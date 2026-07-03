"""Evaluation Engine (v0.5).

Automatic scoring of traced conversations with pluggable evaluators
(rule-based, LLM-as-a-Judge, and custom). Every evaluation and every metric is
persisted via :mod:`app.services.evaluation_service`.

    from app.evaluation import EvaluationEngine

    engine = EvaluationEngine()
    result = engine.evaluate(conversation_run_id, reference="...")
    print(result.overall_score, result.score("faithfulness"))
"""
from .context import EvaluationContext, MetricResult
from .engine import EvaluationEngine, EvaluationError, EvaluationResult
from .evaluators import (
    CustomEvaluator,
    Evaluator,
    LLMJudgeEvaluator,
    Metrics,
    default_evaluators,
)

__all__ = [
    "EvaluationEngine",
    "EvaluationResult",
    "EvaluationError",
    "EvaluationContext",
    "MetricResult",
    "Evaluator",
    "LLMJudgeEvaluator",
    "CustomEvaluator",
    "Metrics",
    "default_evaluators",
]
