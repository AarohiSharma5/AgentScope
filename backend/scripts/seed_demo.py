"""Seed realistic demo data for the Analytics dashboard.

Populates ~90 days of evaluated conversations across several models/providers so
the dashboard, Insights and the Investigate → Comparisons flow all look alive in
a demo — including two deliberately planted regressions (a quality drop and a
cost spike) tied to change annotations, so the anomaly → suspect → isolate story
demonstrates end to end.

Usage (from the ``backend`` directory)::

    python -m scripts.seed_demo            # additive
    python -m scripts.seed_demo --reset    # wipe existing traces/evals first
    python -m scripts.seed_demo --days 120 # longer history

The data is generated directly through the ORM (no external LLM calls), so it's
free and instant. Timestamps are backdated so the daily charts have real history.
"""
from __future__ import annotations

import argparse
import random
from datetime import timedelta

from app import create_app
from app.extensions import db
from app.models.agent_trace import AgentRun, AgentStatus, AgentStep
from app.models.evaluation_trace import EvaluationRun
from app.models.trace import Trace
from app.models.workflow_trace import AgentNode, ConversationRun
from app.services import annotation_service, budget_service
from app.utils.timeutils import utcnow

# Cross-provider model roster — this is the story competitors (single-vendor
# dashboards) can't tell: quality-per-dollar compared across providers.
PROFILES = {
    "gpt-4o": {"score": 0.87, "cost": 0.020, "latency": 1500, "fail": 0.02},
    "claude-3-5-sonnet": {"score": 0.89, "cost": 0.014, "latency": 1250, "fail": 0.02},
    "gemini-1.5-pro": {"score": 0.83, "cost": 0.011, "latency": 1700, "fail": 0.03},
    "gpt-4o-mini": {"score": 0.79, "cost": 0.0016, "latency": 900, "fail": 0.04},
}

# Planted change events (days ago) -> becomes an annotation + a sustained shift.
E_QUALITY_REGRESSION = 44   # Claude prompt change tanks quality + raises failures
E_COST_REGRESSION = 10      # gpt-4o context bump roughly doubles per-eval cost
E_LATENCY_INCIDENT = 6      # one-day latency spike across all models

_PROMPTS = [
    "Summarize this support ticket and suggest next steps.",
    "Draft a reply to the customer's refund request.",
    "Extract the action items from this meeting transcript.",
    "Classify the intent of this user message.",
    "Given these docs, answer the user's billing question.",
]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _build_eval(when, model: str, prof: dict, rng: random.Random) -> list:
    """Construct one evaluated conversation (trace + conversation + run/step + eval)."""
    failed = rng.random() < prof["fail"]
    score = _clamp(rng.gauss(prof["score"], 0.05), 0.05, 0.99)
    if failed:
        score = _clamp(score - 0.35, 0.02, 0.6)
    cost = max(0.0001, rng.gauss(prof["cost"], prof["cost"] * 0.18))
    latency = max(80.0, rng.gauss(prof["latency"], prof["latency"] * 0.15))
    tokens_in = max(50, int(rng.gauss(1200, 220)))
    tokens_out = max(20, int(rng.gauss(420, 90)))
    status = AgentStatus.FAILED if failed else AgentStatus.SUCCESS

    trace = Trace(
        user_prompt=rng.choice(_PROMPTS),
        model_name=model,
        timestamp=when,
    )
    conv = ConversationRun(
        conversation_name=f"{model} · session",
        status=status,
        latency_ms=round(latency, 2),
        started_at=when,
        finished_at=when + timedelta(milliseconds=latency),
        created_at=when,
        request=trace,
    )
    run = AgentRun(
        agent_name="Responder",
        agent_type="llm",
        status=status,
        start_time=when,
        end_time=when + timedelta(milliseconds=latency),
        latency_ms=round(latency, 2),
        created_at=when,
        request=trace,
    )
    node = AgentNode(
        agent_role="responder",
        display_name="Responder",
        execution_order=0,
        status=status,
        created_at=when,
        conversation_run=conv,
        agent_run=run,
    )
    step = AgentStep(
        step_number=1,
        step_type="llm",
        name="completion",
        status=status,
        latency_ms=round(latency, 2),
        token_usage={"input": tokens_in, "output": tokens_out, "total": tokens_in + tokens_out},
        cost=round(cost, 6),
        started_at=when,
        finished_at=when + timedelta(milliseconds=latency),
        created_at=when,
        agent_run=run,
    )
    ev = EvaluationRun(
        evaluation_type="quality",
        model_name="gpt-4o (judge)",
        overall_score=round(score, 4),
        status=status,
        started_at=when,
        finished_at=when + timedelta(seconds=2),
        created_at=when,
        conversation_run=conv,
    )
    return [trace, conv, run, node, step, ev]


def _profile_for(model: str, days_ago: int) -> dict:
    """Return the model's profile for a given day, applying planted regressions."""
    prof = dict(PROFILES[model])
    if model == "claude-3-5-sonnet" and days_ago <= E_QUALITY_REGRESSION:
        prof["score"] = 0.72   # v2 prompt hurt answer quality
        prof["fail"] = 0.11
        prof["latency"] *= 1.25
    if model == "gpt-4o" and days_ago <= E_COST_REGRESSION:
        prof["cost"] = 0.046   # 128k context bump ~doubled per-eval cost
    if days_ago == E_LATENCY_INCIDENT:
        prof["latency"] *= 2.3  # infra incident: everything slowed down that day
    return prof


def _reset() -> None:
    """Delete existing traces/evals/annotations/budgets (FK-safe order)."""
    from app.models.annotation import Annotation
    from app.models.budget import Budget

    for model in (EvaluationRun, AgentStep, AgentNode, AgentRun, ConversationRun, Trace):
        db.session.query(model).delete(synchronize_session=False)
    db.session.query(Annotation).delete(synchronize_session=False)
    db.session.query(Budget).delete(synchronize_session=False)
    db.session.commit()


def seed(days: int, reset: bool) -> None:
    rng = random.Random(42)
    now = utcnow()

    if reset:
        _reset()
        print("Cleared existing traces, evaluations, annotations and budgets.")

    total = 0
    for days_ago in range(days - 1, -1, -1):
        day = now - timedelta(days=days_ago)
        batch: list = []
        for model in PROFILES:
            prof = _profile_for(model, days_ago)
            count = rng.randint(3, 6)
            for _ in range(count):
                # Spread each day's conversations across working hours.
                when = day.replace(
                    hour=rng.randint(8, 20), minute=rng.randint(0, 59),
                    second=rng.randint(0, 59), microsecond=0,
                )
                batch.extend(_build_eval(when, model, prof, rng))
                total += 1
        db.session.add_all(batch)
        db.session.commit()

    # Change annotations aligned to the planted regressions (so Insights surfaces
    # them as "suspected changes" the user can Investigate).
    def _mark(days_ago: int, label: str, desc: str) -> None:
        annotation_service.create_annotation(
            label=label,
            annotated_at=(now - timedelta(days=days_ago)).replace(
                hour=9, minute=0, second=0, microsecond=0
            ),
            description=desc,
        )

    _mark(E_QUALITY_REGRESSION, "Shipped v2 responder prompt",
          "Rewrote the Responder system prompt for Claude.")
    _mark(E_COST_REGRESSION, "Enabled 128k context on gpt-4o",
          "Raised the context window for long tickets.")
    _mark(E_LATENCY_INCIDENT, "Vector DB latency incident",
          "Upstream retrieval store degraded for a few hours.")

    # Budgets / SLOs — a couple sit near/over threshold so Insights shows a breach.
    budgets = [
        ("Monthly cost cap", "cost", 7.0, "lte", 30, None),
        ("Quality floor (SLO)", "avg_score", 0.82, "gte", 30, None),
        ("Latency ceiling", "avg_latency", 2000.0, "lte", 30, None),
    ]
    for name, metric, threshold, comparison, window, model in budgets:
        budget_service.create_budget(
            name=name, metric=metric, threshold_value=threshold,
            comparison=comparison, window_days=window, model=model,
        )

    print(f"Seeded {total} evaluated conversations across {len(PROFILES)} models "
          f"over {days} days, plus 3 change annotations and 3 budgets.")
    print("Planted regressions: Claude quality drop (~44d ago), gpt-4o cost spike "
          "(~10d ago), latency incident (~6d ago).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo analytics data.")
    parser.add_argument("--days", type=int, default=90, help="Days of history (default 90).")
    parser.add_argument("--reset", action="store_true", help="Wipe existing data first.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        seed(days=args.days, reset=args.reset)


if __name__ == "__main__":
    main()
