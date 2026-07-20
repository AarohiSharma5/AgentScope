"""Business logic and persistence for evaluation runs (v0.5).

All SQLAlchemy session handling for :class:`~app.models.evaluation_trace.EvaluationRun`
and :class:`~app.models.evaluation_trace.EvaluationMetric` lives here so the
:class:`~app.evaluation.engine.EvaluationEngine` stays a thin coordinator. Also
reconstructs the :class:`~app.evaluation.context.EvaluationContext` that
evaluators score, reusing the replay snapshot so there is no duplicated
trace-reconstruction logic.
"""
import logging
from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import case, func, or_
from sqlalchemy.orm import selectinload

from ..evaluation.context import EvaluationContext, MetricResult
from ..evaluation.evaluators import Metrics
from ..extensions import db
from ..models.agent_trace import AgentStatus, AgentStep
from ..models.evaluation_trace import EvaluationMetric, EvaluationRun
from ..models.trace import Trace
from ..models.workflow_trace import AgentNode, ConversationRun
from ..services import replay_service
from ..streaming import EventType, emit
from ..utils.sorting import apply_sort, is_valid_sort
from ..utils.timeutils import utcnow
from ..utils.validation import ensure_json_object

logger = logging.getLogger("agentscope")


def _tenant_scope() -> Optional[int]:
    """Organization id reads should be restricted to, or None for no scoping."""
    from ..auth.context import tenant_scope

    return tenant_scope()


def _scoped(query, column):
    """Filter ``query`` to the caller's tenant on ``column`` (no-op when unscoped)."""
    org_id = _tenant_scope()
    if org_id is not None:
        query = query.filter(column == org_id)
    return query


def _org_of_conversation(conversation_run_id: Optional[int]) -> Optional[int]:
    """Organization of a conversation run, used to stamp its evaluations."""
    if conversation_run_id is None:
        return None
    conversation = db.session.get(ConversationRun, conversation_run_id)
    return conversation.organization_id if conversation is not None else None


def _day_expr(column):
    """Portable ``YYYY-MM-DD`` day bucket for the active database dialect.

    Day bucketing is done in SQL (via ``GROUP BY``) rather than by pulling every
    row into Python, so the only dialect-specific bit — the date-truncation
    function — is isolated here. SQLite uses ``strftime``; everything else
    (PostgreSQL) uses ``to_char``. Both yield the same string shape as
    ``datetime.date().isoformat()``.
    """
    if db.session.get_bind().dialect.name == "sqlite":
        return func.strftime("%Y-%m-%d", column)
    return func.to_char(column, "YYYY-MM-DD")


# -- EvaluationRun ----------------------------------------------------------


def create_evaluation_run(
    conversation_run_id: int,
    evaluation_type: Optional[str] = None,
    model_name: Optional[str] = None,
    status: str = AgentStatus.RUNNING,
    started_at: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> EvaluationRun:
    """Persist a new evaluation run (committed) and return it."""
    run = EvaluationRun(
        conversation_run_id=conversation_run_id,
        evaluation_type=evaluation_type,
        model_name=model_name,
        status=status,
        started_at=started_at or utcnow(),
        evaluation_metadata=ensure_json_object(metadata, "metadata"),
        organization_id=_org_of_conversation(conversation_run_id),
    )
    db.session.add(run)
    db.session.commit()
    logger.debug(
        "Started evaluation run id=%s conversation_run_id=%s type=%s",
        run.id, conversation_run_id, evaluation_type,
    )
    return run


def add_metric(
    evaluation_run_id: int,
    metric_name: str,
    metric_value: Optional[float] = None,
    weight: Optional[float] = None,
    notes: Optional[str] = None,
) -> EvaluationMetric:
    """Persist a single metric for an evaluation run (committed)."""
    metric = EvaluationMetric(
        evaluation_run_id=evaluation_run_id,
        metric_name=metric_name,
        metric_value=metric_value,
        weight=weight,
        notes=notes,
    )
    db.session.add(metric)
    db.session.commit()
    return metric


def add_metrics(
    evaluation_run_id: int, metrics: Iterable[MetricResult]
) -> list[EvaluationMetric]:
    """Persist several metric results in one transaction (committed)."""
    rows = [
        EvaluationMetric(
            evaluation_run_id=evaluation_run_id,
            metric_name=m.name,
            metric_value=m.value,
            weight=m.weight,
            notes=m.notes,
        )
        for m in metrics
    ]
    if rows:
        db.session.add_all(rows)
        db.session.commit()
        logger.debug("Recorded %s metrics for evaluation run id=%s", len(rows), evaluation_run_id)
    return rows


def finish_evaluation_run(
    run: EvaluationRun,
    overall_score: Optional[float] = None,
    status: str = AgentStatus.SUCCESS,
    finished_at: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> EvaluationRun:
    """Finish an evaluation run, recording the overall score and status (committed)."""
    run.status = status
    run.finished_at = finished_at or utcnow()
    if overall_score is not None:
        run.overall_score = overall_score
    if metadata:
        merged = dict(run.evaluation_metadata or {})
        merged.update(metadata)
        run.evaluation_metadata = ensure_json_object(merged, "metadata")
    db.session.commit()
    logger.debug("Finished evaluation run id=%s status=%s score=%s", run.id, status, overall_score)
    emit(
        EventType.EVALUATION_FINISHED,
        evaluation_run_id=run.id, conversation_run_id=run.conversation_run_id,
        evaluation_type=run.evaluation_type, overall_score=run.overall_score,
        status=run.status,
    )
    return run


def get_evaluation_run(evaluation_run_id: int) -> Optional[EvaluationRun]:
    """Return an evaluation run eager-loaded with its metrics, or None (tenant-scoped)."""
    run = (
        db.session.query(EvaluationRun)
        .options(selectinload(EvaluationRun.metrics))
        .filter(EvaluationRun.id == evaluation_run_id)
        .one_or_none()
    )
    if run is None:
        return None
    org_id = _tenant_scope()
    if org_id is not None and run.organization_id != org_id:
        return None
    return run


EVALUATION_SORTABLE = {"created_at", "started_at", "finished_at", "overall_score", "status"}
_EVALUATION_SORT_COLUMNS = {name: getattr(EvaluationRun, name) for name in EVALUATION_SORTABLE}


def is_valid_evaluation_sort(sort: str) -> bool:
    """Return True if ``sort`` targets an allowed evaluation field."""
    return is_valid_sort(sort, EVALUATION_SORTABLE)


def list_evaluation_runs(
    page: int = 1,
    limit: int = 20,
    conversation_run_id: Optional[int] = None,
    evaluation_type: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = "-created_at",
) -> tuple[list[EvaluationRun], int]:
    """Return a page of evaluation runs (with metrics) and the total count.

    ``q`` performs a case-insensitive search across the evaluation type and the
    (judge) model name.
    """
    query = _scoped(
        EvaluationRun.query.options(selectinload(EvaluationRun.metrics)),
        EvaluationRun.organization_id,
    )
    if conversation_run_id is not None:
        query = query.filter(EvaluationRun.conversation_run_id == conversation_run_id)
    if evaluation_type is not None:
        query = query.filter(EvaluationRun.evaluation_type == evaluation_type)
    if status is not None:
        query = query.filter(EvaluationRun.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                EvaluationRun.evaluation_type.ilike(like),
                EvaluationRun.model_name.ilike(like),
            )
        )
    total = query.count()
    query = apply_sort(query, sort, _EVALUATION_SORT_COLUMNS)
    items = query.limit(limit).offset((page - 1) * limit).all()
    return items, total


# -- Dashboard aggregation --------------------------------------------------


def get_evaluation_metrics() -> dict:
    """Aggregate evaluation metrics for the dashboard.

    Returns average overall score, average conversation cost/latency (over the
    evaluated conversations), the average of key per-metric scores (correctness,
    faithfulness, groundedness, tool accuracy, memory usage) and the evaluation
    success rate.
    """
    org_id = _tenant_scope()
    total = _scoped(
        db.session.query(func.count(EvaluationRun.id)), EvaluationRun.organization_id
    ).scalar() or 0
    success = (
        _scoped(
            db.session.query(func.count(EvaluationRun.id)),
            EvaluationRun.organization_id,
        )
        .filter(EvaluationRun.status == AgentStatus.SUCCESS)
        .scalar()
        or 0
    )
    avg_score = _scoped(
        db.session.query(func.avg(EvaluationRun.overall_score)),
        EvaluationRun.organization_id,
    ).scalar()

    metric_query = db.session.query(
        EvaluationMetric.metric_name, func.avg(EvaluationMetric.metric_value)
    )
    if org_id is not None:
        metric_query = metric_query.join(
            EvaluationRun, EvaluationMetric.evaluation_run_id == EvaluationRun.id
        ).filter(EvaluationRun.organization_id == org_id)
    metric_rows = metric_query.group_by(EvaluationMetric.metric_name).all()
    by_metric = {name: _round(value, 4) for name, value in metric_rows}

    # Cost and latency are aggregated over the *distinct evaluated
    # conversations* with a few set-based queries instead of looping
    # ``conversation_totals`` per conversation (which was N x ~3 queries and
    # grew linearly with history). ``conv_ids`` is reused as an ``IN`` subquery.
    conv_ids = _scoped(
        db.session.query(EvaluationRun.conversation_run_id),
        EvaluationRun.organization_id,
    ).distinct()
    num_conversations = conv_ids.count()

    # Mean per-conversation cost == total step cost / number of conversations
    # (conversations with no steps contribute 0, matching the old behavior).
    total_cost = (
        db.session.query(func.coalesce(func.sum(AgentStep.cost), 0.0))
        .select_from(AgentNode)
        .join(AgentStep, AgentStep.agent_run_id == AgentNode.agent_run_id)
        .filter(AgentNode.conversation_run_id.in_(conv_ids))
        .scalar()
    ) or 0.0
    average_cost = round(total_cost / num_conversations, 6) if num_conversations else None

    avg_latency = (
        db.session.query(func.avg(ConversationRun.latency_ms))
        .filter(
            ConversationRun.id.in_(conv_ids),
            ConversationRun.latency_ms.isnot(None),
        )
        .scalar()
    )
    average_latency = round(avg_latency, 4) if avg_latency is not None else None

    return {
        "total_evaluations": total,
        "average_evaluation_score": _round(avg_score, 4),
        "average_cost": average_cost,
        "average_latency": average_latency,
        "average_correctness": by_metric.get(Metrics.CORRECTNESS),
        "average_faithfulness": by_metric.get(Metrics.FAITHFULNESS),
        "average_groundedness": by_metric.get(Metrics.GROUNDEDNESS),
        "average_tool_accuracy": by_metric.get(Metrics.TOOL_SUCCESS),
        "average_memory_usage": by_metric.get(Metrics.MEMORY_USAGE),
        "success_rate": round(success / total, 4) if total else 0.0,
    }


def get_evaluation_analytics(days: Optional[int] = None) -> dict:
    """Build daily time-series analytics plus headline rates for the dashboard.

    Each evaluation run is bucketed by its creation date; per-day cost, tokens
    and latency come from the evaluated conversations, alongside the average
    evaluation score and the failure rate. The headline block reuses
    :func:`get_evaluation_metrics`.

    Aggregation is done with a fixed handful of set-based queries (``GROUP BY``
    in SQL, plus one join to sum cost/tokens), independent of how many
    evaluation runs exist — instead of loading every run and issuing ~3 queries
    per run. ``days`` optionally bounds the series to the last N days (``None``
    = all history); the dashboard route passes a sensible default so a growing
    history can never turn one dashboard load into an unbounded scan.
    """
    since = utcnow() - timedelta(days=days) if days and days > 0 else None
    day = _day_expr(EvaluationRun.created_at)

    # 1) Run-level per-day aggregates: count, failures and mean score. One query.
    run_q = _scoped(
        db.session.query(
            day.label("day"),
            func.count(EvaluationRun.id),
            func.sum(case((EvaluationRun.status == AgentStatus.FAILED, 1), else_=0)),
            func.avg(EvaluationRun.overall_score),
        ),
        EvaluationRun.organization_id,
    )
    if since is not None:
        run_q = run_q.filter(EvaluationRun.created_at >= since)
    run_rows = run_q.group_by(day).all()

    # 2) Per-day mean conversation latency. One query (AVG ignores NULLs).
    lat_q = _scoped(
        db.session.query(day.label("day"), func.avg(ConversationRun.latency_ms))
        .select_from(EvaluationRun)
        .join(ConversationRun, EvaluationRun.conversation_run_id == ConversationRun.id),
        EvaluationRun.organization_id,
    )
    if since is not None:
        lat_q = lat_q.filter(EvaluationRun.created_at >= since)
    latency_by_day = dict(lat_q.group_by(day).all())

    # 3) Cost + tokens per day. Tokens live in a JSON column (not portably
    #    SUM-able in SQL), so we pull the (day, cost, token_usage) rows for the
    #    evaluated conversations' steps in ONE date-bounded query and fold them
    #    in Python — no per-conversation fan-out.
    ct_q = _scoped(
        db.session.query(day.label("day"), AgentStep.cost, AgentStep.token_usage)
        .select_from(EvaluationRun)
        .join(AgentNode, AgentNode.conversation_run_id == EvaluationRun.conversation_run_id)
        .join(AgentStep, AgentStep.agent_run_id == AgentNode.agent_run_id),
        EvaluationRun.organization_id,
    )
    if since is not None:
        ct_q = ct_q.filter(EvaluationRun.created_at >= since)

    cost_by_day: dict[str, float] = {}
    tokens_by_day: dict[str, int] = {}
    for bucket_day, cost, usage in ct_q.all():
        cost_by_day[bucket_day] = cost_by_day.get(bucket_day, 0.0) + (cost or 0.0)
        usage = usage or {}
        tokens = usage.get("total") or ((usage.get("input") or 0) + (usage.get("output") or 0))
        tokens_by_day[bucket_day] = tokens_by_day.get(bucket_day, 0) + tokens

    daily = []
    for bucket_day, evaluations, failures, avg_eval_score in sorted(
        run_rows, key=lambda r: r[0] or ""
    ):
        failures = failures or 0
        latency = latency_by_day.get(bucket_day)
        daily.append(
            {
                "date": bucket_day,
                "cost": round(cost_by_day.get(bucket_day, 0.0), 6),
                "tokens": tokens_by_day.get(bucket_day, 0),
                "latency_ms": round(latency, 2) if latency is not None else None,
                "evaluation_score": round(avg_eval_score, 4) if avg_eval_score is not None else None,
                "evaluations": evaluations,
                "failures": failures,
                "failure_rate": round(failures / evaluations, 4) if evaluations else 0.0,
            }
        )

    headline = get_evaluation_metrics()
    headline["failure_rate"] = round(1 - headline["success_rate"], 4)
    return {"daily": daily, "totals": headline, "by_model": _analytics_by_model(since)}


def _analytics_by_model(since: Optional[datetime]) -> list[dict]:
    """Per generating-model breakdown of evaluation cost, quality and reliability.

    Groups by the model that *produced* the conversation (``Trace.model_name``,
    reached via the conversation's originating request) rather than the judge
    model stored on the evaluation run. Uses the same set-based approach as the
    daily series: one grouped query for run stats + latency, and one row-fold for
    cost/tokens (a JSON column that isn't portably SUM-able in SQL).
    """
    # 1) Per-model run stats: evaluations, failures, mean score and mean latency.
    stats_q = _scoped(
        db.session.query(
            Trace.model_name.label("model"),
            func.count(EvaluationRun.id),
            func.sum(case((EvaluationRun.status == AgentStatus.FAILED, 1), else_=0)),
            func.avg(EvaluationRun.overall_score),
            func.avg(ConversationRun.latency_ms),
        )
        .select_from(EvaluationRun)
        .join(ConversationRun, EvaluationRun.conversation_run_id == ConversationRun.id)
        .join(Trace, ConversationRun.request_trace_id == Trace.id),
        EvaluationRun.organization_id,
    )
    if since is not None:
        stats_q = stats_q.filter(EvaluationRun.created_at >= since)
    stats_rows = stats_q.group_by(Trace.model_name).all()

    # 2) Cost + tokens per model, folded in Python (see daily series rationale).
    ct_q = _scoped(
        db.session.query(Trace.model_name, AgentStep.cost, AgentStep.token_usage)
        .select_from(EvaluationRun)
        .join(ConversationRun, EvaluationRun.conversation_run_id == ConversationRun.id)
        .join(Trace, ConversationRun.request_trace_id == Trace.id)
        .join(AgentNode, AgentNode.conversation_run_id == EvaluationRun.conversation_run_id)
        .join(AgentStep, AgentStep.agent_run_id == AgentNode.agent_run_id),
        EvaluationRun.organization_id,
    )
    if since is not None:
        ct_q = ct_q.filter(EvaluationRun.created_at >= since)

    cost_by_model: dict[str, float] = {}
    tokens_by_model: dict[str, int] = {}
    for model, cost, usage in ct_q.all():
        cost_by_model[model] = cost_by_model.get(model, 0.0) + (cost or 0.0)
        usage = usage or {}
        tokens = usage.get("total") or ((usage.get("input") or 0) + (usage.get("output") or 0))
        tokens_by_model[model] = tokens_by_model.get(model, 0) + tokens

    out = []
    for model, evaluations, failures, avg_score, avg_latency in stats_rows:
        failures = failures or 0
        total_cost = cost_by_model.get(model, 0.0)
        out.append(
            {
                "model": model,
                "evaluations": evaluations,
                "failures": failures,
                "failure_rate": round(failures / evaluations, 4) if evaluations else 0.0,
                "average_evaluation_score": _round(avg_score, 4),
                "average_cost": round(total_cost / evaluations, 6) if evaluations else None,
                "average_latency": round(avg_latency, 2) if avg_latency is not None else None,
                "tokens": tokens_by_model.get(model, 0),
            }
        )
    # Busiest models first so the UI leads with the most-evaluated.
    out.sort(key=lambda r: r["evaluations"], reverse=True)
    return out


def _round(value: Optional[float], places: int) -> Optional[float]:
    """Round an optional number to ``places`` decimals, preserving None."""
    return round(value, places) if value is not None else None


# -- Evaluation context -----------------------------------------------------


def build_evaluation_context(
    conversation_run_id: int,
    reference: Optional[str] = None,
    expected_facts: Optional[list[str]] = None,
    latency_budget_ms: Optional[float] = None,
    cost_budget: Optional[float] = None,
    extra: Optional[dict] = None,
) -> Optional[EvaluationContext]:
    """Reconstruct the evaluation context for a conversation, or None if missing.

    Reuses the replay snapshot (workflow, agent sequence, prompts, steps, tool /
    memory / retriever sub-records) and the conversation cost/token/latency
    totals, flattening them into the shape evaluators consume.
    """
    snapshot = replay_service.build_snapshot(conversation_run_id)
    if snapshot is None:
        return None
    totals = replay_service.conversation_totals(conversation_run_id)

    answer = None
    retrieved_parts: list[str] = []
    documents: list[dict] = []
    tools: list[dict] = []
    memory: list[dict] = []

    for node in snapshot["nodes"]:
        prompt = node.get("prompt") or {}
        if prompt.get("retrieved_context"):
            retrieved_parts.append(prompt["retrieved_context"])
        if node.get("output") is not None:
            answer = node["output"]  # last non-null output wins (final agent)
        for step in node.get("steps", []):
            tools.extend(step.get("tools", []))
            memory.extend(step.get("memory", []))
            for retr in step.get("retrievers", []):
                documents.extend(retr.get("documents", []))

    first_prompt = next(
        (n.get("prompt") for n in snapshot["nodes"] if n.get("prompt")), None
    ) or {}

    return EvaluationContext(
        conversation_run_id=conversation_run_id,
        user_prompt=snapshot.get("user_prompt") or first_prompt.get("user_prompt"),
        system_prompt=snapshot.get("system_prompt") or first_prompt.get("system_prompt"),
        answer=answer,
        retrieved_context="\n".join(retrieved_parts) if retrieved_parts else None,
        documents=documents,
        tools=tools,
        memory=memory,
        latency_ms=totals.get("latency_ms"),
        cost=totals.get("cost"),
        total_tokens=totals.get("total_tokens"),
        reference=reference,
        expected_facts=list(expected_facts or []),
        latency_budget_ms=latency_budget_ms,
        cost_budget=cost_budget,
        extra=dict(extra or {}),
    )
