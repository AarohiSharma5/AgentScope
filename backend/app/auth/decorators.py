"""View decorators that enforce authentication and role-based access.

* :func:`require_auth`   — a valid JWT or API key must be present.
* :func:`optional_auth`  — resolve an identity if present (reject bad creds).
* :func:`require_role`    — require a minimum role in the route's organization.

Authorization/isolation logic lives in :mod:`app.services.auth_service`; these
decorators wire it into request handling and stash the identity on ``g``.
"""
from functools import wraps

from .context import current_identity, resolve_identity, set_identity
from .errors import AuthError
from .roles import Role


def require_auth(view):
    """Require any authenticated principal (user or API key)."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        identity = current_identity() or resolve_identity()
        if identity is None:
            raise AuthError()
        set_identity(identity)
        return view(*args, **kwargs)

    return wrapper


def optional_auth(view):
    """Resolve an identity when supplied; never require one."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_identity() is None:
            set_identity(resolve_identity())
        return view(*args, **kwargs)

    return wrapper


def require_role(min_role: str = Role.VIEWER, org_arg: str = "org_id"):
    """Require the principal to hold ``min_role`` in the route's organization.

    The organization id is read from the view's ``org_arg`` keyword argument.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            # Imported lazily to avoid an import cycle at module load.
            from ..services import auth_service

            identity = current_identity() or resolve_identity()
            if identity is None:
                raise AuthError()
            set_identity(identity)
            auth_service.authorize_org(identity, kwargs.get(org_arg), min_role)
            return view(*args, **kwargs)

        return wrapper

    return decorator
