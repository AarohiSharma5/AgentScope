"""Shared pagination helpers for list endpoints.

Keeps the ``{"data": [...], "pagination": {...}}`` envelope identical across every
collection endpoint so clients can rely on one shape.
"""
from typing import Any


def paginated(items: list[Any], page: int, limit: int, total: int) -> dict:
    """Build the shared paginated collection envelope."""
    return {
        "data": items,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit if total and limit else 0,
        },
    }
