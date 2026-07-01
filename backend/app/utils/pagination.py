"""Shared pagination helpers for list endpoints.

Keeps the ``{"data": [...], "pagination": {...}}`` envelope identical across every
collection endpoint so clients can rely on one shape.
"""
from typing import Any

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class PaginationError(ValueError):
    """Raised when page/limit query parameters are invalid."""


def parse_page_limit(args, default_limit: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT):
    """Parse and validate ``page``/``limit`` from request args.

    Returns ``(page, limit)`` or raises :class:`PaginationError` with a
    client-friendly message. Centralised so every list endpoint validates
    pagination identically.
    """
    try:
        page = int(args.get("page", 1))
        limit = int(args.get("limit", default_limit))
    except (TypeError, ValueError):
        raise PaginationError("page and limit must be integers")
    if page < 1:
        raise PaginationError("page must be >= 1")
    if not (1 <= limit <= max_limit):
        raise PaginationError(f"limit must be between 1 and {max_limit}")
    return page, limit


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
