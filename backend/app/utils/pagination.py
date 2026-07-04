"""Shared pagination helpers for list endpoints.

Keeps the ``{"data": [...], "pagination": {...}}`` envelope identical across every
collection endpoint so clients can rely on one shape.

At scale (millions of rows) two patterns matter and are supported here:

* **Bounded counts.** ``COUNT(*)`` on a huge table is O(rows). :func:`count_query`
  can cap the count at a configured limit so a list endpoint never pays for a
  full scan just to render "1,000,000+" in a footer.
* **Keyset pagination.** Deep ``OFFSET`` scans re-read and discard every skipped
  row. :func:`keyset_page` fetches the next page by filtering on the last seen
  id, which stays constant-time no matter how deep the client pages.
"""
from typing import Any, Optional

from sqlalchemy import func

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


def count_query(query, max_count: int = 0) -> int:
    """Count rows matching ``query``, optionally capped for large tables.

    When ``max_count`` is > 0 the count is computed over a subquery limited to
    ``max_count + 1`` rows, so the database stops scanning early. The returned
    value is therefore an exact count up to ``max_count`` and ``max_count`` when
    there are more (callers can treat "== max_count" as "at least this many").
    A ``max_count`` of 0 performs a normal exact count.
    """
    if max_count and max_count > 0:
        limited = query.limit(max_count + 1).subquery()
        capped = query.session.query(func.count()).select_from(limited).scalar() or 0
        return min(capped, max_count)
    return query.count()


def keyset_page(
    query,
    id_column,
    limit: int,
    after_id: Optional[int] = None,
    descending: bool = True,
) -> list[Any]:
    """Return one keyset (a.k.a. seek) page ordered by ``id_column``.

    ``after_id`` is the last id the client already saw; the next page is fetched
    with a ``WHERE id < :after_id`` (descending) filter instead of ``OFFSET``,
    keeping deep pagination constant-time on an indexed id column.
    """
    if after_id is not None:
        query = query.filter(id_column < after_id if descending else id_column > after_id)
    order = id_column.desc() if descending else id_column.asc()
    return query.order_by(order).limit(limit).all()
