"""Lightweight validation helpers for JSON-typed fields.

The agent-tracing models persist several ``JSON`` columns (metadata, token
usage, tool arguments, retrieved documents). SQLite and PostgreSQL will both
happily accept anything JSON-serialisable, so these helpers reject values that
would either fail to serialise or violate the expected shape *before* they reach
the database, turning obscure driver errors into clear validation errors.
"""
import json
from typing import Any, Optional


class ValidationError(ValueError):
    """Raised when a value cannot be stored in a JSON column as expected."""


def _is_json_serializable(value: Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def ensure_json_object(value: Any, field: str) -> Optional[dict]:
    """Validate that ``value`` is a JSON-serialisable object (dict) or None.

    Returns the value unchanged so it can be used inline.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationError(f"{field} must be a JSON object")
    if not _is_json_serializable(value):
        raise ValidationError(f"{field} must be JSON-serializable")
    return value


def ensure_json_array(value: Any, field: str) -> Optional[list]:
    """Validate that ``value`` is a JSON-serialisable array (list) or None."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a JSON array")
    if not _is_json_serializable(value):
        raise ValidationError(f"{field} must be JSON-serializable")
    return value
