"""Business logic and persistence for evaluation runs (v0.5).

All SQLAlchemy session handling for :class:`~app.models.evaluation_trace.EvaluationRun`
and :class:`~app.models.evaluation_trace.EvaluationMetric` lives here so the
:class:`~app.evaluation.engine.EvaluationEngine` stays a thin coordinator. Also
reconstructs the :class:`~app.evaluation.context.EvaluationContext` that
evaluators score, reusing the replay snapshot so there is no duplicated
trace-reconstruction logic.
"""
import logging
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from ..evaluation.context import EvaluationContext, MetricResult
from ..evaluation.evaluators import Metrics
from ..extensions import db
from ..models.agent_trace import AgentStatus
from ..models.evaluation_trace import EvaluationMetric, EvaluationRun
from ..services import replay_service
from ..streaming import EventType, emit
from ..utils.sorting import apply_sort, is_valid_sort
from ..utils.timeutils import utcnow
from ..utils.validation import ensure_json_object

logger = logging.getLogger("agentscope")


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
    """Return an evaluation run eager-loaded with its metrics, or None."""
    return (
        db.session.query(EvaluationRun)
        .options(selectinload(EvaluationRun.metrics))
        .filter(EvaluationRun.id == evaluation_run_id)
        .one_or_none()
    )


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
    query = EvaluationRun.query.options(selectinload(EvaluationRun.metrics))
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
    total = db.session.query(func.count(EvaluationRun.id)).scalar() or 0
    success = (
        db.session.query(func.count(EvaluationRun.id))
        .filter(EvaluationRun.status == AgentStatus.SUCCESS)
        .scalar()
        or 0
    )
    avg_score = db.session.query(func.avg(EvaluationRun.overall_score)).scalar()

    metric_rows = (
        db.session.query(
            EvaluationMetric.metric_name, func.avg(EvaluationMetric.metric_value)
        )
        .group_by(EvaluationMetric.metric_name)
        .all()
    )
    by_metric = {name: _round(value, 4) for name, value in metric_rows}

    conversation_ids = [
        row[0]
        for row in db.session.query(EvaluationRun.conversation_run_id).distinct().all()
    ]
    costs: list[float] = []
    latencies: list[float] = []
    for conversation_id in conversation_ids:
        totals = replay_service.conversation_totals(conversation_id)
        if totals.get("cost") is not None:
            costs.append(totals["cost"])
        if totals.get("latency_ms") is not None:
            latencies.append(totals["latency_ms"])

    return {
        "total_evaluations": total,
        "average_evaluation_score": _round(avg_score, 4),
        "average_cost": _mean(costs, 6),
        "average_latency": _mean(latencies, 4),
        "average_correctness": by_metric.get(Metrics.CORRECTNESS),
        "average_faithfulness": by_metric.get(Metrics.FAITHFULNESS),
        "average_groundedness": by_metric.get(Metrics.GROUNDEDNESS),
        "average_tool_accuracy": by_metric.get(Metrics.TOOL_SUCCESS),
        "average_memory_usage": by_metric.get(Metrics.MEMORY_USAGE),
        "success_rate": round(success / total, 4) if total else 0.0,
    }


def get_evaluation_analytics() -> dict:
    """Build daily time-series analytics plus headline rates for the dashboard.

    Each evaluation run is bucketed by its creation date; per-day cost, tokens
    and latency come from the evaluated conversations (reusing
    ``conversation_totals``), alongside the average evaluation score and the
    failure rate. The headline block reuses :func:`get_evaluation_metrics`.
    """
    runs = EvaluationRun.query.order_by(EvaluationRun.created_at.asc()).all()

    buckets: dict[str, dict] = {}
    for run in runs:
        day = (run.created_at.date().isoformat() if run.created_at else "unknown")
        bucket = buckets.setdefault(
            day,
            {"cost": 0.0, "tokens": 0, "latency_sum": 0.0, "latency_n": 0,
             "scores": [], "evaluations": 0, "failures": 0},
        )
        totals = replay_service.conversation_totals(run.conversation_run_id)
        bucket["cost"] += totals.get("cost") or 0.0
        bucket["tokens"] += totals.get("total_tokens") or 0
        if totals.get("latency_ms") is not None:
            bucket["latency_sum"] += totals["latency_ms"]
            bucket["latency_n"] += 1
        if run.overall_score is not None:
            bucket["scores"].append(run.overall_score)
        bucket["evaluations"] += 1
        if run.status == AgentStatus.FAILED:
            bucket["failures"] += 1

    daily = [
        {
            "date": day,
            "cost": round(b["cost"], 6),
            "tokens": b["tokens"],
            "latency_ms": round(b["latency_sum"] / b["latency_n"], 2) if b["latency_n"] else None,
            "evaluation_score": _mean(b["scores"], 4),
            "evaluations": b["evaluations"],
            "failures": b["failures"],
            "failure_rate": round(b["failures"] / b["evaluations"], 4) if b["evaluations"] else 0.0,
        }
        for day, b in sorted(buckets.items())
    ]

    headline = get_evaluation_metrics()
    headline["failure_rate"] = round(1 - headline["success_rate"], 4)
    return {"daily": daily, "totals": headline}


def _round(value: Optional[float], places: int) -> Optional[float]:
    """Round an optional number to ``places`` decimals, preserving None."""
    return round(value, places) if value is not None else None


def _mean(values: list[float], places: int) -> Optional[float]:
    """Mean of a list, rounded, or None when empty."""
    return round(sum(values) / len(values), places) if values else None


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
