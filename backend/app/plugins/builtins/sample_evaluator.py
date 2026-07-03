"""Example EVALUATOR plugin.

Contributes a custom evaluator built on the platform's existing
``app.evaluation.evaluators.Evaluator`` interface, showing that plugins extend
the real abstractions rather than a parallel one.
"""
from ...evaluation.context import EvaluationContext, MetricResult
from ...evaluation.evaluators import Evaluator
from ..base import Capability, PluginBase, PluginContext, PluginMetadata


class KeywordPresenceEvaluator(Evaluator):
    """Scores 1.0 if every expected fact appears in the answer, else the ratio."""

    name = "keyword_presence"
    kind = "custom"
    default_weight = 1.0

    def evaluate(self, ctx: EvaluationContext) -> "MetricResult | None":
        expected = [f for f in (ctx.expected_facts or []) if f]
        if not expected or not ctx.answer:
            return None
        answer = ctx.answer.lower()
        hits = sum(1 for fact in expected if fact.lower() in answer)
        score = hits / len(expected)
        return self._result(score, notes=f"{hits}/{len(expected)} expected facts present")


class SampleEvaluatorPlugin(PluginBase):
    """Contributes the ``keyword_presence`` evaluator."""

    metadata = PluginMetadata(
        name="sample-evaluators",
        version="1.0.0",
        author="AgentScope",
        description="Reference evaluator plugin (keyword presence).",
        capabilities=[Capability.EVALUATOR],
        tags=["example", "evaluation"],
        license="MIT",
    )

    def register(self, context: PluginContext) -> None:
        context.register_evaluator(
            KeywordPresenceEvaluator.name,
            KeywordPresenceEvaluator(),
            description="Fraction of expected facts present in the answer.",
        )
