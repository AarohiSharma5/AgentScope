"""Business logic for creating, querying and aggregating traces.

Keeping persistence logic here (rather than in the routes) keeps the API thin
and makes the same logic reusable from the middleware/SDK helper.
"""
from typing import Optional

from sqlalchemy import func

from ..extensions import db
from ..models.trace import Trace, TraceStatus

# Rough price table (USD per 1K tokens) used to estimate cost when the caller
# does not provide one. Extend as needed for your providers.
_PRICE_PER_1K = {
    # model_name: (input_price, output_price)
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
}


def estimate_cost(model_name: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    """Estimate request cost in USD from the price table, or None if unknown."""
    prices = _PRICE_PER_1K.get(model_name)
    if not prices:
        return None
    in_price, out_price = prices
    return round(
        (input_tokens or 0) / 1000 * in_price + (output_tokens or 0) / 1000 * out_price,
        6,
    )


def create_trace(data: dict) -> Trace:
    """Create and persist a Trace from a payload dict."""
    input_tokens = data.get("input_tokens")
    output_tokens = data.get("output_tokens")
    total_tokens = data.get("total_tokens")
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0)

    model_name = data.get("model_name", "unknown")
    estimated_cost = data.get("estimated_cost")
    if estimated_cost is None and input_tokens is not None and output_tokens is not None:
        estimated_cost = estimate_cost(model_name, input_tokens, output_tokens)

    trace = Trace(
        user_prompt=data.get("user_prompt"),
        system_prompt=data.get("system_prompt"),
        model_name=model_name,
        latency_ms=data.get("latency_ms"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost=estimated_cost,
        retrieved_documents=data.get("retrieved_documents"),
        tool_calls=data.get("tool_calls"),
        final_response=data.get("final_response"),
        status=data.get("status", TraceStatus.SUCCESS),
        error_message=data.get("error_message"),
    )
    db.session.add(trace)
    db.session.commit()
    return trace


def list_traces(limit: int = 100, offset: int = 0) -> list[Trace]:
    """Return traces ordered by most recent first."""
    return (
        Trace.query.order_by(Trace.timestamp.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


def get_trace(trace_id: int) -> Optional[Trace]:
    """Return a single trace by id, or None."""
    return db.session.get(Trace, trace_id)


def get_stats() -> dict:
    """Compute aggregate dashboard metrics across all traces."""
    total_requests = db.session.query(func.count(Trace.id)).scalar() or 0

    if total_requests == 0:
        return {
            "total_requests": 0,
            "avg_latency_ms": 0,
            "avg_tokens": 0,
            "avg_cost": 0,
            "success_rate": 0,
        }

    avg_latency = db.session.query(func.avg(Trace.latency_ms)).scalar() or 0
    avg_tokens = db.session.query(func.avg(Trace.total_tokens)).scalar() or 0
    avg_cost = db.session.query(func.avg(Trace.estimated_cost)).scalar() or 0
    success_count = (
        db.session.query(func.count(Trace.id))
        .filter(Trace.status == TraceStatus.SUCCESS)
        .scalar()
        or 0
    )

    return {
        "total_requests": total_requests,
        "avg_latency_ms": round(float(avg_latency), 2),
        "avg_tokens": round(float(avg_tokens), 2),
        "avg_cost": round(float(avg_cost), 6),
        "success_rate": round(success_count / total_requests * 100, 2),
    }
