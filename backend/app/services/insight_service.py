"""Analytics insights: anomaly detection + (optional) AI-generated summary.

Two layers, deliberately decoupled:

1. A **deterministic** engine (:func:`build_insights`) that turns the analytics
   series into structured, plain-English *findings* — trend regressions, per-day
   anomalies, top cost drivers, best-value models, tail-latency and budget
   breaches. It needs no API keys and always produces a heuristic summary, so the
   dashboard is never blank or dependent on an external call.
2. An **optional AI narrator** (:func:`generate_ai_summary`) that hands the same
   structured digest to an LLM (via the in-house provider layer) for a polished
   executive summary. If no provider is configured, or the call fails, the caller
   simply keeps the heuristic summary — the feature degrades gracefully.
"""
import json
import logging
import os
from typing import Callable, Optional

from ..utils.timeutils import utcnow
from . import budget_service, evaluation_service

logger = logging.getLogger("agentscope")

# z-score threshold for flagging a single day as an anomaly, and the minimum
# number of days required before anomaly detection is meaningful.
_ANOMALY_Z = 2.0
_ANOMALY_MIN_POINTS = 5

_SEVERITY_ORDER = {"crit": 0, "warn": 1, "info": 2}

_METRIC_LABEL = {
    "cost": "total cost",
    "avg_score": "average score",
    "failure_rate": "failure rate",
    "avg_latency": "average latency",
}


def _round(value: Optional[float], places: int) -> Optional[float]:
    return round(value, places) if value is not None else None


def _fmt_cost(v: Optional[float]) -> str:
    return f"${v:,.4f}" if v is not None else "n/a"


def _fmt_ms(v: Optional[float]) -> str:
    return f"{v:,.0f} ms" if v is not None else "n/a"


def _fmt_pct(v: Optional[float]) -> str:
    return f"{round(v * 100)}%" if v is not None else "n/a"


def _fmt_score(v: Optional[float]) -> str:
    return f"{v:.2f}" if v is not None else "n/a"


def _date(iso: Optional[str]) -> str:
    return iso or "an unknown day"


def _weighted_halves(daily: list, pick: Callable) -> Optional[tuple]:
    """Evaluation-weighted averages of ``pick`` over the earlier vs recent half.

    Weighting by each day's evaluation count means busy days count more than
    quiet ones (mirrors the frontend trend logic). Returns ``(earlier, recent)``
    or ``None`` when either half has no data.
    """
    if not daily or len(daily) < 2:
        return None
    mid = len(daily) // 2

    def wavg(rows):
        num = den = 0.0
        for r in rows:
            v = pick(r)
            if v is None:
                continue
            w = r.get("evaluations") or 0
            num += v * w
            den += w
        return num / den if den else None

    earlier, recent = wavg(daily[:mid]), wavg(daily[mid:])
    if earlier is None or recent is None:
        return None
    return earlier, recent


def _pct_change(pair: Optional[tuple]) -> Optional[float]:
    """Relative change between the earlier and recent halves (or None)."""
    if not pair or pair[0] == 0:
        return None
    return (pair[1] - pair[0]) / abs(pair[0])


def _anomaly(daily: list, pick: Callable, direction: str) -> Optional[tuple]:
    """Most extreme outlier day for ``pick`` as ``(date, value, z)`` or None.

    Uses a simple mean/standard-deviation z-score — explainable and adequate for
    the small day-bucketed series. ``direction`` is ``high`` (spikes are bad, e.g.
    cost/latency/failures) or ``low`` (dips are bad, e.g. score).
    """
    pts = [(r["date"], pick(r)) for r in daily if pick(r) is not None]
    if len(pts) < _ANOMALY_MIN_POINTS:
        return None
    values = [v for _, v in pts]
    n = len(values)
    mean = sum(values) / n
    std = (sum((v - mean) ** 2 for v in values) / n) ** 0.5
    if std == 0:
        return None
    worst = None
    for d, v in pts:
        z = (v - mean) / std
        if direction == "high" and z >= _ANOMALY_Z:
            if worst is None or v > worst[1]:
                worst = (d, v, z)
        elif direction == "low" and z <= -_ANOMALY_Z:
            if worst is None or v < worst[1]:
                worst = (d, v, z)
    return worst


def build_insights(
    days: Optional[int] = None, model: Optional[str] = None
) -> dict:
    """Build structured findings + a heuristic summary over the window.

    Reuses :func:`evaluation_service.get_evaluation_analytics` (so the same
    tenant-scoping, date-bound and model filter apply) and the current budget
    statuses. Returns a payload the route can optionally enrich with an AI
    summary.
    """
    analytics = evaluation_service.get_evaluation_analytics(days=days, model=model)
    daily = analytics.get("daily") or []
    by_model = analytics.get("by_model") or []
    percentiles = analytics.get("percentiles") or {}
    window_label = f"last {days} days" if days and days > 0 else "all-time window"

    findings: list[dict] = []

    def add(fid, severity, title, detail):
        findings.append({"id": fid, "severity": severity, "title": title, "detail": detail})

    evals = sum(d.get("evaluations") or 0 for d in daily)

    def wavg(pick):
        num = den = 0.0
        for d in daily:
            v = pick(d)
            if v is None:
                continue
            w = d.get("evaluations") or 0
            num += v * w
            den += w
        return num / den if den else None

    per_eval_cost = lambda d: (d["cost"] / d["evaluations"]) if d.get("evaluations") else None

    avg_score = wavg(lambda d: d.get("evaluation_score"))
    avg_latency = wavg(lambda d: d.get("latency_ms"))
    total_cost = sum(d.get("cost") or 0.0 for d in daily)
    cost_per_eval = total_cost / evals if evals else None
    failures = sum(d.get("failures") or 0 for d in daily)
    failure_rate = failures / evals if evals else None

    # -- Trend findings (earlier half vs recent half) --
    q = _pct_change(_weighted_halves(daily, lambda d: d.get("evaluation_score")))
    if q is not None and q <= -0.05:
        add("quality_down", "crit" if q <= -0.15 else "warn", "Quality regression",
            f"Average score fell {round(abs(q) * 100)}% versus earlier in the {window_label}.")
    elif q is not None and q >= 0.05:
        add("quality_up", "info", "Quality improving",
            f"Average score rose {round(q * 100)}% across the {window_label}.")

    fh = _weighted_halves(daily, lambda d: d.get("failure_rate"))
    if fh is not None:
        inc = fh[1] - fh[0]
        if inc >= 0.05:
            add("failure_up", "crit" if inc >= 0.15 else "warn", "Failure-rate spike",
                f"Failure rate rose {round(inc * 100)} points versus earlier in the {window_label}.")

    c = _pct_change(_weighted_halves(daily, per_eval_cost))
    if c is not None and c >= 0.15:
        add("cost_up", "warn", "Cost climbing",
            f"Cost per evaluation rose {round(c * 100)}% across the {window_label}.")

    lat = _pct_change(_weighted_halves(daily, lambda d: d.get("latency_ms")))
    if lat is not None and lat >= 0.20:
        add("latency_up", "warn", "Latency climbing",
            f"Average latency rose {round(lat * 100)}% across the {window_label}.")

    # -- Per-day anomalies (pinpoint a specific spike/dip) --
    a = _anomaly(daily, per_eval_cost, "high")
    if a:
        add("cost_anomaly", "warn", "Cost spike",
            f"{_date(a[0])} spiked to {_fmt_cost(a[1])}/eval (~{a[2]:.1f}σ above normal).")
    a = _anomaly(daily, lambda d: d.get("latency_ms"), "high")
    if a:
        add("latency_anomaly", "warn", "Latency spike",
            f"{_date(a[0])} spiked to {_fmt_ms(a[1])} average latency (~{a[2]:.1f}σ above normal).")
    a = _anomaly(daily, lambda d: d.get("failure_rate"), "high")
    if a:
        add("failure_anomaly", "warn", "Failure spike",
            f"{_date(a[0])} saw failures jump to {_fmt_pct(a[1])} (~{a[2]:.1f}σ above normal).")
    a = _anomaly(daily, lambda d: d.get("evaluation_score"), "low")
    if a:
        add("score_anomaly", "warn", "Quality dip",
            f"{_date(a[0])} dipped to a {_fmt_score(a[1])} average score (~{abs(a[2]):.1f}σ below normal).")

    # -- Cross-model findings --
    priced = [m for m in by_model if m.get("average_cost") and m.get("evaluations")]
    if priced:
        top = max(priced, key=lambda m: m["average_cost"] * m["evaluations"])
        add("top_cost_model", "info", "Top cost driver",
            f"{top['model']} drives the most spend "
            f"({_fmt_cost(top['average_cost'] * top['evaluations'])} over {top['evaluations']} evals).")
    valued = [m for m in by_model if m.get("average_cost") and m.get("average_evaluation_score")]
    if len(valued) >= 2:
        best = max(valued, key=lambda m: m["average_evaluation_score"] / m["average_cost"])
        add("best_value_model", "info", "Best value model",
            f"{best['model']} gives the best quality per dollar "
            f"(score {_fmt_score(best['average_evaluation_score'])} at {_fmt_cost(best['average_cost'])}/eval).")

    # -- Tail latency --
    lp = percentiles.get("latency_ms") or {}
    if lp.get("p50") and lp.get("p95") and lp["p95"] >= 2 * lp["p50"]:
        add("tail_latency", "warn", "Heavy latency tail",
            f"p95 latency ({_fmt_ms(lp['p95'])}) is {lp['p95'] / lp['p50']:.1f}x the median "
            f"({_fmt_ms(lp['p50'])}) — a slow tail an average hides.")

    # -- Budget / SLO breaches (independent of the insights window) --
    for b in budget_service.list_budgets():
        st = budget_service.evaluate_status(b)
        label = _METRIC_LABEL.get(b.metric, b.metric)
        arrow = "≥" if b.comparison == "gte" else "≤"
        if st["status"] == "breach":
            add(f"budget_{b.id}", "crit", "Budget breached",
                f"'{b.name}' breached: {label} is {st['actual']} (target {arrow} {b.threshold_value}).")
        elif st["status"] == "warn":
            add(f"budget_{b.id}", "warn", "Budget at risk",
                f"'{b.name}' is at risk: {label} is {st['actual']} (target {arrow} {b.threshold_value}).")

    findings.sort(key=lambda f: _SEVERITY_ORDER.get(f["severity"], 9))

    digest = {
        "window": window_label,
        "model": model,
        "evaluations": evals,
        "avg_score": _round(avg_score, 4),
        "cost_per_eval": _round(cost_per_eval, 6),
        "total_cost": round(total_cost, 6),
        "avg_latency_ms": _round(avg_latency, 2),
        "failure_rate": _round(failure_rate, 4),
        "latency_percentiles": percentiles.get("latency_ms"),
        "cost_percentiles": percentiles.get("cost"),
        "by_model": [
            {
                "model": m.get("model"),
                "evaluations": m.get("evaluations"),
                "average_cost": m.get("average_cost"),
                "average_evaluation_score": m.get("average_evaluation_score"),
                "failure_rate": m.get("failure_rate"),
            }
            for m in by_model[:5]
        ],
    }

    return {
        "generated_at": utcnow().isoformat(),
        "window": {"days": days, "model": model, "label": window_label},
        "summary": _heuristic_summary(digest, findings),
        "summary_source": "heuristic",
        "findings": findings,
        "digest": digest,
    }


def _heuristic_summary(digest: dict, findings: list) -> str:
    """A plain-English summary composed from the top findings (no LLM)."""
    evals = digest["evaluations"]
    if not evals:
        return f"No evaluations recorded in the {digest['window']} — nothing to analyze yet."
    parts = [
        f"Ran {evals} evaluation{'s' if evals != 1 else ''} in the {digest['window']} "
        f"(avg score {_fmt_score(digest['avg_score'])}, "
        f"{_fmt_cost(digest['cost_per_eval'])}/eval)."
    ]
    notable = [f for f in findings if f["severity"] in ("crit", "warn")]
    for f in notable[:3]:
        parts.append(f["detail"])
    if not notable:
        parts.append("Metrics are stable with no notable regressions or anomalies detected.")
    return " ".join(parts)


def generate_ai_summary(
    digest: dict,
    findings: list,
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[str]:
    """Ask an LLM to narrate the digest, or return None if unavailable.

    The provider defaults to ``INSIGHTS_PROVIDER`` (env, else ``openai``) and the
    model to ``INSIGHTS_MODEL`` (env, else the provider's default). Any failure —
    unknown provider, missing key, network/parse error — returns ``None`` so the
    caller falls back to the heuristic summary. Never raises.
    """
    provider_name = provider_name or os.environ.get("INSIGHTS_PROVIDER", "openai")
    model = model or os.environ.get("INSIGHTS_MODEL")
    try:
        from ..providers import ChatMessage, Role, provider_registry

        provider = provider_registry.create(provider_name)
    except Exception:  # noqa: BLE001 - unknown/misconfigured provider is non-fatal
        logger.info("AI insights: provider %r unavailable", provider_name)
        return None

    if not provider.is_configured():
        logger.info("AI insights: provider %r is not configured (no API key)", provider_name)
        return None

    system = (
        "You are a senior AI-observability analyst. Given a JSON digest of an "
        "agent-evaluation dashboard and a list of detected findings, write a crisp "
        "2-4 sentence executive summary for an engineering lead. Lead with the most "
        "important change or risk, cite concrete numbers from the data, and end with "
        "a suggested next step if one is warranted. Do not invent facts. Do not add a "
        "preamble, headings, or bullet points."
    )
    user = json.dumps({"digest": digest, "findings": findings}, default=str)
    try:
        result = provider.chat(
            [ChatMessage(Role.SYSTEM, system), ChatMessage(Role.USER, user)],
            model=model,
            temperature=0.3,
            max_tokens=220,
        )
    except Exception:  # noqa: BLE001 - never let a provider error break the dashboard
        logger.warning("AI insights: summary generation failed", exc_info=True)
        return None

    text = (getattr(result, "text", "") or "").strip()
    return text or None
