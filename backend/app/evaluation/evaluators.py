"""Pluggable evaluators for the Evaluation Engine (v0.5).

Three kinds of evaluator share one tiny interface (:class:`Evaluator`):

* **Rule-based** — deterministic, dependency-free heuristics (token overlap,
  ratios, budget scores). One per built-in metric.
* **LLM-as-a-Judge** — :class:`LLMJudgeEvaluator`, which delegates scoring to a
  caller-supplied ``judge`` callable (so there is no hard dependency on any
  provider; pass a real model client or a stub).
* **Custom** — :class:`CustomEvaluator`, wrapping any user callable.

Every evaluator returns a :class:`~app.evaluation.context.MetricResult` (with a
``None`` value when the metric is not applicable). All logic here is pure and
unit-testable in isolation from the database.
"""
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from .context import EvaluationContext, MetricResult

logger = logging.getLogger("agentscope")

DEFAULT_LATENCY_BUDGET_MS = 5000.0
DEFAULT_COST_BUDGET = 0.05

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an the is are was were be been being of to in on for and or but with "
    "as at by from this that these those it its into over under then than so "
    "you your we our they their he she his her i me my do does did have has had "
    "will would can could should what which who whom how when where why".split()
)


class Metrics:
    """Canonical metric names produced by the built-in evaluators."""

    CORRECTNESS = "correctness"
    GROUNDEDNESS = "groundedness"
    FAITHFULNESS = "faithfulness"
    CONTEXT_PRECISION = "context_precision"
    CONTEXT_RECALL = "context_recall"
    ANSWER_RELEVANCE = "answer_relevance"
    TOOL_SUCCESS = "tool_success"
    MEMORY_USAGE = "memory_usage"
    LATENCY_SCORE = "latency_score"
    COST_SCORE = "cost_score"


# -- Text helpers -----------------------------------------------------------


def _tokens(text: Optional[str], drop_stopwords: bool = True) -> set[str]:
    """Lowercase word tokens, optionally without stopwords."""
    if not text:
        return set()
    words = _WORD_RE.findall(text.lower())
    if drop_stopwords:
        return {w for w in words if w not in _STOPWORDS}
    return set(words)


def _coverage(a: set[str], b: set[str]) -> Optional[float]:
    """Fraction of ``a`` covered by ``b`` (``None`` when ``a`` is empty)."""
    if not a:
        return None
    return round(len(a & b) / len(a), 4)


def _f1(a: set[str], b: set[str]) -> Optional[float]:
    """Token-overlap F1 between two token sets (``None`` if either is empty)."""
    if not a or not b:
        return None
    overlap = len(a & b)
    if overlap == 0:
        return 0.0
    precision = overlap / len(b)
    recall = overlap / len(a)
    return round(2 * precision * recall / (precision + recall), 4)


# -- Base -------------------------------------------------------------------


class Evaluator(ABC):
    """Scores one metric for an :class:`EvaluationContext`."""

    #: Persisted metric name.
    name: str = "metric"
    #: Default weight in the overall score (overridable per evaluation).
    default_weight: float = 1.0
    #: One of "rule", "llm", "custom" (used to infer the evaluation type).
    kind: str = "rule"

    @abstractmethod
    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        """Return a :class:`MetricResult`, or ``None`` to emit nothing."""

    def _result(self, value: Optional[float], notes: Optional[str] = None) -> MetricResult:
        return MetricResult(name=self.name, value=value, weight=self.default_weight, notes=notes)


# -- Rule-based evaluators --------------------------------------------------


class CorrectnessEvaluator(Evaluator):
    """Token-overlap F1 between the answer and a reference answer."""

    name = Metrics.CORRECTNESS

    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        if not ctx.reference:
            return self._result(None, "no reference answer provided")
        value = _f1(_tokens(ctx.reference), _tokens(ctx.answer))
        return self._result(value, "token-overlap F1 vs reference")


class GroundednessEvaluator(Evaluator):
    """Fraction of the answer's content supported by the retrieved context."""

    name = Metrics.GROUNDEDNESS

    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        if not ctx.answer:
            return self._result(None, "no answer to ground")
        if not ctx.retrieved_context:
            return self._result(None, "no retrieved context")
        value = _coverage(_tokens(ctx.answer), _tokens(ctx.retrieved_context))
        return self._result(value, "answer coverage by retrieved context")


class FaithfulnessEvaluator(Evaluator):
    """Answer support by context OR question (1 - hallucination rate)."""

    name = Metrics.FAITHFULNESS

    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        if not ctx.answer:
            return self._result(None, "no answer to check")
        support = _tokens(ctx.retrieved_context) | _tokens(ctx.user_prompt)
        if not support:
            return self._result(None, "no context or question to support answer")
        value = _coverage(_tokens(ctx.answer), support)
        return self._result(value, "answer support by context+question")


class ContextPrecisionEvaluator(Evaluator):
    """Fraction of retrieved documents that were selected/used."""

    name = Metrics.CONTEXT_PRECISION

    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        if not ctx.documents:
            return self._result(None, "no retrieved documents")
        selected = sum(1 for d in ctx.documents if d.get("selected"))
        value = round(selected / len(ctx.documents), 4)
        return self._result(value, f"{selected}/{len(ctx.documents)} documents selected")


class ContextRecallEvaluator(Evaluator):
    """Fraction of expected facts found in the retrieved context/documents."""

    name = Metrics.CONTEXT_RECALL

    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        if not ctx.expected_facts:
            return self._result(None, "no expected facts provided")
        haystack = _tokens(ctx.retrieved_context, drop_stopwords=False)
        for doc in ctx.documents:
            haystack |= _tokens(doc.get("chunk_text"), drop_stopwords=False)
        found = 0
        for fact in ctx.expected_facts:
            fact_tokens = _tokens(fact, drop_stopwords=False)
            if fact_tokens and fact_tokens <= haystack:
                found += 1
        value = round(found / len(ctx.expected_facts), 4)
        return self._result(value, f"{found}/{len(ctx.expected_facts)} facts recalled")


class AnswerRelevanceEvaluator(Evaluator):
    """Fraction of the question's terms addressed by the answer."""

    name = Metrics.ANSWER_RELEVANCE

    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        if not ctx.user_prompt:
            return self._result(None, "no question/prompt provided")
        if not ctx.answer:
            return self._result(0.0, "no answer produced")
        value = _coverage(_tokens(ctx.user_prompt), _tokens(ctx.answer))
        return self._result(value, "question terms addressed by answer")


class ToolSuccessEvaluator(Evaluator):
    """Fraction of tool executions that succeeded."""

    name = Metrics.TOOL_SUCCESS

    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        if not ctx.tools:
            return self._result(None, "no tool executions")
        ok = sum(1 for t in ctx.tools if t.get("status") == "success")
        value = round(ok / len(ctx.tools), 4)
        return self._result(value, f"{ok}/{len(ctx.tools)} tools succeeded")


class MemoryUsageEvaluator(Evaluator):
    """Fraction of memory accesses whose result was actually used."""

    name = Metrics.MEMORY_USAGE

    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        if not ctx.memory:
            return self._result(None, "no memory accesses")
        used = sum(1 for m in ctx.memory if m.get("used"))
        value = round(used / len(ctx.memory), 4)
        return self._result(value, f"{used}/{len(ctx.memory)} memory hits used")


class LatencyScoreEvaluator(Evaluator):
    """Score = max(0, 1 - latency / budget)."""

    name = Metrics.LATENCY_SCORE

    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        if ctx.latency_ms is None:
            return self._result(None, "no latency recorded")
        budget = ctx.latency_budget_ms or DEFAULT_LATENCY_BUDGET_MS
        value = max(0.0, round(1 - ctx.latency_ms / budget, 4)) if budget else None
        return self._result(value, f"latency {ctx.latency_ms}ms vs budget {budget}ms")


class CostScoreEvaluator(Evaluator):
    """Score = max(0, 1 - cost / budget)."""

    name = Metrics.COST_SCORE

    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        if ctx.cost is None:
            return self._result(None, "no cost recorded")
        budget = ctx.cost_budget or DEFAULT_COST_BUDGET
        value = max(0.0, round(1 - ctx.cost / budget, 4)) if budget else None
        return self._result(value, f"cost {ctx.cost} vs budget {budget}")


# -- LLM-as-a-Judge ---------------------------------------------------------


class LLMJudgeEvaluator(Evaluator):
    """Delegates scoring to a caller-supplied judge callable.

    ``judge`` receives a prompt string (built from the context) and returns
    either a float in ``[0, 1]`` or a ``{"score": float, "notes": str}`` dict.
    Keeping the judge injectable avoids any hard provider dependency and makes
    the evaluator trivially testable with a stub.
    """

    kind = "llm"

    def __init__(
        self,
        judge: Callable[[str], Any],
        name: str = "llm_judge",
        weight: float = 1.0,
        model: Optional[str] = None,
        prompt_builder: Optional[Callable[[EvaluationContext], str]] = None,
    ) -> None:
        self.name = name
        self.default_weight = weight
        self._judge = judge
        self.model = model
        self._prompt_builder = prompt_builder or _default_judge_prompt

    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        prompt = self._prompt_builder(ctx)
        try:
            verdict = self._judge(prompt)
        except Exception as exc:  # noqa: BLE001 - record failure as a metric note
            logger.warning("LLM judge %s failed: %s", self.name, exc)
            return self._result(None, f"judge error: {type(exc).__name__}: {exc}")

        score, notes = verdict, "llm-as-a-judge"
        if isinstance(verdict, dict):
            score = verdict.get("score")
            notes = verdict.get("notes", notes)
        value = None if score is None else round(float(score), 4)
        return self._result(value, notes)


def _default_judge_prompt(ctx: EvaluationContext) -> str:
    """Build a generic judge prompt from the evaluation context."""
    return (
        "Rate the answer from 0 to 1.\n"
        f"Question: {ctx.user_prompt}\n"
        f"Context: {ctx.retrieved_context}\n"
        f"Reference: {ctx.reference}\n"
        f"Answer: {ctx.answer}\n"
    )


# -- Custom -----------------------------------------------------------------


class CustomEvaluator(Evaluator):
    """Wraps a user callable ``fn(ctx)`` returning a float, dict or MetricResult."""

    kind = "custom"

    def __init__(
        self,
        name: str,
        fn: Callable[[EvaluationContext], Any],
        weight: float = 1.0,
    ) -> None:
        self.name = name
        self.default_weight = weight
        self._fn = fn

    def evaluate(self, ctx: EvaluationContext) -> Optional[MetricResult]:
        try:
            out = self._fn(ctx)
        except Exception as exc:  # noqa: BLE001 - record failure as a metric note
            logger.warning("custom evaluator %s failed: %s", self.name, exc)
            return self._result(None, f"evaluator error: {type(exc).__name__}: {exc}")
        if out is None or isinstance(out, MetricResult):
            return out
        if isinstance(out, dict):
            return self._result(
                None if out.get("score") is None else round(float(out["score"]), 4),
                out.get("notes"),
            )
        return self._result(round(float(out), 4))


# -- Defaults ---------------------------------------------------------------


def default_evaluators() -> list[Evaluator]:
    """The full set of built-in rule-based evaluators (one per metric)."""
    return [
        CorrectnessEvaluator(),
        GroundednessEvaluator(),
        FaithfulnessEvaluator(),
        ContextPrecisionEvaluator(),
        ContextRecallEvaluator(),
        AnswerRelevanceEvaluator(),
        ToolSuccessEvaluator(),
        MemoryUsageEvaluator(),
        LatencyScoreEvaluator(),
        CostScoreEvaluator(),
    ]
