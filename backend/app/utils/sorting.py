"""Shared, portable sort helpers for list endpoints.

Sort strings use an optional ``-`` prefix for descending order (e.g.
``-created_at``). Kept in one place so every service validates and applies
sorting identically across SQLite and PostgreSQL.
"""
from typing import Iterable

from sqlalchemy import asc, desc


def is_valid_sort(sort: str, allowed: Iterable[str]) -> bool:
    """Return True if ``sort`` targets an allowed field (optional ``-`` prefix)."""
    if not sort:
        return False
    field = sort[1:] if sort.startswith("-") else sort
    return field in allowed


def apply_sort(query, sort: str, columns: dict):
    """Apply ordering to a query. Assumes ``sort`` was already validated.

    ``columns`` maps a sortable field name to its ORM column.
    """
    descending = sort.startswith("-")
    field = sort[1:] if descending else sort
    column = columns[field]
    return query.order_by(desc(column) if descending else asc(column))
