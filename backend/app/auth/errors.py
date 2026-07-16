"""Auth-specific exceptions and their JSON error handlers.

Kept separate from the core ``errors`` module so the auth subsystem is fully
self-contained and additive. :func:`register_auth_error_handlers` wires the
handlers into the app factory.
"""
from flask import Flask

from ..errors import error_response


class AuthError(Exception):
    """Authentication failed or is missing (HTTP 401)."""

    status = 401

    def __init__(self, message: str = "authentication required"):
        super().__init__(message)
        self.message = message


class AuthzError(Exception):
    """Authenticated, but not permitted (HTTP 403)."""

    status = 403

    def __init__(self, message: str = "you do not have permission to perform this action"):
        super().__init__(message)
        self.message = message


class RateLimitError(Exception):
    """Too many requests (HTTP 429)."""

    status = 429

    def __init__(self, message: str = "rate limit exceeded", retry_after: int = 1):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


def register_auth_error_handlers(app: Flask) -> None:
    """Register handlers so auth errors use the standard JSON envelope."""

    @app.errorhandler(AuthError)
    def _handle_auth(exc: AuthError):
        return error_response(exc.message, exc.status)

    @app.errorhandler(AuthzError)
    def _handle_authz(exc: AuthzError):
        return error_response(exc.message, exc.status)

    @app.errorhandler(RateLimitError)
    def _handle_rate_limit(exc: RateLimitError):
        response, status = error_response(exc.message, exc.status)
        response.headers["Retry-After"] = str(exc.retry_after)
        return response, status
