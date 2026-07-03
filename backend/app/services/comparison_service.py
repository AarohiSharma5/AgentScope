"""Business logic and persistence for model comparison (v0.5).

Builds a provider-agnostic *profile* of a conversation variant (output, latency,
tokens, cost, evaluation score, tool calls, memory usage, retriever
performance), records pairwise :class:`~app.models.evaluation_trace.ModelComparison`
rows, and generates comparison summaries and side-by-side views.

Trace reconstruction and the cost/token/latency totals are reused from
:mod:`app.services.replay_service`, so there is no duplicated aggregation logic.
Model names are treated as opaque strings — the architecture never hard-codes a
provider.
"""
import logging
from typing import Optional

from ..models.evaluation_trace import ModelComparison
from ..services import replay_service

logger = logging.getLogger("agentscope")


def variant_profile(
    conversation_run_id: int,
    model: Optional[str] = None,
    evaluation_score: Optional[float] = None,
    replay_run_id: Optional[int] = None,
) -> Optional[dict]:
    """Aggregate a single variant's comparison profile, or None if missing.

    Reuses the replay snapshot + conversation totals and flattens them into the
    comparison dimensions: output, latency, tokens, cost, evaluation score, tool
    calls, memory usage and retriever performance.
    """
    snapshot = replay_service.build_snapshot(conversation_run_id)
    if snapshot is None:
        return None
    totals = replay_service.conversation_totals(conversation_run_id)

    output = None
    tools_total = tools_ok = 0
    mem_total = mem_used = 0
    retrievals = docs_total = docs_selected = 0
    sim_sum = 0.0
    sim_n = 0

    for node in snapshot["nodes"]:
        if node.get("output") is not None:
            output = node["output"]
        for step in node.get("steps", []):
            for tool in step.get("tools", []):
                tools_total += 1
                if tool.get("status") == "success":
                    tools_ok += 1
            for mem in step.get("memory", []):
                mem_total += 1
                if mem.get("used"):
                    mem_used += 1
            for retr in step.get("retrievers", []):
                retrievals += 1
                for doc in retr.get("documents", []):
                    docs_total += 1
                    if doc.get("selected"):
                        docs_selected += 1
                    if doc.get("similarity_score") is not None:
                        sim_sum += doc["similarity_score"]
                        sim_n += 1

    return {
        "model": model,
        "conversation_run_id": conversation_run_id,
        "replay_run_id": replay_run_id,
        "output": output,
        "latency_ms": totals.get("latency_ms"),
        "total_tokens": totals.get("total_tokens"),
        "cost": totals.get("cost"),
        "evaluation_score": evaluation_score,
        "tool_calls": {
            "total": tools_total,
            "success": tools_ok,
            "success_rate": round(tools_ok / tools_total, 4) if tools_total else None,
        },
        "memory_usage": {
            "total": mem_total,
            "used": mem_used,
            "used_rate": round(mem_used / mem_total, 4) if mem_total else None,
        },
        "retriever": {
            "retrievals": retrievals,
            "documents": docs_total,
            "selected": docs_selected,
            "precision": round(docs_selected / docs_total, 4) if docs_total else None,
            "avg_similarity": round(sim_sum / sim_n, 4) if sim_n else None,
        },
    }


def record_pair(
    baseline: dict,
    variant: dict,
    conversation_run_id: Optional[int] = None,
    winner: Optional[str] = None,
    reason: Optional[str] = None,
) -> ModelComparison:
    """Persist a pairwise comparison (baseline vs variant), computing deltas.

    Differences are ``baseline`` minus ``variant``. When ``winner`` is not given
    it is chosen by higher evaluation score, then lower cost, then lower latency.
    ``conversation_run_id`` anchors the record (defaults to the baseline
    variant's conversation) — the engine anchors it to the source conversation.
    """
    cost_diff = _sub(baseline.get("cost"), variant.get("cost"))
    latency_diff = _sub(baseline.get("latency_ms"), variant.get("latency_ms"))
    token_diff = _sub(baseline.get("total_tokens"), variant.get("total_tokens"))
    token_diff = int(token_diff) if token_diff is not None else None

    if winner is None:
        winner, reason = _decide_winner(baseline, variant, cost_diff, latency_diff, reason)

    return replay_service.create_model_comparison(
        conversation_run_id=conversation_run_id or baseline["conversation_run_id"],
        model_a=baseline.get("model"),
        model_b=variant.get("model"),
        winner=winner,
        reason=reason,
        cost_difference=cost_diff,
        latency_difference=latency_diff,
        token_difference=token_diff,
        metadata={"baseline": baseline, "variant": variant},
    )


def summarize(profiles: list[dict]) -> dict:
    """Rank the variants and pick the best model on each dimension."""
    if not profiles:
        return {"ranking": [], "best_by": {}, "overall_winner": None}

    ranking = sorted(profiles, key=_ranking_key)
    best_by = {
        "evaluation_score": _best(profiles, "evaluation_score", higher=True),
        "latency_ms": _best(profiles, "latency_ms", higher=False),
        "cost": _best(profiles, "cost", higher=False),
        "total_tokens": _best(profiles, "total_tokens", higher=False),
        "tool_success": _best_nested(profiles, "tool_calls", "success_rate", higher=True),
        "memory_usage": _best_nested(profiles, "memory_usage", "used_rate", higher=True),
        "retriever_precision": _best_nested(profiles, "retriever", "precision", higher=True),
    }
    return {
        "ranking": [p.get("model") for p in ranking],
        "best_by": best_by,
        "overall_winner": ranking[0].get("model"),
    }


def side_by_side(profiles: list[dict]) -> dict:
    """Build a metric-by-model matrix for side-by-side viewing."""
    models = [p.get("model") for p in profiles]
    by_model = {p.get("model"): p for p in profiles}

    def row(label: str, getter) -> dict:
        return {"metric": label, "values": {m: getter(by_model[m]) for m in models}}

    return {
        "models": models,
        "rows": [
            row("output", lambda p: p.get("output")),
            row("latency_ms", lambda p: p.get("latency_ms")),
            row("total_tokens", lambda p: p.get("total_tokens")),
            row("cost", lambda p: p.get("cost")),
            row("evaluation_score", lambda p: p.get("evaluation_score")),
            row("tool_success_rate", lambda p: p["tool_calls"]["success_rate"]),
            row("memory_used_rate", lambda p: p["memory_usage"]["used_rate"]),
            row("retriever_precision", lambda p: p["retriever"]["precision"]),
            row("retriever_avg_similarity", lambda p: p["retriever"]["avg_similarity"]),
        ],
    }


# -- Internal helpers -------------------------------------------------------


def _sub(a, b):
    """Subtract two optional numbers, returning None if both are missing."""
    if a is None and b is None:
        return None
    return round((a or 0) - (b or 0), 6)


def _decide_winner(baseline, variant, cost_diff, latency_diff, reason):
    """Pick a winner: higher eval score, then lower cost, then lower latency."""
    a, b = baseline.get("model") or "model_a", variant.get("model") or "model_b"
    sa, sb = baseline.get("evaluation_score"), variant.get("evaluation_score")
    if sa is not None and sb is not None and sa != sb:
        winner = a if sa > sb else b
        return winner, reason or f"higher evaluation score ({winner})"
    if cost_diff is not None and cost_diff != 0:
        winner = b if cost_diff > 0 else a  # baseline - variant > 0 => variant cheaper
        return winner, reason or f"lower cost ({winner})"
    if latency_diff is not None and latency_diff != 0:
        winner = b if latency_diff > 0 else a
        return winner, reason or f"lower latency ({winner})"
    return None, reason or "tie"


def _ranking_key(profile: dict):
    """Sort key: best evaluation score first, then cheapest, then fastest."""
    score = profile.get("evaluation_score")
    return (
        -(score if score is not None else -1),
        profile.get("cost") if profile.get("cost") is not None else float("inf"),
        profile.get("latency_ms") if profile.get("latency_ms") is not None else float("inf"),
    )


def _best(profiles: list[dict], key: str, higher: bool) -> Optional[str]:
    """Model with the best (max/min) value for a top-level numeric key."""
    candidates = [p for p in profiles if p.get(key) is not None]
    if not candidates:
        return None
    chosen = (max if higher else min)(candidates, key=lambda p: p[key])
    return chosen.get("model")


def _best_nested(profiles: list[dict], group: str, key: str, higher: bool) -> Optional[str]:
    """Model with the best value for a nested numeric key (e.g. tool_calls.success_rate)."""
    candidates = [p for p in profiles if (p.get(group) or {}).get(key) is not None]
    if not candidates:
        return None
    chosen = (max if higher else min)(candidates, key=lambda p: p[group][key])
    return chosen.get("model")
