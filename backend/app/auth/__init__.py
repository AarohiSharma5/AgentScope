"""Authentication & authorization subsystem (v1.0).

Additive and backward compatible: importing this package has no side effects on
existing routes. Enforcement is opt-in via the decorators below.
"""
from .context import (
    Identity,
    current_identity,
    current_organization_id,
    resolve_identity,
    set_identity,
    tenant_scope,
)
from .decorators import optional_auth, require_auth, require_role
from .errors import (
    AuthError,
    AuthzError,
    RateLimitError,
    register_auth_error_handlers,
)
from .rate_limit import limiter, rate_limited
from .roles import Role, is_valid_role, role_satisfies

__all__ = [
    "Identity",
    "current_identity",
    "current_organization_id",
    "tenant_scope",
    "resolve_identity",
    "set_identity",
    "require_auth",
    "optional_auth",
    "require_role",
    "AuthError",
    "AuthzError",
    "RateLimitError",
    "register_auth_error_handlers",
    "rate_limited",
    "limiter",
    "Role",
    "is_valid_role",
    "role_satisfies",
]
