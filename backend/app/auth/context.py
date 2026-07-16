"""Per-request auth identity resolution and access.

An :class:`Identity` describes the authenticated principal for the current
request — either a user (via JWT) or an API key. It is stashed on Flask's ``g``
so decorators, services and audit logging can read it without re-parsing
credentials.
"""
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from flask import current_app, g, has_request_context, request

from ..extensions import db
from ..models.auth import ApiKey, User
from ..utils.timeutils import utcnow
from . import tokens
from .errors import AuthError, AuthzError
from .keys import hash_key

logger = logging.getLogger(__name__)

_IDENTITY_ATTR = "agentscope_identity"

#: Debounce window (seconds) for persisting ``ApiKey.last_used_at``. Updating it
#: on every authenticated request causes write amplification and row-lock
#: contention on a hot key under ingest-heavy traffic. Instead we remember, per
#: process, when each key was last persisted and skip the write until the window
#: elapses — so a key hit thousands of times a minute yields at most one UPDATE
#: per window. Overridable via ``API_KEY_LAST_USED_DEBOUNCE_SECONDS`` (0 = write
#: every request, the old behavior).
_DEFAULT_LAST_USED_DEBOUNCE_SECONDS = 60
_last_used_flushed: dict[int, datetime] = {}
_last_used_lock = threading.Lock()

#: Sentinel organization id used to scope an authenticated-but-org-less principal
#: to *no* rows. Organization ids are positive autoincrement values, so filtering
#: ``organization_id == _NO_TENANT`` can never match — a deny-by-default read
#: scope, rather than silently falling back to "see everything".
_NO_TENANT = -1


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


def current_organization_id() -> Optional[int]:
    """Active organization of the current principal, or ``None``.

    Used to *stamp* ownership on writes. An API key carries a single org; a JWT
    user's active org is resolved at authentication time (see
    :func:`_resolve_active_org`). Safe to call outside a request (returns
    ``None``).
    """
    if not has_request_context():
        return None
    identity = current_identity()
    return identity.organization_id if identity is not None else None


def tenant_scope() -> Optional[int]:
    """Organization id that reads should be restricted to, or ``None``.

    Scoping only applies when auth is enforced (``AUTH_ENABLED``); with auth off,
    reads are unscoped (backward-compatible single-tenant behavior). When on:

    * a super-admin with no selected org sees everything (admin view);
    * any principal with an active org is scoped to it (API key, or a JWT user's
      resolved active org);
    * an authenticated principal *without* an active org (e.g. a JWT user who
      belongs to several orgs and did not pick one) is scoped to
      :data:`_NO_TENANT` so they see nothing rather than every tenant's data.
    """
    if not has_request_context() or not current_app.config.get("AUTH_ENABLED"):
        return None
    identity = current_identity()
    if identity is None:
        # Auth is enforced but no principal resolved on this request: deny by
        # default rather than fall through to "see everything".
        return _NO_TENANT
    if identity.organization_id is not None:
        return identity.organization_id
    if identity.is_superadmin:
        return None
    return _NO_TENANT


def resolve_identity() -> Optional[Identity]:
    """Resolve an :class:`Identity` from request credentials.

    Supports ``Authorization: Bearer <jwt>`` and ``X-API-Key: <key>``. As a
    fallback (for ``EventSource``/SSE, which cannot set request headers) an
    ``access_token`` or ``api_key`` query parameter is also accepted. Returns
    ``None`` when no credentials are present, and raises :class:`AuthError` when
    credentials are present but invalid.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return _identity_from_jwt(auth_header[7:].strip())

    api_key = request.headers.get("X-API-Key")
    if api_key:
        return _identity_from_api_key(api_key.strip())

    # Query-param fallback for header-less clients (SSE). Only used when no
    # credential header was supplied.
    query_token = request.args.get("access_token")
    if query_token:
        return _identity_from_jwt(query_token.strip())

    query_key = request.args.get("api_key")
    if query_key:
        return _identity_from_api_key(query_key.strip())

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
    org_id, role = _resolve_active_org(user)
    return Identity(
        auth_type="jwt",
        user_id=user.id,
        email=user.email,
        is_superadmin=user.is_superadmin,
        organization_id=org_id,
        role=role,
    )


def _resolve_active_org(user: User) -> tuple[Optional[int], Optional[str]]:
    """Resolve a JWT user's active organization (and their role within it).

    Priority: an explicit ``X-Organization-Id`` header (validated against the
    user's memberships), else their sole membership when they belong to exactly
    one organization, else unresolved (``None``). A super-admin may act in any
    org via the header without a membership.
    """
    from ..models.auth import Membership

    requested = request.headers.get("X-Organization-Id")
    if requested:
        try:
            org_id = int(requested)
        except (TypeError, ValueError):
            raise AuthError("X-Organization-Id must be an integer")
        membership = Membership.query.filter_by(
            user_id=user.id, organization_id=org_id
        ).first()
        if membership is not None:
            return org_id, membership.role
        if user.is_superadmin:
            return org_id, None
        raise AuthzError("you are not a member of the requested organization")

    memberships = Membership.query.filter_by(user_id=user.id).all()
    if len(memberships) == 1:
        return memberships[0].organization_id, memberships[0].role
    return None, None


def _identity_from_api_key(raw: str) -> Identity:
    key = ApiKey.query.filter_by(key_hash=hash_key(raw)).first()
    if key is None or not key.is_valid():
        raise AuthError("invalid or revoked API key")
    _touch_last_used(key)
    return Identity(
        auth_type="api_key",
        api_key_id=key.id,
        organization_id=key.organization_id,
        project_id=key.project_id,
        role=key.role,
    )


def _debounce_interval() -> float:
    """Configured debounce window in seconds (falls back to the default)."""
    if has_request_context():
        return current_app.config.get(
            "API_KEY_LAST_USED_DEBOUNCE_SECONDS", _DEFAULT_LAST_USED_DEBOUNCE_SECONDS
        )
    return _DEFAULT_LAST_USED_DEBOUNCE_SECONDS


def _should_flush_last_used(key_id: int, now: datetime, interval: float) -> bool:
    """True at most once per ``interval`` seconds per key (thread-safe).

    The slot is reserved *inside* the lock, so a burst of concurrent requests for
    the same hot key produces a single writer rather than a thundering herd all
    updating the same row at once.
    """
    with _last_used_lock:
        last = _last_used_flushed.get(key_id)
        if last is not None and (now - last).total_seconds() < interval:
            return False
        _last_used_flushed[key_id] = now
        return True


def _touch_last_used(key: ApiKey) -> None:
    """Persist ``last_used_at``, debounced to at most once per window per key.

    Best-effort telemetry: a failure here must never break authentication, so we
    roll back and continue (releasing the reservation so a later request retries).
    """
    interval = _debounce_interval()
    now = utcnow()
    # interval == 0 disables debouncing (write on every request, old behavior).
    if interval and not _should_flush_last_used(key.id, now, interval):
        return
    key.last_used_at = now
    try:
        db.session.commit()
    except Exception:  # pragma: no cover - defensive; auth must not fail on this
        db.session.rollback()
        with _last_used_lock:
            _last_used_flushed.pop(key.id, None)
        logger.warning(
            "failed to persist api_key.last_used_at for key id=%s", key.id, exc_info=True
        )
