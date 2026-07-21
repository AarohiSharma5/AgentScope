"""Serializer for timeline annotations (deploy / change markers)."""
from ..models.annotation import Annotation
from .common import iso as _iso


def serialize_annotation(annotation: Annotation) -> dict:
    """Serialize an annotation.

    Exposes both the full ``annotated_at`` timestamp and a ``date`` (YYYY-MM-DD)
    convenience field so the dashboard can align markers to the daily buckets of
    the analytics time series without re-parsing.
    """
    return {
        "id": annotation.id,
        "label": annotation.label,
        "description": annotation.description,
        "annotated_at": _iso(annotation.annotated_at),
        "date": annotation.annotated_at.date().isoformat() if annotation.annotated_at else None,
        "created_at": _iso(annotation.created_at),
    }
