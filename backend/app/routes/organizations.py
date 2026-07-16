"""Tenancy endpoints (v1.0): organizations, members, projects, API keys, audit.

Enforces organization and project isolation plus RBAC via the auth decorators
and :mod:`app.services.auth_service`. Routes remain thin.
"""
from flask import Blueprint, jsonify, request

from ..auth import Role, current_identity, require_auth, require_role
from ..errors import error_response
from ..services import audit_service, auth_service
from ..services.auth_service import AuthServiceError
from ..utils.pagination import PaginationError, paginated, parse_page_limit

orgs_bp = Blueprint("organizations", __name__)


def _json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        return None
    return body


def _effective_role(org_id: int) -> str:
    """The current principal's role in ``org_id`` (already authorized)."""
    identity = current_identity()
    if identity.auth_type == "api_key":
        return identity.role or Role.VIEWER
    if getattr(identity, "is_superadmin", False) and identity.role is None:
        return Role.ADMIN
    return identity.role or Role.VIEWER


# -- organizations ----------------------------------------------------------


@orgs_bp.get("/organizations")
@require_auth
def list_organizations():
    """List organizations the current user belongs to (paginated)."""
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)

    identity = current_identity()
    if identity.auth_type != "jwt":
        # An API key is scoped to a single organization: a fixed one-item page.
        org = auth_service.get_organization(identity.organization_id)
        items = [org.to_dict()] if org and page == 1 else []
        return jsonify(paginated(items, page, limit, 1 if org else 0))

    from ..extensions import db
    from ..models.auth import User

    user = db.session.get(User, identity.user_id)
    orgs, total = auth_service.list_user_organizations_page(user, page, limit)
    return jsonify(paginated([o.to_dict() for o in orgs], page, limit, total))


@orgs_bp.post("/organizations")
@require_auth
def create_organization():
    """Create a new organization (the creator becomes its admin)."""
    identity = current_identity()
    if identity.auth_type != "jwt":
        return error_response("only users can create organizations", 403)

    body = _json_body()
    if body is None:
        return error_response("request body must be a JSON object", 400)

    from ..extensions import db
    from ..models.auth import User

    user = db.session.get(User, identity.user_id)
    try:
        org, membership = auth_service.create_organization(body.get("name", ""), user)
    except AuthServiceError as exc:
        return error_response(str(exc), 400)

    audit_service.record("organization.created", identity=identity,
                         organization_id=org.id, target_type="organization", target_id=org.id)
    return jsonify({"organization": org.to_dict(), "membership": membership.to_dict()}), 201


@orgs_bp.get("/organizations/<int:org_id>")
@require_role(Role.VIEWER)
def get_organization(org_id: int):
    org = auth_service.get_organization(org_id)
    if org is None:
        return error_response("organization not found", 404)
    return jsonify(org.to_dict())


# -- members ----------------------------------------------------------------


@orgs_bp.get("/organizations/<int:org_id>/members")
@require_role(Role.VIEWER)
def list_members(org_id: int):
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)
    members, total = auth_service.list_members_page(org_id, page, limit)
    return jsonify(paginated([m.to_dict() for m in members], page, limit, total))


@orgs_bp.post("/organizations/<int:org_id>/members")
@require_role(Role.ADMIN)
def add_member(org_id: int):
    body = _json_body()
    if body is None:
        return error_response("request body must be a JSON object", 400)
    try:
        membership = auth_service.add_member(
            org_id, body.get("email", ""), body.get("role", Role.VIEWER),
            actor_role=_effective_role(org_id),
        )
    except AuthServiceError as exc:
        return error_response(str(exc), 400)
    audit_service.record("member.added", identity=current_identity(), organization_id=org_id,
                         target_type="user", target_id=membership.user_id,
                         metadata={"role": membership.role})
    return jsonify(membership.to_dict()), 201


@orgs_bp.patch("/organizations/<int:org_id>/members/<int:user_id>")
@require_role(Role.ADMIN)
def update_member(org_id: int, user_id: int):
    body = _json_body()
    if body is None:
        return error_response("request body must be a JSON object", 400)
    try:
        membership = auth_service.update_member_role(
            org_id, user_id, body.get("role", ""), actor_role=_effective_role(org_id)
        )
    except AuthServiceError as exc:
        return error_response(str(exc), 400)
    audit_service.record("member.role_changed", identity=current_identity(), organization_id=org_id,
                         target_type="user", target_id=user_id, metadata={"role": membership.role})
    return jsonify(membership.to_dict())


@orgs_bp.delete("/organizations/<int:org_id>/members/<int:user_id>")
@require_role(Role.ADMIN)
def remove_member(org_id: int, user_id: int):
    try:
        removed = auth_service.remove_member(org_id, user_id)
    except AuthServiceError as exc:
        return error_response(str(exc), 400)
    if not removed:
        return error_response("membership not found", 404)
    audit_service.record("member.removed", identity=current_identity(), organization_id=org_id,
                         target_type="user", target_id=user_id)
    return jsonify({"status": "ok"})


# -- projects ---------------------------------------------------------------


@orgs_bp.get("/organizations/<int:org_id>/projects")
@require_role(Role.VIEWER)
def list_projects(org_id: int):
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)
    projects, total = auth_service.list_projects_page(org_id, page, limit)
    return jsonify(paginated([p.to_dict() for p in projects], page, limit, total))


@orgs_bp.post("/organizations/<int:org_id>/projects")
@require_role(Role.DEVELOPER)
def create_project(org_id: int):
    body = _json_body()
    if body is None:
        return error_response("request body must be a JSON object", 400)
    try:
        project = auth_service.create_project(org_id, body.get("name", ""))
    except AuthServiceError as exc:
        return error_response(str(exc), 400)
    audit_service.record("project.created", identity=current_identity(), organization_id=org_id,
                         project_id=project.id, target_type="project", target_id=project.id)
    return jsonify(project.to_dict()), 201


@orgs_bp.get("/projects/<int:project_id>")
@require_auth
def get_project(project_id: int):
    try:
        project = auth_service.authorize_project(current_identity(), project_id, Role.VIEWER)
    except AuthServiceError as exc:
        return error_response(str(exc), 404)
    return jsonify(project.to_dict())


# -- API keys ---------------------------------------------------------------


@orgs_bp.get("/organizations/<int:org_id>/api-keys")
@require_role(Role.DEVELOPER)
def list_api_keys(org_id: int):
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)
    project_id = request.args.get("project_id", type=int)
    keys, total = auth_service.list_api_keys_page(org_id, page, limit, project_id=project_id)
    return jsonify(paginated([k.to_dict() for k in keys], page, limit, total))


@orgs_bp.post("/organizations/<int:org_id>/api-keys")
@require_role(Role.DEVELOPER)
def create_api_key(org_id: int):
    body = _json_body()
    if body is None:
        return error_response("request body must be a JSON object", 400)
    identity = current_identity()
    try:
        key, raw = auth_service.create_api_key(
            org_id,
            name=body.get("name", ""),
            role=body.get("role", Role.DEVELOPER),
            actor_role=_effective_role(org_id),
            project_id=body.get("project_id"),
            created_by_user_id=identity.user_id,
        )
    except AuthServiceError as exc:
        return error_response(str(exc), 400)
    audit_service.record("api_key.created", identity=identity, organization_id=org_id,
                         project_id=key.project_id, target_type="api_key", target_id=key.id)
    # The raw secret is returned exactly once.
    return jsonify(key.to_dict(include_secret=raw)), 201


@orgs_bp.delete("/organizations/<int:org_id>/api-keys/<int:key_id>")
@require_role(Role.ADMIN)
def revoke_api_key(org_id: int, key_id: int):
    if not auth_service.revoke_api_key(org_id, key_id):
        return error_response("API key not found", 404)
    audit_service.record("api_key.revoked", identity=current_identity(), organization_id=org_id,
                         target_type="api_key", target_id=key_id)
    return jsonify({"status": "ok"})


# -- audit logs -------------------------------------------------------------


@orgs_bp.get("/organizations/<int:org_id>/audit-logs")
@require_role(Role.ADMIN)
def list_audit_logs(org_id: int):
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)
    items, total = audit_service.list_for_org(
        org_id, page, limit, action=request.args.get("action")
    )
    return jsonify(paginated([i.to_dict() for i in items], page, limit, total))
