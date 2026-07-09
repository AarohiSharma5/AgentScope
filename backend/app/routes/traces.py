"""REST API endpoints for traces and dashboard stats."""
from flask import Blueprint, jsonify, request

from ..errors import error_response
from ..services import trace_service

traces_bp = Blueprint("traces", __name__)


@traces_bp.post("/traces")
def create_trace():
    """Ingest a new LLM request trace."""
    data = request.get_json(silent=True) or {}
    if not data.get("model_name"):
        return error_response("model_name is required", 400)

    trace = trace_service.create_trace(data)
    return jsonify(trace.to_dict()), 201


#: Upper bound on the number of traces a single list request may return, so a
#: client cannot ask for an unbounded slice and exhaust server memory.
MAX_TRACES_LIMIT = 500


@traces_bp.get("/traces")
def list_traces():
    """List traces (most recent first) with simple, bounded pagination."""
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return error_response("limit and offset must be integers", 400)
    if not (1 <= limit <= MAX_TRACES_LIMIT):
        return error_response(f"limit must be between 1 and {MAX_TRACES_LIMIT}", 400)
    if offset < 0:
        return error_response("offset must be >= 0", 400)

    traces = trace_service.list_traces(limit=limit, offset=offset)
    return jsonify([t.to_dict() for t in traces])


@traces_bp.get("/traces/<int:trace_id>")
def get_trace(trace_id: int):
    """Fetch a single trace with all captured fields."""
    trace = trace_service.get_trace(trace_id)
    if trace is None:
        return error_response("trace not found", 404)
    return jsonify(trace.to_dict())


@traces_bp.get("/stats")
def get_stats():
    """Return aggregate dashboard metrics."""
    return jsonify(trace_service.get_stats())
