"""REST endpoints for Agent Execution Tracing (v0.2).

Routes are intentionally thin: they parse and validate request input, delegate
all querying/aggregation to the service layer, and shape responses via reusable
serializers. No business logic or SQLAlchemy session access lives here.

Response conventions (shared across the v0.2 API):

* Collections -> ``{"data": [...], "pagination": {page, limit, total, pages}}``
* Single resource -> the serialized object directly
* Errors -> ``{"error": message, "details": {...optional}}`` (see ``errors``)
"""
from flask import Blueprint, jsonify, request

from ..errors import error_response
from ..models.agent_trace import AgentStatus
from ..serializers.agent import serialize_run_detail, serialize_run_summary
from ..services import trace_service
from ..utils.pagination import PaginationError, paginated, parse_page_limit

agent_traces_bp = Blueprint("agent_traces", __name__)

_ALLOWED_STATUS = {
    AgentStatus.PENDING,
    AgentStatus.RUNNING,
    AgentStatus.SUCCESS,
    AgentStatus.FAILED,
}


@agent_traces_bp.get("/agent-runs")
def list_agent_runs():
    """List agent runs with pagination, filtering, search and sorting."""
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)

    status = request.args.get("status")
    if status is not None and status not in _ALLOWED_STATUS:
        return error_response(
            "invalid status", 400, {"allowed": sorted(_ALLOWED_STATUS)}
        )
    agent_type = request.args.get("agent_type")

    q = request.args.get("q")
    if q is not None:
        q = q.strip() or None

    sort = request.args.get("sort", "-created_at")
    if not trace_service.is_valid_agent_run_sort(sort):
        return error_response(
            "invalid sort field",
            400,
            {
                "allowed": sorted(trace_service.AGENT_RUN_SORTABLE),
                "hint": "prefix with '-' for descending, e.g. -created_at",
            },
        )

    items, total = trace_service.list_agent_runs(
        page=page, limit=limit, status=status, agent_type=agent_type, sort=sort, q=q
    )
    return jsonify(paginated([serialize_run_summary(r) for r in items], page, limit, total))


@agent_traces_bp.get("/agent-runs/<int:run_id>")
def get_agent_run(run_id: int):
    """Return a single agent run with steps, sub-records and a timeline."""
    run = trace_service.get_agent_run(run_id)
    if run is None:
        return error_response("agent run not found", 404)
    return jsonify(serialize_run_detail(run))


@agent_traces_bp.get("/requests/<int:request_id>/agent-runs")
def list_runs_for_request(request_id: int):
    """Return every agent run for a request (404 if the request is unknown)."""
    if trace_service.get_trace(request_id) is None:
        return error_response("request not found", 404)

    runs = trace_service.list_agent_runs_for_request(request_id)
    data = [serialize_run_summary(run) for run in runs]
    # Single-page envelope keeps the response shape consistent with /agent-runs.
    return jsonify(paginated(data, page=1, limit=max(len(data), 1), total=len(data)))


@agent_traces_bp.get("/dashboard/agent-metrics")
def agent_metrics():
    """Return aggregate agent-execution metrics for the dashboard."""
    return jsonify(trace_service.get_agent_metrics())
