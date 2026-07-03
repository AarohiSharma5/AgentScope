"""Evaluation context and metric result value objects (v0.5).

These are pure, ORM-free data holders shared by the evaluators and the
:class:`~app.evaluation.engine.EvaluationEngine`. The context is reconstructed
from a traced conversation by :func:`app.services.evaluation_service.build_evaluation_context`.
"""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MetricResult:
    """A single scored metric produced by an evaluator.

    ``value`` is normally in ``[0, 1]`` (higher is better) or ``None`` when the
    metric was not applicable (e.g. no reference answer was supplied); ``None``
    values are still persisted for transparency but ignored by the weighted
    overall score.
    """

    name: str
    value: Optional[float]
    weight: float = 1.0
    notes: Optional[str] = None


@dataclass
class EvaluationContext:
    """Everything an evaluator needs to score one conversation.

    Built from a conversation's traces (answer, retrieved context/documents,
    tool executions, memory accesses, latency and cost) plus caller-supplied
    ground truth (``reference`` / ``expected_facts``) and scoring budgets.
    """

    conversation_run_id: int
    user_prompt: Optional[str] = None
    system_prompt: Optional[str] = None
    answer: Optional[str] = None
    retrieved_context: Optional[str] = None
    documents: list[dict] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    memory: list[dict] = field(default_factory=list)
    latency_ms: Optional[float] = None
    cost: Optional[float] = None
    total_tokens: Optional[int] = None
    # Caller-supplied ground truth / expectations.
    reference: Optional[str] = None
    expected_facts: list[str] = field(default_factory=list)
    # Scoring budgets (used by the latency / cost evaluators).
    latency_budget_ms: Optional[float] = None
    cost_budget: Optional[float] = None
    # Free-form extras for custom evaluators.
    extra: dict[str, Any] = field(default_factory=dict)
