"""Serializers for the v0.5 replay, evaluation and comparison models.

Pure functions (no DB access) that turn ORM instances into JSON-serializable
dictionaries, reused across list and detail endpoints so response shapes stay
consistent with the rest of the API.
"""
from ..models.evaluation_trace import (
    EvaluationMetric,
    EvaluationRun,
    ModelComparison,
    ReplayRun,
)
from .common import iso as _iso


def serialize_replay_run(replay: ReplayRun) -> dict:
    """Serialize a replay run."""
    return {
        "id": replay.id,
        "original_conversation_run_id": replay.original_conversation_run_id,
        "replayed_model": replay.replayed_model,
        "temperature": replay.temperature,
        "top_p": replay.top_p,
        "system_prompt_override": replay.system_prompt_override,
        "status": replay.status,
        "started_at": _iso(replay.started_at),
        "finished_at": _iso(replay.finished_at),
        "latency_ms": replay.latency_ms,
        "cost": replay.cost,
        "metadata": replay.replay_metadata,
        "created_at": _iso(replay.created_at),
    }


def serialize_metric(metric: EvaluationMetric) -> dict:
    """Serialize a single evaluation metric."""
    return {
        "id": metric.id,
        "evaluation_run_id": metric.evaluation_run_id,
        "metric_name": metric.metric_name,
        "metric_value": metric.metric_value,
        "weight": metric.weight,
        "notes": metric.notes,
    }


def serialize_evaluation_run(run: EvaluationRun, include_metrics: bool = True) -> dict:
    """Serialize an evaluation run, optionally including its metrics."""
    data = {
        "id": run.id,
        "conversation_run_id": run.conversation_run_id,
        "evaluation_type": run.evaluation_type,
        "model_name": run.model_name,
        "overall_score": run.overall_score,
        "status": run.status,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "metadata": run.evaluation_metadata,
        "created_at": _iso(run.created_at),
    }
    if include_metrics:
        data["metrics"] = [serialize_metric(m) for m in run.metrics]
    return data


def serialize_model_comparison(comparison: ModelComparison) -> dict:
    """Serialize a model comparison record."""
    return {
        "id": comparison.id,
        "conversation_run_id": comparison.conversation_run_id,
        "model_a": comparison.model_a,
        "model_b": comparison.model_b,
        "winner": comparison.winner,
        "reason": comparison.reason,
        "cost_difference": comparison.cost_difference,
        "latency_difference": comparison.latency_difference,
        "token_difference": comparison.token_difference,
        "metadata": comparison.comparison_metadata,
        "created_at": _iso(comparison.created_at),
    }
