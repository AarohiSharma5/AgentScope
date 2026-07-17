"""REST API endpoints for traces and dashboard stats."""
from flask import Blueprint, jsonify, request

from ..auth import rate_limited
from ..errors import error_response, get_json_body
from ..services import trace_service
from ..utils.pagination import PaginationError, paginated, parse_page_limit

traces_bp = Blueprint("traces", __name__)


@traces_bp.post("/traces")
@rate_limited(config_key="RATE_LIMIT_INGEST")
def create_trace():
    """Ingest a new LLM request trace."""
    data = get_json_body()
    if not data.get("model_name"):
        return error_response("model_name is required", 400)

    trace = trace_service.create_trace(data)
    return jsonify(trace.to_dict()), 201


@traces_bp.get("/traces")
def list_traces():
    """List traces (most recent first) using the shared paginated envelope.

    Standardized on ``page``/``limit`` + ``{data, pagination}`` so clients can
    share one pagination/parse helper across every collection endpoint. ``limit``
    is validated and bounded by :func:`parse_page_limit`, so a client can never
    request an unbounded slice.
    """
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)

    traces, total = trace_service.list_traces_page(page=page, limit=limit)
    return jsonify(paginated([t.to_dict() for t in traces], page, limit, total))


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
