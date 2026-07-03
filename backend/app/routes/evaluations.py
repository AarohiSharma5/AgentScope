"""REST endpoints for replay, evaluation and model comparison (v0.5).

Routes stay thin: parse and validate request input, delegate all
execution/querying to the engines and service layer, and shape responses via
reusable serializers. No business logic or SQLAlchemy session access lives here.

Response conventions (shared across the API):

* Collections -> ``{"data": [...], "pagination": {page, limit, total, pages}}``
* Single resource -> the serialized object directly
* Created resource -> the serialized object with HTTP 201
* Errors -> ``{"error": message, "details": {...optional}}`` (see ``errors``)

REST replays/comparisons run in *mock* mode: live agent/tool handlers are Python
callables that cannot be expressed in JSON, so they are only available through
the SDK. Likewise evaluations use the built-in rule-based evaluators (an
LLM-as-a-Judge needs a callable judge supplied in-process).
"""
from flask import Blueprint, jsonify, request

from ..comparison import ComparisonError, ModelComparisonEngine
from ..errors import error_response
from ..evaluation import EvaluationEngine, EvaluationError
from ..models.agent_trace import AgentStatus
from ..orchestration import ReplayEngine, ReplayError
from ..serializers.evaluation import (
    serialize_evaluation_run,
    serialize_model_comparison,
    serialize_replay_run,
)
from ..services import evaluation_service, replay_service
from ..utils.pagination import PaginationError, paginated, parse_page_limit

evaluations_bp = Blueprint("evaluations", __name__)

_STATUSES = {
    AgentStatus.PENDING,
    AgentStatus.RUNNING,
    AgentStatus.SUCCESS,
    AgentStatus.FAILED,
    AgentStatus.CANCELLED,
    AgentStatus.TIMEOUT,
}


# -- Request-body helpers ---------------------------------------------------


def _json_body():
    """Return the request JSON object, or an ``(error_response)`` tuple."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        return None
    return body


def _clean(value):
    """Trim a query-string value to a non-empty string or None."""
    if value is None:
        return None
    return value.strip() or None


def _opt_number(body: dict, key: str):
    """Validate an optional numeric body field. Returns (value, error)."""
    value = body.get(key)
    if value is None:
        return None, None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, f"{key} must be a number"
    return value, None


def _int_arg(name: str):
    """Parse an optional integer query arg (raises ValueError if malformed)."""
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        return None
    return int(raw)


# -- Replays ----------------------------------------------------------------


@evaluations_bp.get("/replays")
def list_replays():
    """List replay runs with pagination, filtering, search and sorting."""
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)

    status = request.args.get("status")
    if status is not None and status not in _STATUSES:
        return error_response("invalid status", 400, {"allowed": sorted(_STATUSES)})

    try:
        original = _int_arg("original_conversation_run_id") or _int_arg("conversation_run_id")
    except (TypeError, ValueError):
        return error_response("original_conversation_run_id must be an integer", 400)

    sort = request.args.get("sort", "-created_at")
    if not replay_service.is_valid_replay_sort(sort):
        return error_response(
            "invalid sort field",
            400,
            {
                "allowed": sorted(replay_service.REPLAY_SORTABLE),
                "hint": "prefix with '-' for descending, e.g. -created_at",
            },
        )

    items, total = replay_service.list_replay_runs(
        page=page, limit=limit, original_conversation_run_id=original,
        status=status, q=_clean(request.args.get("q")), sort=sort,
    )
    return jsonify(paginated([serialize_replay_run(r) for r in items], page, limit, total))


@evaluations_bp.post("/replays")
def create_replay():
    """Create (run) a replay of a traced conversation under new parameters."""
    body = _json_body()
    if body is None:
        return error_response("request body must be a JSON object", 400)

    conversation_run_id = body.get("conversation_run_id") or body.get(
        "original_conversation_run_id"
    )
    if not isinstance(conversation_run_id, int) or isinstance(conversation_run_id, bool):
        return error_response("conversation_run_id (integer) is required", 400)

    for key in ("temperature", "top_p"):
        _, err = _opt_number(body, key)
        if err:
            return error_response(err, 400)
    tools = body.get("tools")
    if tools is not None and not isinstance(tools, dict):
        return error_response("tools must be a JSON object", 400)

    try:
        result = ReplayEngine().replay(
            conversation_run_id,
            model=body.get("model"),
            temperature=body.get("temperature"),
            top_p=body.get("top_p"),
            system_prompt=body.get("system_prompt"),
            memory=body.get("memory"),
            tools=tools,
            conversation_name=body.get("conversation_name"),
        )
    except ReplayError as exc:
        return error_response(str(exc), 404)

    data = serialize_replay_run(result.replay_run)
    data["replay_conversation_run_id"] = result.replay_conversation_run_id
    data["totals"] = result.totals
    return jsonify(data), 201


@evaluations_bp.get("/replays/<int:replay_id>")
def get_replay(replay_id: int):
    """Return a single replay run."""
    replay = replay_service.get_replay_run(replay_id)
    if replay is None:
        return error_response("replay run not found", 404)
    return jsonify(serialize_replay_run(replay))


# -- Evaluations ------------------------------------------------------------


@evaluations_bp.get("/evaluations")
def list_evaluations():
    """List evaluation runs with pagination, filtering, search and sorting."""
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)

    status = request.args.get("status")
    if status is not None and status not in _STATUSES:
        return error_response("invalid status", 400, {"allowed": sorted(_STATUSES)})

    try:
        conversation = _int_arg("conversation_run_id")
    except (TypeError, ValueError):
        return error_response("conversation_run_id must be an integer", 400)

    sort = request.args.get("sort", "-created_at")
    if not evaluation_service.is_valid_evaluation_sort(sort):
        return error_response(
            "invalid sort field",
            400,
            {
                "allowed": sorted(evaluation_service.EVALUATION_SORTABLE),
                "hint": "prefix with '-' for descending, e.g. -created_at",
            },
        )

    items, total = evaluation_service.list_evaluation_runs(
        page=page, limit=limit, conversation_run_id=conversation,
        evaluation_type=_clean(request.args.get("evaluation_type")),
        status=status, q=_clean(request.args.get("q")), sort=sort,
    )
    return jsonify(paginated([serialize_evaluation_run(r) for r in items], page, limit, total))


@evaluations_bp.post("/evaluations")
def create_evaluation():
    """Run an evaluation over a conversation, persisting the run and metrics."""
    body = _json_body()
    if body is None:
        return error_response("request body must be a JSON object", 400)

    conversation_run_id = body.get("conversation_run_id")
    if not isinstance(conversation_run_id, int) or isinstance(conversation_run_id, bool):
        return error_response("conversation_run_id (integer) is required", 400)

    expected_facts = body.get("expected_facts")
    if expected_facts is not None and not isinstance(expected_facts, list):
        return error_response("expected_facts must be an array of strings", 400)
    weights = body.get("weights")
    if weights is not None and not isinstance(weights, dict):
        return error_response("weights must be a JSON object", 400)
    for key in ("latency_budget_ms", "cost_budget"):
        _, err = _opt_number(body, key)
        if err:
            return error_response(err, 400)

    try:
        result = EvaluationEngine().evaluate(
            conversation_run_id,
            reference=body.get("reference"),
            expected_facts=expected_facts,
            latency_budget_ms=body.get("latency_budget_ms"),
            cost_budget=body.get("cost_budget"),
            evaluation_type=body.get("evaluation_type"),
            model_name=body.get("model_name"),
            weights=weights,
            metadata=body.get("metadata"),
        )
    except EvaluationError as exc:
        return error_response(str(exc), 404)

    run = evaluation_service.get_evaluation_run(result.evaluation_run_id)
    return jsonify(serialize_evaluation_run(run)), 201


@evaluations_bp.get("/evaluations/<int:evaluation_id>")
def get_evaluation(evaluation_id: int):
    """Return a single evaluation run with its metrics."""
    run = evaluation_service.get_evaluation_run(evaluation_id)
    if run is None:
        return error_response("evaluation run not found", 404)
    return jsonify(serialize_evaluation_run(run))


# -- Comparisons ------------------------------------------------------------


@evaluations_bp.get("/comparisons")
def list_comparisons():
    """List model comparisons with pagination, filtering, search and sorting."""
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)

    try:
        conversation = _int_arg("conversation_run_id")
    except (TypeError, ValueError):
        return error_response("conversation_run_id must be an integer", 400)

    sort = request.args.get("sort", "-created_at")
    if not replay_service.is_valid_comparison_sort(sort):
        return error_response(
            "invalid sort field",
            400,
            {
                "allowed": sorted(replay_service.COMPARISON_SORTABLE),
                "hint": "prefix with '-' for descending, e.g. -created_at",
            },
        )

    items, total = replay_service.list_comparisons(
        page=page, limit=limit, conversation_run_id=conversation,
        q=_clean(request.args.get("q")), sort=sort,
    )
    return jsonify(
        paginated([serialize_model_comparison(c) for c in items], page, limit, total)
    )


@evaluations_bp.post("/comparisons")
def create_comparison():
    """Run one conversation against multiple models and compare them."""
    body = _json_body()
    if body is None:
        return error_response("request body must be a JSON object", 400)

    conversation_run_id = body.get("conversation_run_id")
    if not isinstance(conversation_run_id, int) or isinstance(conversation_run_id, bool):
        return error_response("conversation_run_id (integer) is required", 400)

    models = body.get("models")
    if (
        not isinstance(models, list)
        or not models
        or not all(isinstance(m, str) for m in models)
    ):
        return error_response("models must be a non-empty array of strings", 400)

    expected_facts = body.get("expected_facts")
    if expected_facts is not None and not isinstance(expected_facts, list):
        return error_response("expected_facts must be an array of strings", 400)
    model_configs = body.get("model_configs")
    if model_configs is not None and not isinstance(model_configs, dict):
        return error_response("model_configs must be a JSON object", 400)

    try:
        result = ModelComparisonEngine().compare(
            conversation_run_id,
            models,
            baseline_model=body.get("baseline_model"),
            evaluate=bool(body.get("evaluate", False)),
            reference=body.get("reference"),
            expected_facts=expected_facts,
            latency_budget_ms=body.get("latency_budget_ms"),
            cost_budget=body.get("cost_budget"),
            model_configs=model_configs,
        )
    except ComparisonError as exc:
        return error_response(str(exc), 400)
    except ReplayError as exc:
        return error_response(str(exc), 404)

    return (
        jsonify(
            {
                "original_conversation_run_id": result.original_conversation_run_id,
                "baseline_model": result.baseline_model,
                "winner": result.winner,
                "profiles": result.profiles,
                "summary": result.summary,
                "side_by_side": result.side_by_side,
                "comparison_ids": result.comparison_ids,
            }
        ),
        201,
    )


# -- Dashboard --------------------------------------------------------------


@evaluations_bp.get("/dashboard/evaluation-metrics")
def evaluation_metrics():
    """Return aggregate evaluation metrics for the dashboard."""
    return jsonify(evaluation_service.get_evaluation_metrics())
