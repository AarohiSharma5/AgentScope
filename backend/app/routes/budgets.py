"""REST endpoints for budgets / SLOs / metric thresholds.

Thin routes over :mod:`app.services.budget_service`: validate input, delegate
persistence, and shape responses via :func:`serialize_budget` (which enriches
each budget with its live OK / warn / breach status). Budgets turn the analytics
dashboard from a passive report into active governance — cost caps and quality
SLOs that flag themselves when breached.
"""
from flask import Blueprint, jsonify, request

from ..errors import error_response
from ..serializers.budget import serialize_budget
from ..services import budget_service

budgets_bp = Blueprint("budgets", __name__)

_MAX_WINDOW_DAYS = 365


@budgets_bp.get("/budgets")
def list_budgets():
    """List the caller's budgets, each enriched with its live status."""
    items = budget_service.list_budgets()
    return jsonify({"data": [serialize_budget(b) for b in items]})


@budgets_bp.post("/budgets")
def create_budget():
    """Create a budget. Body: ``{name, metric, threshold_value, window_days?,
    model?, comparison?}``. ``comparison`` defaults to the metric's natural
    direction (cost/latency/failure = ``lte``, score = ``gte``)."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error_response("request body must be a JSON object", 400)

    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        return error_response("name is required", 400)
    if len(name) > 255:
        return error_response("name must be at most 255 characters", 400)

    metric = body.get("metric")
    if metric not in budget_service.BUDGET_METRICS:
        allowed = ", ".join(sorted(budget_service.BUDGET_METRICS))
        return error_response(f"metric must be one of: {allowed}", 400)

    threshold = body.get("threshold_value")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        return error_response("threshold_value must be a number", 400)
    if threshold <= 0:
        return error_response("threshold_value must be greater than 0", 400)

    comparison = body.get("comparison") or budget_service.default_comparison(metric)
    if comparison not in ("lte", "gte"):
        return error_response("comparison must be 'lte' or 'gte'", 400)

    window_days = body.get("window_days", 30)
    if not isinstance(window_days, int) or isinstance(window_days, bool) or window_days < 0:
        return error_response("window_days must be a non-negative integer", 400)
    window_days = min(window_days, _MAX_WINDOW_DAYS)

    model = body.get("model")
    if model is not None and not isinstance(model, str):
        return error_response("model must be a string", 400)

    budget = budget_service.create_budget(
        name=name.strip(),
        metric=metric,
        threshold_value=float(threshold),
        comparison=comparison,
        window_days=window_days,
        model=(model.strip() if isinstance(model, str) else None) or None,
    )
    return jsonify(serialize_budget(budget)), 201


@budgets_bp.delete("/budgets/<int:budget_id>")
def delete_budget(budget_id: int):
    """Delete a budget by id (tenant-scoped)."""
    if not budget_service.delete_budget(budget_id):
        return error_response("budget not found", 404)
    return "", 204
