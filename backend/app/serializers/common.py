"""Shared serialization helpers used across serializer modules."""
from datetime import datetime
from typing import Optional


def iso(value: Optional[datetime]) -> Optional[str]:
    """Return an ISO-8601 string for a datetime, or None."""
    return value.isoformat() if value else None
