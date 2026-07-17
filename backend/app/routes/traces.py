"""REST API endpoints for traces and dashboard stats."""
from datetime import datetime

from flask import Blueprint, jsonify, request

from ..auth import rate_limited
from ..errors import error_response, get_json_body
from ..models.trace import TraceStatus
from ..services import trace_service
from ..utils.pagination import PaginationError, paginated, parse_page_limit

traces_bp = Blueprint("traces", __name__)

_TRACE_STATUSES = {TraceStatus.SUCCESS, TraceStatus.FAILED}
_TRACE_SORTS = {"timestamp", "-timestamp"}


def _clean(value):
    """Trim a query-string value to None when blank."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_dt(value):
    """Parse an ISO date/datetime query param, returning (datetime|None, error|None)."""
    value = _clean(value)
    if value is None:
        return None, None
    try:
        return datetime.fromisoformat(value), None
    except ValueError:
        return None, f"invalid datetime '{value}' (use ISO format, e.g. 2026-07-10)"


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
    """List traces using the shared paginated envelope, with optional filters.

    Standardized on ``page``/``limit`` + ``{data, pagination}`` so clients can
    share one pagination/parse helper across every collection endpoint. ``limit``
    is validated and bounded by :func:`parse_page_limit`, so a client can never
    request an unbounded slice.

    Optional query params segment a high-volume list. The primary axis is the
    application/area: ``project`` (the first-class tag) or ``system_prompt``
    (exact, for untagged traffic). Secondary refinements: ``model`` (exact),
    ``status`` (``success``/``failed``), ``since``/``until`` (ISO datetime window),
    ``q`` (substring search over prompts/response) and ``sort``
    (``-timestamp`` newest-first, default, or ``timestamp``).
    """
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)

    status = _clean(request.args.get("status"))
    if status is not None and status not in _TRACE_STATUSES:
        return error_response("invalid status", 400, {"allowed": sorted(_TRACE_STATUSES)})

    sort = request.args.get("sort", "-timestamp")
    if sort not in _TRACE_SORTS:
        return error_response("invalid sort", 400, {"allowed": sorted(_TRACE_SORTS)})

    since, err = _parse_dt(request.args.get("since"))
    if err:
        return error_response(err, 400)
    until, err = _parse_dt(request.args.get("until"))
    if err:
        return error_response(err, 400)

    traces, total = trace_service.list_traces_page(
        page=page,
        limit=limit,
        project=_clean(request.args.get("project")),
        system_prompt=_clean(request.args.get("system_prompt")),
        model=_clean(request.args.get("model")),
        status=status,
        q=_clean(request.args.get("q")),
        since=since,
        until=until,
        sort=sort,
    )
    return jsonify(paginated([t.to_dict() for t in traces], page, limit, total))


@traces_bp.get("/traces/facets")
def trace_facets():
    """Filter options for the Requests UI.

    ``areas`` is the primary axis (applications/system-prompt areas); ``models``
    and ``statuses`` are secondary refinements.
    """
    return jsonify(
        {
            "areas": trace_service.list_trace_areas(),
            "models": trace_service.distinct_trace_models(),
            "statuses": sorted(_TRACE_STATUSES),
        }
    )


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
