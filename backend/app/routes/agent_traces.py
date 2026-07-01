"""REST endpoints for Agent Execution Tracing (v0.2).

Routes are intentionally thin: they parse and validate request input, delegate
all querying/aggregation to the service layer, and shape responses via reusable
serializers. No business logic or SQLAlchemy session access lives here.
"""
from flask import Blueprint, jsonify, request

from ..models.agent_trace import AgentStatus
from ..serializers.agent import serialize_run_detail, serialize_run_summary
from ..services import trace_service

agent_traces_bp = Blueprint("agent_traces", __name__)

_ALLOWED_STATUS = {
    AgentStatus.PENDING,
    AgentStatus.RUNNING,
    AgentStatus.SUCCESS,
    AgentStatus.FAILED,
}

_MAX_LIMIT = 100


@agent_traces_bp.get("/agent-runs")
def list_agent_runs():
    """List agent runs with pagination, filtering and sorting."""
    # Pagination
    try:
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 20))
    except ValueError:
        return jsonify({"error": "page and limit must be integers"}), 400
    if page < 1:
        return jsonify({"error": "page must be >= 1"}), 400
    if not (1 <= limit <= _MAX_LIMIT):
        return jsonify({"error": f"limit must be between 1 and {_MAX_LIMIT}"}), 400

    # Filtering
    status = request.args.get("status")
    if status is not None and status not in _ALLOWED_STATUS:
        return (
            jsonify({"error": f"invalid status; allowed: {sorted(_ALLOWED_STATUS)}"}),
            400,
        )
    agent_type = request.args.get("agent_type")

    # Free-text search
    q = request.args.get("q")
    if q is not None:
        q = q.strip() or None

    # Sorting
    sort = request.args.get("sort", "-created_at")
    if not trace_service.is_valid_agent_run_sort(sort):
        return (
            jsonify(
                {
                    "error": "invalid sort field",
                    "allowed": sorted(trace_service.AGENT_RUN_SORTABLE),
                    "hint": "prefix with '-' for descending, e.g. -created_at",
                }
            ),
            400,
        )

    items, total = trace_service.list_agent_runs(
        page=page, limit=limit, status=status, agent_type=agent_type, sort=sort, q=q
    )

    return jsonify(
        {
            "data": [serialize_run_summary(run) for run in items],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit if total else 0,
            },
        }
    )


@agent_traces_bp.get("/agent-runs/<int:run_id>")
def get_agent_run(run_id: int):
    """Return a single agent run with steps, sub-records and a timeline."""
    run = trace_service.get_agent_run(run_id)
    if run is None:
        return jsonify({"error": "agent run not found"}), 404
    return jsonify(serialize_run_detail(run))


@agent_traces_bp.get("/requests/<int:request_id>/agent-runs")
def list_runs_for_request(request_id: int):
    """Return every agent run for a given request (404 if the request is unknown)."""
    if trace_service.get_trace(request_id) is None:
        return jsonify({"error": "request not found"}), 404

    runs = trace_service.list_agent_runs_for_request(request_id)
    return jsonify(
        {
            "data": [serialize_run_summary(run) for run in runs],
            "total": len(runs),
        }
    )


@agent_traces_bp.get("/dashboard/agent-metrics")
def agent_metrics():
    """Return aggregate agent-execution metrics for the dashboard."""
    return jsonify(trace_service.get_agent_metrics())
