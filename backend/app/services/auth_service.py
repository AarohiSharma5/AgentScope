"""Business logic for authentication, tenancy, RBAC and API keys (v1.0).

Routes stay thin: they validate input and call these functions, which own all
SQLAlchemy access, password/token handling, organization isolation and role
checks. No business logic lives in the route layer.
"""
import logging
import re
import secrets
from datetime import timedelta, timezone
from typing import List, Optional, Tuple

from flask import current_app

from ..auth import keys, tokens
from ..auth.errors import AuthError, AuthzError
from ..auth.roles import Role, is_valid_role, role_satisfies
from ..extensions import db
from ..models.auth import ApiKey, Membership, Organization, Project, RefreshToken, User
from ..utils.timeutils import utcnow

logger = logging.getLogger("agentscope")


class AuthServiceError(ValueError):
    """A user-facing validation error in the auth service."""


# -- helpers ----------------------------------------------------------------


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "org"


def _unique_org_slug(name: str) -> str:
    base = slugify(name)
    slug, i = base, 2
    while Organization.query.filter_by(slug=slug).first() is not None:
        slug = f"{base}-{i}"
        i += 1
    return slug


def _unique_project_slug(org_id: int, name: str) -> str:
    base = slugify(name)
    slug, i = base, 2
    while Project.query.filter_by(organization_id=org_id, slug=slug).first() is not None:
        slug = f"{base}-{i}"
        i += 1
    return slug


def _aware(dt):
    """Normalize a possibly-naive datetime (SQLite) to timezone-aware UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# -- users & authentication -------------------------------------------------


def get_user_by_email(email: str) -> Optional[User]:
    return User.query.filter_by(email=(email or "").strip().lower()).first()


def validate_password(password: str) -> None:
    """Enforce the password policy, raising :class:`AuthServiceError` on failure.

    Policy: at least ``PASSWORD_MIN_LENGTH`` characters (default 8) and a mix of
    at least one letter and one digit, so trivially guessable passwords (all
    digits, dictionary words) are rejected. Shared by registration and password
    change so both apply the same rules.
    """
    min_len = int(current_app.config.get("PASSWORD_MIN_LENGTH", 8))
    if not password or len(password) < min_len:
        raise AuthServiceError(f"password must be at least {min_len} characters")
    if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        raise AuthServiceError("password must contain at least one letter and one number")


def create_user(email: str, password: str, name: Optional[str] = None,
                is_superadmin: bool = False) -> User:
    """Create a user with a securely hashed password."""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise AuthServiceError("a valid email is required")
    validate_password(password)
    if get_user_by_email(email) is not None:
        raise AuthServiceError("a user with this email already exists")

    user = User(email=email, name=name, is_superadmin=is_superadmin)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    logger.info("Created user id=%s email=%s", user.id, user.email)
    return user


def authenticate(email: str, password: str) -> Optional[User]:
    """Return the user when credentials are valid and the account is active."""
    user = get_user_by_email(email)
    if user is None or not user.is_active or not user.check_password(password):
        return None
    user.last_login_at = utcnow()
    db.session.commit()
    return user


# -- JWT issuance -----------------------------------------------------------


def _jwt_config() -> Tuple[str, int, int, Optional[str]]:
    """Return ``(secret, access_ttl, refresh_ttl, issuer)`` from app config."""
    return (
        current_app.config["JWT_SECRET"],
        int(current_app.config["JWT_ACCESS_TTL"]),
        int(current_app.config["JWT_REFRESH_TTL"]),
        current_app.config.get("JWT_ISSUER") or None,
    )


def _mint_token_pair(user: User, family_id: str) -> dict:
    """Record a new refresh token in ``family_id`` and mint a matching pair.

    Each pair carries a fresh ``jti`` persisted in :class:`RefreshToken`, so the
    refresh side is revocable and single-use (see :func:`refresh_access_token`).
    Commits the new record together with any pending rotation bookkeeping.
    """
    secret, access_ttl, refresh_ttl, issuer = _jwt_config()
    jti = secrets.token_hex(16)
    db.session.add(
        RefreshToken(
            jti=jti,
            family_id=family_id,
            user_id=user.id,
            expires_at=utcnow() + timedelta(seconds=refresh_ttl),
        )
    )
    db.session.commit()
    access_claims = {"sub": user.id, "email": user.email, "iss": issuer}
    refresh_claims = {"sub": user.id, "jti": jti, "fam": family_id, "iss": issuer}
    return {
        "token_type": "Bearer",
        "expires_in": access_ttl,
        "access_token": tokens.encode(access_claims, secret, expires_in=access_ttl, token_type="access"),
        "refresh_token": tokens.encode(refresh_claims, secret, expires_in=refresh_ttl, token_type="refresh"),
    }


def issue_tokens(user: User) -> dict:
    """Start a new refresh-token family and mint the first access+refresh pair."""
    return _mint_token_pair(user, secrets.token_hex(16))


def _revoke_family(family_id: str) -> None:
    RefreshToken.query.filter_by(family_id=family_id, revoked=False).update(
        {"revoked": True}, synchronize_session=False
    )


def revoke_user_refresh_tokens(user_id: int) -> int:
    """Revoke every active refresh token for a user; return how many were revoked.

    Called on password change so a stolen refresh token stops working immediately
    instead of remaining valid for the rest of its (up to 30-day) TTL.
    """
    count = RefreshToken.query.filter_by(user_id=user_id, revoked=False).update(
        {"revoked": True}, synchronize_session=False
    )
    db.session.commit()
    return count


def refresh_access_token(refresh_token: str) -> dict:
    """Rotate a valid refresh token, returning a fresh access+refresh pair.

    Refresh tokens are single-use: the presented token is revoked and replaced by
    a new one in the same family. Presenting an already-rotated or revoked token
    (the classic signature of a stolen token being replayed) revokes the entire
    family so the legitimate user's session is severed too, forcing re-login.
    """
    secret, _, _, issuer = _jwt_config()
    try:
        claims = tokens.decode(refresh_token, secret, expected_type="refresh", issuer=issuer)
    except tokens.ExpiredToken:
        raise AuthError("refresh token has expired")
    except tokens.TokenError:
        raise AuthError("invalid refresh token")

    jti = claims.get("jti")
    record = RefreshToken.query.filter_by(jti=jti).first() if jti else None
    if record is None:
        raise AuthError("invalid refresh token")
    if record.revoked or record.used_at is not None:
        # Reuse of a rotated/revoked token: treat as compromise, kill the family.
        _revoke_family(record.family_id)
        db.session.commit()
        raise AuthError("refresh token has been revoked")
    if _aware(record.expires_at) is not None and _aware(record.expires_at) <= utcnow():
        raise AuthError("refresh token has expired")

    user = db.session.get(User, record.user_id)
    if user is None or not user.is_active:
        raise AuthError("user not found or inactive")

    record.used_at = utcnow()
    record.revoked = True
    return _mint_token_pair(user, record.family_id)


# -- organizations & memberships --------------------------------------------


def create_organization(name: str, owner: User) -> Tuple[Organization, Membership]:
    """Create an organization and make ``owner`` its admin."""
    if not (name or "").strip():
        raise AuthServiceError("organization name is required")
    org = Organization(name=name.strip(), slug=_unique_org_slug(name))
    db.session.add(org)
    db.session.flush()
    membership = Membership(user_id=owner.id, organization_id=org.id, role=Role.ADMIN)
    db.session.add(membership)
    db.session.commit()
    logger.info("Created organization id=%s owner=%s", org.id, owner.id)
    return org, membership


def get_organization(org_id: int) -> Optional[Organization]:
    return db.session.get(Organization, org_id)


def list_user_organizations(user: User) -> List[Organization]:
    return _user_organizations_query(user).all()


def _user_organizations_query(user: User):
    return (
        Organization.query.join(Membership, Membership.organization_id == Organization.id)
        .filter(Membership.user_id == user.id)
        .order_by(Organization.created_at.asc())
    )


def list_user_organizations_page(
    user: User, page: int, limit: int
) -> Tuple[List[Organization], int]:
    """Return a page of the user's organizations and the total count."""
    query = _user_organizations_query(user)
    total = query.count()
    items = query.limit(limit).offset((page - 1) * limit).all()
    return items, total


def get_membership(user_id: int, org_id: int) -> Optional[Membership]:
    return Membership.query.filter_by(user_id=user_id, organization_id=org_id).first()


def list_members(org_id: int) -> List[Membership]:
    return Membership.query.filter_by(organization_id=org_id).all()


def list_members_page(
    org_id: int, page: int, limit: int
) -> Tuple[List[Membership], int]:
    """Return a bounded page of an organization's members and the total count."""
    query = Membership.query.filter_by(organization_id=org_id).order_by(Membership.id.asc())
    total = query.count()
    items = query.limit(limit).offset((page - 1) * limit).all()
    return items, total


def add_member(org_id: int, email: str, role: str, actor_role: str) -> Membership:
    """Add an existing user to an organization with a role."""
    _validate_grantable_role(role, actor_role)
    user = get_user_by_email(email)
    if user is None:
        raise AuthServiceError("no user with that email exists")
    if get_membership(user.id, org_id) is not None:
        raise AuthServiceError("user is already a member of this organization")
    membership = Membership(user_id=user.id, organization_id=org_id, role=role)
    db.session.add(membership)
    db.session.commit()
    return membership


def update_member_role(org_id: int, user_id: int, role: str, actor_role: str) -> Membership:
    _validate_grantable_role(role, actor_role)
    membership = get_membership(user_id, org_id)
    if membership is None:
        raise AuthServiceError("membership not found")
    membership.role = role
    db.session.commit()
    return membership


def remove_member(org_id: int, user_id: int) -> bool:
    membership = get_membership(user_id, org_id)
    if membership is None:
        return False
    # Never leave an organization without an admin.
    if membership.role == Role.ADMIN and _admin_count(org_id) <= 1:
        raise AuthServiceError("cannot remove the last admin of an organization")
    db.session.delete(membership)
    db.session.commit()
    return True


def _admin_count(org_id: int) -> int:
    return Membership.query.filter_by(organization_id=org_id, role=Role.ADMIN).count()


def _validate_grantable_role(role: str, actor_role: str) -> None:
    if not is_valid_role(role):
        raise AuthServiceError(f"invalid role; must be one of {sorted(Role.ALL)}")
    # Cannot grant a role more privileged than your own.
    if not role_satisfies(actor_role, role):
        raise AuthzError("you cannot grant a role higher than your own")


# -- authorization / isolation ----------------------------------------------


def authorize_org(identity, org_id: Optional[int], min_role: str = Role.VIEWER):
    """Enforce that ``identity`` may act in ``org_id`` at ``min_role``.

    Returns the effective role. Raises :class:`AuthError`/:class:`AuthzError`.
    This is the single choke point for organization isolation.
    """
    if org_id is None:
        raise AuthzError("organization context is required")

    # Platform superadmins bypass membership checks.
    if getattr(identity, "is_superadmin", False):
        return Role.ADMIN

    if identity.auth_type == "api_key":
        if identity.organization_id != org_id:
            raise AuthzError("API key is not scoped to this organization")
        effective = identity.role or Role.VIEWER
    else:  # jwt / user
        membership = get_membership(identity.user_id, org_id)
        if membership is None:
            raise AuthzError("you are not a member of this organization")
        effective = membership.role
        identity.role = effective

    identity.organization_id = org_id
    if not role_satisfies(effective, min_role):
        raise AuthzError(f"this action requires the '{min_role}' role")
    return effective


def authorize_project(identity, project_id: int, min_role: str = Role.VIEWER) -> Project:
    """Enforce access to a project within its organization (project isolation)."""
    project = db.session.get(Project, project_id)
    if project is None:
        raise AuthServiceError("project not found")
    authorize_org(identity, project.organization_id, min_role)
    # API keys bound to a specific project may only touch that project.
    if identity.auth_type == "api_key" and identity.project_id not in (None, project_id):
        raise AuthzError("API key is not scoped to this project")
    return project


# -- projects ---------------------------------------------------------------


def create_project(org_id: int, name: str) -> Project:
    if not (name or "").strip():
        raise AuthServiceError("project name is required")
    project = Project(
        organization_id=org_id, name=name.strip(), slug=_unique_project_slug(org_id, name)
    )
    db.session.add(project)
    db.session.commit()
    return project


def list_projects(org_id: int) -> List[Project]:
    return _projects_query(org_id).all()


def _projects_query(org_id: int):
    return Project.query.filter_by(organization_id=org_id).order_by(Project.created_at.asc())


def list_projects_page(
    org_id: int, page: int, limit: int
) -> Tuple[List[Project], int]:
    """Return a bounded page of an organization's projects and the total count."""
    query = _projects_query(org_id)
    total = query.count()
    items = query.limit(limit).offset((page - 1) * limit).all()
    return items, total


# -- API keys ---------------------------------------------------------------


def create_api_key(
    org_id: int,
    name: str,
    role: str,
    actor_role: str,
    project_id: Optional[int] = None,
    created_by_user_id: Optional[int] = None,
    expires_at=None,
) -> Tuple[ApiKey, str]:
    """Create an API key, returning ``(key, raw_secret)`` (secret shown once)."""
    if not (name or "").strip():
        raise AuthServiceError("API key name is required")
    _validate_grantable_role(role, actor_role)
    if project_id is not None:
        project = db.session.get(Project, project_id)
        if project is None or project.organization_id != org_id:
            raise AuthServiceError("project not found in this organization")

    prefix = current_app.config.get("API_KEY_PREFIX", "as")
    raw, display_prefix, key_hash = keys.new_key(prefix)
    api_key = ApiKey(
        organization_id=org_id,
        project_id=project_id,
        name=name.strip(),
        prefix=display_prefix,
        key_hash=key_hash,
        role=role,
        created_by_user_id=created_by_user_id,
        expires_at=expires_at,
    )
    db.session.add(api_key)
    db.session.commit()
    return api_key, raw


def list_api_keys(org_id: int, project_id: Optional[int] = None) -> List[ApiKey]:
    return _api_keys_query(org_id, project_id).all()


def _api_keys_query(org_id: int, project_id: Optional[int] = None):
    query = ApiKey.query.filter_by(organization_id=org_id)
    if project_id is not None:
        query = query.filter_by(project_id=project_id)
    return query.order_by(ApiKey.created_at.desc())


def list_api_keys_page(
    org_id: int, page: int, limit: int, project_id: Optional[int] = None
) -> Tuple[List[ApiKey], int]:
    """Return a bounded page of an organization's API keys and the total count."""
    query = _api_keys_query(org_id, project_id)
    total = query.count()
    items = query.limit(limit).offset((page - 1) * limit).all()
    return items, total


def get_api_key(org_id: int, key_id: int) -> Optional[ApiKey]:
    key = db.session.get(ApiKey, key_id)
    if key is None or key.organization_id != org_id:
        return None
    return key


def revoke_api_key(org_id: int, key_id: int) -> bool:
    key = get_api_key(org_id, key_id)
    if key is None:
        return False
    key.revoked = True
    db.session.commit()
    return True
