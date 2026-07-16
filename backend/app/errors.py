"""Consistent JSON error responses and application-wide error handlers.

Every error the API returns follows the same envelope::

    {"error": "human readable message", "details": {...optional...}}

Routes use :func:`error_response` for validation/404 errors, and the handlers
registered by :func:`register_error_handlers` guarantee the same shape for
uncaught 404/405/500 responses so clients can rely on a single format.
"""
import logging
from typing import Any, Optional

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .utils.validation import ValidationError

logger = logging.getLogger("agentscope")


def error_response(message: str, status: int, details: Optional[dict] = None):
    """Build a ``(json, status)`` tuple in the standard error envelope."""
    payload: dict[str, Any] = {"error": message}
    if details:
        payload["details"] = details
    return jsonify(payload), status


def get_json_body(required: bool = True) -> dict:
    """Return the request body as a JSON object (dict) or raise ``ValidationError``.

    Strict counterpart to ``request.get_json(silent=True) or {}``: malformed
    JSON, a missing/incorrect ``Content-Type`` or (when ``required``) an empty
    body raise a clear 400 — "request body must be valid JSON" or "must be a JSON
    object" — instead of silently degrading to ``{}`` and surfacing a misleading
    downstream "<field> is required". The raised :class:`ValidationError` is
    rendered through :func:`error_response` by the registered handler, so the
    error envelope stays consistent.
    """
    data = request.get_json(silent=True)
    if data is None:
        if not required and not (request.get_data() or b"").strip():
            return {}
        raise ValidationError("request body must be valid JSON")
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")
    return data


def register_error_handlers(app: Flask) -> None:
    """Register handlers so all errors share the standard JSON envelope."""

    @app.errorhandler(ValidationError)
    def _handle_validation_error(exc: ValidationError):
        return error_response(str(exc), 400)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):
        return error_response(exc.description or exc.name, exc.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):  # noqa: BLE001 - last-resort handler
        logger.exception("Unhandled error: %s", exc)
        return error_response("internal server error", 500)
