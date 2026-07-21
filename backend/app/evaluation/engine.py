"""Evaluation engine (v0.5).

Runs a set of pluggable :class:`~app.evaluation.evaluators.Evaluator` instances
over a traced conversation, computes a weighted overall score, and persists an
:class:`~app.models.evaluation_trace.EvaluationRun` with one
:class:`~app.models.evaluation_trace.EvaluationMetric` per evaluator.

Business logic and persistence live in
:mod:`app.services.evaluation_service`; this class only coordinates. It supports
both synchronous (:meth:`EvaluationEngine.evaluate`) and asynchronous
(:meth:`EvaluationEngine.evaluate_async`) execution. Must be used inside a Flask
application context (the async worker re-enters the captured app context).
"""
import logging
import weakref
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Optional

from flask import current_app

from ..models.agent_trace import AgentStatus
from ..services import evaluation_service
from .constraints import constraint_evaluator
from .context import MetricResult
from .evaluators import Evaluator, LLMJudgeEvaluator, default_evaluators

logger = logging.getLogger("agentscope")

# Engines create their async executor lazily and ad hoc (there is no singleton),
# so track any that spun one up in a weak set. This lets the app factory shut
# every live evaluation executor down on worker exit without keeping engines
# alive or leaking threads (see ``shutdown_all_engines``).
_ENGINES_WITH_EXECUTORS: "weakref.WeakSet[EvaluationEngine]" = weakref.WeakSet()


def shutdown_all_engines() -> None:
    """Shut down the async executor of every engine that started one."""
    for engine in list(_ENGINES_WITH_EXECUTORS):
        try:
            engine.shutdown()
        except Exception:  # noqa: BLE001 - best-effort teardown, never raise
            logger.exception("failed to shut down an evaluation engine executor")


class EvaluationError(Exception):
    """Raised when a conversation cannot be evaluated (e.g. it does not exist)."""


class EvaluationResult:
    """The outcome of an evaluation."""

    def __init__(
        self,
        evaluation_run_id: int,
        conversation_run_id: int,
        overall_score: Optional[float],
        metrics: list[MetricResult],
        status: str,
    ) -> None:
        self.evaluation_run_id = evaluation_run_id
        self.conversation_run_id = conversation_run_id
        self.overall_score = overall_score
        self.metrics = metrics
        self.status = status

    @property
    def ok(self) -> bool:
        """True when the evaluation completed successfully."""
        return self.status == AgentStatus.SUCCESS

    def score(self, metric_name: str) -> Optional[float]:
        """Return a single metric's value by name, or None."""
        for m in self.metrics:
            if m.name == metric_name:
                return m.value
        return None

    def __repr__(self) -> str:
        return (
            f"<EvaluationResult run_id={self.evaluation_run_id} "
            f"overall={self.overall_score} metrics={len(self.metrics)}>"
        )


class EvaluationEngine:
    """Scores conversations with pluggable evaluators and persists the results."""

    def __init__(
        self,
        evaluators: Optional[list[Evaluator]] = None,
        judge: Optional[Any] = None,
        judge_model: Optional[str] = None,
        max_workers: int = 4,
    ) -> None:
        """Build an engine.

        ``evaluators`` overrides the built-in rule-based set. When a ``judge``
        callable is supplied, an :class:`LLMJudgeEvaluator` is appended (unless a
        custom evaluator list already includes one).
        """
        self.evaluators = list(evaluators) if evaluators is not None else default_evaluators()
        if judge is not None:
            self.evaluators.append(LLMJudgeEvaluator(judge=judge, model=judge_model))
        self.judge_model = judge_model
        self._max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None

    def register(self, evaluator: Evaluator) -> "EvaluationEngine":
        """Add a (custom) evaluator to this engine and return self for chaining."""
        self.evaluators.append(evaluator)
        return self

    # -- Synchronous --------------------------------------------------------

    def evaluate(
        self,
        conversation_run_id: int,
        reference: Optional[str] = None,
        expected_facts: Optional[list[str]] = None,
        latency_budget_ms: Optional[float] = None,
        cost_budget: Optional[float] = None,
        evaluators: Optional[list[Evaluator]] = None,
        evaluation_type: Optional[str] = None,
        model_name: Optional[str] = None,
        weights: Optional[dict[str, float]] = None,
        metadata: Optional[dict] = None,
        constraints: Optional[list] = None,
    ) -> EvaluationResult:
        """Evaluate a conversation, persisting the run and every metric.

        ``constraints`` (declarative dicts/callables; see
        :mod:`app.evaluation.constraints`) appends a deterministic
        ``constraint_validity`` metric for hard product-requirement checks.
        """
        ctx = evaluation_service.build_evaluation_context(
            conversation_run_id,
            reference=reference,
            expected_facts=expected_facts,
            latency_budget_ms=latency_budget_ms,
            cost_budget=cost_budget,
        )
        if ctx is None:
            raise EvaluationError(
                f"conversation {conversation_run_id} not found or has no trace"
            )

        evs = list(evaluators) if evaluators is not None else list(self.evaluators)
        if constraints:
            evs.append(constraint_evaluator(constraints))
        run = evaluation_service.create_evaluation_run(
            conversation_run_id=conversation_run_id,
            evaluation_type=evaluation_type or _infer_type(evs),
            model_name=model_name or self.judge_model,
            status=AgentStatus.RUNNING,
            metadata=metadata,
        )

        metrics: list[MetricResult] = []
        status = AgentStatus.SUCCESS
        try:
            for evaluator in evs:
                result = evaluator.evaluate(ctx)
                if result is None:
                    continue
                if weights and result.name in weights:
                    result.weight = weights[result.name]
                metrics.append(result)
        except Exception:  # noqa: BLE001 - persist partial results + mark failed
            status = AgentStatus.FAILED
            logger.exception("evaluation failed for conversation %s", conversation_run_id)

        evaluation_service.add_metrics(run.id, metrics)
        overall = _weighted_overall(metrics)
        evaluation_service.finish_evaluation_run(run, overall_score=overall, status=status)

        return EvaluationResult(
            evaluation_run_id=run.id,
            conversation_run_id=conversation_run_id,
            overall_score=overall,
            metrics=metrics,
            status=status,
        )

    # -- Asynchronous -------------------------------------------------------

    def evaluate_async(self, *args, **kwargs) -> "Future[EvaluationResult]":
        """Run :meth:`evaluate` on a worker thread, returning a ``Future``.

        The current Flask app is captured and re-entered inside the worker so the
        evaluation gets its own (thread-local) database session.
        """
        app = current_app._get_current_object()

        def task() -> EvaluationResult:
            with app.app_context():
                try:
                    return self.evaluate(*args, **kwargs)
                finally:
                    # Pooled worker threads are reused; drop the thread-local
                    # session so connections/state never bleed across evals.
                    from ..extensions import db

                    db.session.remove()

        return self._get_executor().submit(task)

    def _get_executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers, thread_name_prefix="eval"
            )
            # Track for coordinated shutdown on worker exit.
            _ENGINES_WITH_EXECUTORS.add(self)
        return self._executor

    def shutdown(self) -> None:
        """Shut down the async executor, if one was created."""
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None


def _infer_type(evaluators: list[Evaluator]) -> str:
    """Infer the evaluation type from the evaluators' kinds."""
    kinds = {getattr(e, "kind", "rule") for e in evaluators}
    if len(kinds) == 1:
        return {"rule": "rule_based", "llm": "llm_judge", "custom": "custom"}[kinds.pop()]
    return "mixed"


def _weighted_overall(metrics: list[MetricResult]) -> Optional[float]:
    """Weighted average of metric values, ignoring ``None`` values."""
    scored = [(m.value, m.weight or 0.0) for m in metrics if m.value is not None]
    total_weight = sum(w for _, w in scored)
    if not scored or total_weight == 0:
        return None
    return round(sum(v * w for v, w in scored) / total_weight, 4)
