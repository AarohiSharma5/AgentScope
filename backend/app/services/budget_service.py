"""Persistence and evaluation for budgets / SLOs / metric thresholds.

CRUD over :class:`~app.models.budget.Budget` (tenant-scoped exactly like the
other resources) plus the live evaluation that turns a stored threshold into an
OK / warn / breach status by pulling the current metric value from
:mod:`app.services.evaluation_service`.
"""
from typing import Optional

from ..extensions import db
from ..models.budget import Budget
from . import evaluation_service

# Metrics a budget can watch, with their natural guardrail direction:
#   lte -> actual must stay AT/BELOW the threshold (cost cap, latency/failure ceiling)
#   gte -> actual must stay AT/ABOVE the threshold (quality floor)
BUDGET_METRICS: dict[str, str] = {
    "cost": "lte",
    "avg_score": "gte",
    "failure_rate": "lte",
    "avg_latency": "lte",
}

# Fraction of the way to a breach at which an lte budget flips to "warn" (80% of
# a cost cap). For gte floors, "warn" means within 5% above the floor.
_WARN_FRACTION = 0.8
_WARN_MARGIN = 1.05


def _tenant_scope() -> Optional[int]:
    from ..auth.context import tenant_scope

    return tenant_scope()


def _current_org() -> Optional[int]:
    from ..auth.context import current_organization_id

    return current_organization_id()


def _scoped(query):
    """Restrict ``query`` to the caller's tenant (no-op when unscoped)."""
    org_id = _tenant_scope()
    if org_id is not None:
        query = query.filter(Budget.organization_id == org_id)
    return query


def default_comparison(metric: str) -> Optional[str]:
    """Natural guardrail direction for ``metric`` (or None if unknown)."""
    return BUDGET_METRICS.get(metric)


def list_budgets() -> list[Budget]:
    """Return the caller's budgets, newest first."""
    return _scoped(Budget.query).order_by(Budget.created_at.desc()).all()


def create_budget(
    name: str,
    metric: str,
    threshold_value: float,
    comparison: str,
    window_days: int = 30,
    model: Optional[str] = None,
) -> Budget:
    """Persist a new budget stamped with the caller's organization."""
    budget = Budget(
        name=name,
        metric=metric,
        comparison=comparison,
        threshold_value=threshold_value,
        window_days=window_days,
        model=model,
        organization_id=_current_org(),
    )
    db.session.add(budget)
    db.session.commit()
    return budget


def get_budget(budget_id: int) -> Optional[Budget]:
    """Return a budget by id, or None if missing / not the caller's tenant."""
    budget = db.session.get(Budget, budget_id)
    if budget is None:
        return None
    org_id = _tenant_scope()
    if org_id is not None and budget.organization_id != org_id:
        return None
    return budget


def delete_budget(budget_id: int) -> bool:
    """Delete a budget (tenant-scoped). Returns True if one was removed."""
    budget = get_budget(budget_id)
    if budget is None:
        return False
    db.session.delete(budget)
    db.session.commit()
    return True


def evaluate_status(budget: Budget) -> dict:
    """Compute the live status of ``budget`` against its current metric value.

    Returns ``actual`` (current value, or None when there's no data),
    ``ratio`` (actual / threshold, for a progress bar) and ``status`` — one of
    ``ok`` / ``warn`` / ``breach`` / ``unknown``.
    """
    actual = evaluation_service.metric_value(
        budget.metric, days=budget.window_days, model=budget.model
    )
    threshold = budget.threshold_value
    if actual is None:
        return {"actual": None, "ratio": None, "status": "unknown"}

    ratio = round(actual / threshold, 4) if threshold else None
    if budget.comparison == "gte":
        if actual < threshold:
            status = "breach"
        elif ratio is not None and ratio <= _WARN_MARGIN:
            status = "warn"
        else:
            status = "ok"
    else:  # lte
        if actual > threshold:
            status = "breach"
        elif ratio is not None and ratio >= _WARN_FRACTION:
            status = "warn"
        else:
            status = "ok"
    return {"actual": actual, "ratio": ratio, "status": status}
