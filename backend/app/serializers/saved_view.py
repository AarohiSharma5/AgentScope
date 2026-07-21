"""Serializer for saved analytics views (custom dashboards)."""
from ..models.saved_view import SavedView
from .common import iso as _iso


def serialize_saved_view(view: SavedView) -> dict:
    """Serialize a saved view, emitting its config blob as-is."""
    return {
        "id": view.id,
        "name": view.name,
        "config": view.config or {},
        "created_at": _iso(view.created_at),
    }
