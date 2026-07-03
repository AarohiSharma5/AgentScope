"""Model Comparison (v0.5).

Execute one traced workflow against multiple models and compare them on output,
latency, tokens, cost, evaluation score, tool calls, memory usage and retriever
performance. Provider-agnostic: model names are opaque strings.

    from app.comparison import ModelComparisonEngine

    engine = ModelComparisonEngine()
    result = engine.compare(conversation_run_id, ["gpt-4o", "claude-3-5-sonnet"])
    print(result.winner, result.side_by_side)
"""
from .engine import ComparisonError, ComparisonResult, ModelComparisonEngine

__all__ = ["ModelComparisonEngine", "ComparisonResult", "ComparisonError"]
