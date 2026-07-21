"""Serializer for budgets / SLOs / metric thresholds."""
from ..models.budget import Budget
from ..services import budget_service
from .common import iso as _iso


def serialize_budget(budget: Budget, with_status: bool = True) -> dict:
    """Serialize a budget, optionally enriched with its live status.

    When ``with_status`` is set, the current metric value is evaluated and the
    ``actual`` / ``ratio`` / ``status`` fields are merged in so the dashboard can
    render a progress bar and an OK / warn / breach badge in one payload.
    """
    data = {
        "id": budget.id,
        "name": budget.name,
        "metric": budget.metric,
        "comparison": budget.comparison,
        "threshold_value": budget.threshold_value,
        "window_days": budget.window_days,
        "model": budget.model,
        "created_at": _iso(budget.created_at),
    }
    if with_status:
        data.update(budget_service.evaluate_status(budget))
    return data
