"""Per-request auth identity resolution and access.

An :class:`Identity` describes the authenticated principal for the current
request — either a user (via JWT) or an API key. It is stashed on Flask's ``g``
so decorators, services and audit logging can read it without re-parsing
credentials.
"""
from dataclasses import dataclass
from typing import Optional

from flask import current_app, g, request

from ..extensions import db
from ..models.auth import ApiKey, User
from ..utils.timeutils import utcnow
from . import tokens
from .errors import AuthError
from .keys import hash_key

_IDENTITY_ATTR = "agentscope_identity"


@dataclass
class Identity:
    """The authenticated principal for a request."""

    auth_type: str  # "jwt" or "api_key"
    user_id: Optional[int] = None
    email: Optional[str] = None
    is_superadmin: bool = False
    api_key_id: Optional[int] = None
    organization_id: Optional[int] = None
    project_id: Optional[int] = None
    role: Optional[str] = None  # role carried by an API key

    @property
    def principal_id(self) -> str:
        """A stable identifier for rate limiting / audit."""
        if self.auth_type == "api_key":
            return f"key:{self.api_key_id}"
        return f"user:{self.user_id}"

    def to_dict(self) -> dict:
        return {
            "auth_type": self.auth_type,
            "user_id": self.user_id,
            "email": self.email,
            "is_superadmin": self.is_superadmin,
            "api_key_id": self.api_key_id,
            "organization_id": self.organization_id,
            "project_id": self.project_id,
            "role": self.role,
        }


def set_identity(identity: Optional[Identity]) -> None:
    setattr(g, _IDENTITY_ATTR, identity)


def current_identity() -> Optional[Identity]:
    return getattr(g, _IDENTITY_ATTR, None)


def resolve_identity() -> Optional[Identity]:
    """Resolve an :class:`Identity` from request credentials.

    Supports ``Authorization: Bearer <jwt>`` and ``X-API-Key: <key>``. Returns
    ``None`` when no credentials are present, and raises :class:`AuthError` when
    credentials are present but invalid.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return _identity_from_jwt(auth_header[7:].strip())

    api_key = request.headers.get("X-API-Key")
    if api_key:
        return _identity_from_api_key(api_key.strip())

    return None


def _identity_from_jwt(token: str) -> Identity:
    secret = current_app.config["JWT_SECRET"]
    try:
        claims = tokens.decode(token, secret, expected_type="access")
    except tokens.ExpiredToken:
        raise AuthError("access token has expired")
    except tokens.TokenError:
        raise AuthError("invalid access token")

    user = db.session.get(User, claims.get("sub"))
    if user is None or not user.is_active:
        raise AuthError("user not found or inactive")
    return Identity(
        auth_type="jwt",
        user_id=user.id,
        email=user.email,
        is_superadmin=user.is_superadmin,
    )


def _identity_from_api_key(raw: str) -> Identity:
    key = ApiKey.query.filter_by(key_hash=hash_key(raw)).first()
    if key is None or not key.is_valid():
        raise AuthError("invalid or revoked API key")
    key.last_used_at = utcnow()
    db.session.commit()
    return Identity(
        auth_type="api_key",
        api_key_id=key.id,
        organization_id=key.organization_id,
        project_id=key.project_id,
        role=key.role,
    )
