"""REST endpoints for saved analytics views (custom dashboards).

Thin routes over :mod:`app.services.saved_view_service`: validate input, delegate
persistence, and shape responses via :func:`serialize_saved_view`. A saved view
captures a named analytics configuration (range + model filter) so users can
re-apply a preferred slice of the dashboard in one click.
"""
from flask import Blueprint, jsonify, request

from ..errors import error_response
from ..serializers.saved_view import serialize_saved_view
from ..services import saved_view_service
from ..utils.validation import ValidationError

saved_views_bp = Blueprint("saved_views", __name__)


@saved_views_bp.get("/saved-views")
def list_saved_views():
    """List the caller's saved views, newest first."""
    items = saved_view_service.list_saved_views()
    return jsonify({"data": [serialize_saved_view(v) for v in items]})


@saved_views_bp.post("/saved-views")
def create_saved_view():
    """Create a saved view. Body: ``{name, config}`` where config is a JSON object."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error_response("request body must be a JSON object", 400)

    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        return error_response("name is required", 400)
    if len(name) > 255:
        return error_response("name must be at most 255 characters", 400)

    config = body.get("config", {})
    try:
        view = saved_view_service.create_saved_view(name=name.strip(), config=config)
    except ValidationError as exc:
        return error_response(str(exc), 400)
    return jsonify(serialize_saved_view(view)), 201


@saved_views_bp.delete("/saved-views/<int:view_id>")
def delete_saved_view(view_id: int):
    """Delete a saved view by id (tenant-scoped)."""
    if not saved_view_service.delete_saved_view(view_id):
        return error_response("saved view not found", 404)
    return "", 204
