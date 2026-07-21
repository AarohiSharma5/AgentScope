"""REST endpoints for timeline annotations (deploy / change markers).

Thin routes over :mod:`app.services.annotation_service`: validate input, delegate
persistence, and shape responses via :func:`serialize_annotation`. Annotations
let the analytics dashboard tie quality/cost/latency movements to the change
that caused them ("v2 prompt shipped", "switched to gpt-4o").
"""
from datetime import datetime

from flask import Blueprint, jsonify, request

from ..errors import error_response
from ..serializers.annotation import serialize_annotation
from ..services import annotation_service

annotations_bp = Blueprint("annotations", __name__)


def _parse_when(value):
    """Parse an ISO date or datetime string into a ``datetime`` (or None)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        # Accept a trailing 'Z' (UTC) and bare dates ("2026-07-20") alike.
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


@annotations_bp.get("/annotations")
def list_annotations():
    """List the caller's annotations, optionally bounded to the last ``?days=N``."""
    raw_days = request.args.get("days")
    days = None
    if raw_days not in (None, ""):
        try:
            days = int(raw_days)
        except (TypeError, ValueError):
            return error_response("days must be an integer", 400)
    items = annotation_service.list_annotations(days=days)
    return jsonify({"data": [serialize_annotation(a) for a in items]})


@annotations_bp.post("/annotations")
def create_annotation():
    """Create an annotation. Body: ``{label, annotated_at, description?}``."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error_response("request body must be a JSON object", 400)

    label = body.get("label")
    if not isinstance(label, str) or not label.strip():
        return error_response("label is required", 400)
    if len(label) > 255:
        return error_response("label must be at most 255 characters", 400)

    when = _parse_when(body.get("annotated_at"))
    if when is None:
        return error_response(
            "annotated_at is required (ISO date or datetime, e.g. 2026-07-20)", 400
        )

    description = body.get("description")
    if description is not None and not isinstance(description, str):
        return error_response("description must be a string", 400)

    annotation = annotation_service.create_annotation(
        label=label.strip(),
        annotated_at=when,
        description=(description.strip() if isinstance(description, str) else None) or None,
    )
    return jsonify(serialize_annotation(annotation)), 201


@annotations_bp.delete("/annotations/<int:annotation_id>")
def delete_annotation(annotation_id: int):
    """Delete an annotation by id (tenant-scoped)."""
    if not annotation_service.delete_annotation(annotation_id):
        return error_response("annotation not found", 404)
    return "", 204
