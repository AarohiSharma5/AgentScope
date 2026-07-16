"""Authentication endpoints (v1.0): register, login, refresh, profile.

Thin routes over :mod:`app.services.auth_service`. All responses follow the
shared JSON envelope. These endpoints are additive and do not alter any
existing route's behavior.
"""
from flask import Blueprint, jsonify, request

from ..auth import current_identity, rate_limited, require_auth
from ..errors import error_response
from ..services import audit_service, auth_service
from ..services.auth_service import AuthServiceError

auth_bp = Blueprint("auth", __name__)


def _json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        return None
    return body


@auth_bp.post("/auth/register")
@rate_limited("5/minute")
def register():
    """Register a new user and their first organization (as admin)."""
    body = _json_body()
    if body is None:
        return error_response("request body must be a JSON object", 400)

    org_name = (body.get("organization_name") or body.get("organization") or "").strip()
    if not org_name:
        return error_response("organization_name is required", 400)

    try:
        user = auth_service.create_user(
            email=body.get("email", ""),
            password=body.get("password", ""),
            name=body.get("name"),
        )
        org, membership = auth_service.create_organization(org_name, user)
    except AuthServiceError as exc:
        return error_response(str(exc), 400)

    tokens = auth_service.issue_tokens(user)
    audit_service.record(
        "user.registered", identity=None, organization_id=org.id,
        target_type="user", target_id=user.id,
    )
    return (
        jsonify(
            {
                "user": user.to_dict(),
                "organization": org.to_dict(),
                "membership": membership.to_dict(),
                "tokens": tokens,
            }
        ),
        201,
    )


@auth_bp.post("/auth/login")
@rate_limited("10/minute")
def login():
    """Exchange email/password for an access + refresh token pair."""
    body = _json_body()
    if body is None:
        return error_response("request body must be a JSON object", 400)

    user = auth_service.authenticate(body.get("email", ""), body.get("password", ""))
    if user is None:
        audit_service.record(
            "user.login_failed", metadata={"email": body.get("email")},
        )
        return error_response("invalid email or password", 401)

    tokens = auth_service.issue_tokens(user)
    audit_service.record("user.login", target_type="user", target_id=user.id,
                         metadata={"user_id": user.id})
    return jsonify({"user": user.to_dict(), "tokens": tokens})


@auth_bp.post("/auth/refresh")
@rate_limited("30/minute")
def refresh():
    """Exchange a refresh token for a new token pair."""
    body = _json_body()
    if body is None:
        return error_response("request body must be a JSON object", 400)
    token = body.get("refresh_token")
    if not token:
        return error_response("refresh_token is required", 400)
    tokens = auth_service.refresh_access_token(token)  # raises AuthError on failure
    return jsonify({"tokens": tokens})


@auth_bp.get("/auth/me")
@require_auth
def me():
    """Return the authenticated principal and (for users) their memberships."""
    identity = current_identity()
    payload = {"identity": identity.to_dict()}
    if identity.auth_type == "jwt":
        from ..extensions import db
        from ..models.auth import User

        user = db.session.get(User, identity.user_id)
        payload["user"] = user.to_dict() if user else None
        payload["memberships"] = [m.to_dict() for m in (user.memberships if user else [])]
    return jsonify(payload)


@auth_bp.post("/auth/change-password")
@require_auth
def change_password():
    """Change the authenticated user's password (JWT only)."""
    identity = current_identity()
    if identity.auth_type != "jwt":
        return error_response("only users can change a password", 403)

    body = _json_body()
    if body is None:
        return error_response("request body must be a JSON object", 400)

    from ..extensions import db
    from ..models.auth import User

    user = db.session.get(User, identity.user_id)
    if user is None or not user.check_password(body.get("current_password", "")):
        return error_response("current password is incorrect", 400)

    new_password = body.get("new_password", "")
    if len(new_password) < 8:
        return error_response("new password must be at least 8 characters", 400)

    user.set_password(new_password)
    db.session.commit()
    # Sever every existing session: a refresh token stolen before the reset must
    # not survive it (M11). Access tokens are short-lived and expire on their own.
    revoked = auth_service.revoke_user_refresh_tokens(user.id)
    audit_service.record("user.password_changed", identity=identity,
                         target_type="user", target_id=user.id,
                         metadata={"revoked_refresh_tokens": revoked})
    return jsonify({"status": "ok"})
