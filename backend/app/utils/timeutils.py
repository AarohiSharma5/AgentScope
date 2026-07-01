"""Small time helpers shared across models, services and the SDK.

Centralising ``utcnow`` avoids the same timezone-aware helper being redefined in
several modules and guarantees every timestamp is stored in UTC.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC ``datetime``."""
    return datetime.now(timezone.utc)
