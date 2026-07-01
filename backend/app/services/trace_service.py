"""Business logic for creating, querying and aggregating traces.

Keeping persistence logic here (rather than in the routes) keeps the API thin
and makes the same logic reusable from the middleware/SDK helper.

This module also owns the persistence layer for **agent execution tracing**
(v0.2). All SQLAlchemy session handling lives here so routes and the
``TraceRecorder`` SDK never touch the session directly.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, asc, cast, desc, func, or_

from ..extensions import db
from ..models.trace import Trace, TraceStatus
from ..models.agent_trace import (
    AgentRun,
    AgentStep,
    AgentStatus,
    ToolExecution,
    MemoryAccess,
    RetrieverTrace,
)

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


def update_trace(trace_id: int, **fields) -> Optional[Trace]:
    """Update an existing Trace in place (used to store the final response).

    Only known columns are written, and ``total_tokens`` is recomputed when
    input/output tokens are supplied without an explicit total. Returns the
    updated Trace, or None if it does not exist.
    """
    trace = db.session.get(Trace, trace_id)
    if trace is None:
        return None

    for key, value in fields.items():
        if value is not None and hasattr(trace, key):
            setattr(trace, key, value)

    if fields.get("total_tokens") is None and (
        fields.get("input_tokens") is not None or fields.get("output_tokens") is not None
    ):
        trace.total_tokens = (trace.input_tokens or 0) + (trace.output_tokens or 0)

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


# ---------------------------------------------------------------------------
# Agent execution tracing (v0.2)
#
# These functions encapsulate all SQLAlchemy session logic for the agent
# tracing models. The TraceRecorder SDK (utils/trace_recorder.py) composes
# them; routes should never touch the session directly.
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


def create_agent_run(
    request_id: int,
    agent_name: str,
    agent_type: Optional[str] = None,
    parent_run_id: Optional[int] = None,
    status: str = AgentStatus.RUNNING,
    start_time: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> AgentRun:
    """Persist a new agent run and return it (flushed, so ``id`` is set)."""
    run = AgentRun(
        request_id=request_id,
        agent_name=agent_name,
        agent_type=agent_type,
        parent_run_id=parent_run_id,
        status=status,
        start_time=start_time or _utcnow(),
        run_metadata=metadata,
    )
    db.session.add(run)
    db.session.commit()
    return run


def finish_agent_run(
    run: AgentRun,
    status: str = AgentStatus.SUCCESS,
    end_time: Optional[datetime] = None,
    latency_ms: Optional[float] = None,
    metadata: Optional[dict] = None,
) -> AgentRun:
    """Mark an agent run finished, recording end time, latency and status."""
    run.end_time = end_time or _utcnow()
    run.status = status
    if latency_ms is not None:
        run.latency_ms = latency_ms
    if metadata is not None:
        run.run_metadata = metadata
    db.session.commit()
    return run


def create_agent_step(
    agent_run_id: int,
    step_number: Optional[int] = None,
    step_type: Optional[str] = None,
    name: Optional[str] = None,
    input: Optional[str] = None,
    output: Optional[str] = None,
    status: str = AgentStatus.RUNNING,
    started_at: Optional[datetime] = None,
    token_usage: Optional[dict] = None,
    cost: Optional[float] = None,
    metadata: Optional[dict] = None,
) -> AgentStep:
    """Persist a new step within an agent run."""
    step = AgentStep(
        agent_run_id=agent_run_id,
        step_number=step_number,
        step_type=step_type,
        name=name,
        input=input,
        output=output,
        status=status,
        started_at=started_at or _utcnow(),
        token_usage=token_usage,
        cost=cost,
        step_metadata=metadata,
    )
    db.session.add(step)
    db.session.commit()
    return step


def finish_agent_step(
    step: AgentStep,
    status: str = AgentStatus.SUCCESS,
    output: Optional[str] = None,
    token_usage: Optional[dict] = None,
    cost: Optional[float] = None,
    latency_ms: Optional[float] = None,
    finished_at: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> AgentStep:
    """Mark a step finished, recording end time, latency, output and status."""
    step.finished_at = finished_at or _utcnow()
    step.status = status
    if output is not None:
        step.output = output
    if token_usage is not None:
        step.token_usage = token_usage
    if cost is not None:
        step.cost = cost
    if latency_ms is not None:
        step.latency_ms = latency_ms
    if metadata is not None:
        step.step_metadata = metadata
    db.session.commit()
    return step


def create_tool_execution(
    step_id: int,
    tool_name: str,
    arguments: Optional[dict] = None,
    result: Optional[str] = None,
    status: str = AgentStatus.SUCCESS,
    latency_ms: Optional[float] = None,
    error_message: Optional[str] = None,
) -> ToolExecution:
    """Persist a tool/function call made during a step."""
    tool = ToolExecution(
        step_id=step_id,
        tool_name=tool_name,
        arguments=arguments,
        result=result,
        status=status,
        latency_ms=latency_ms,
        error_message=error_message,
    )
    db.session.add(tool)
    db.session.commit()
    return tool


def create_memory_access(
    step_id: int,
    memory_type: Optional[str] = None,
    query: Optional[str] = None,
    retrieved_text: Optional[str] = None,
    similarity_score: Optional[float] = None,
    used: Optional[bool] = None,
    latency_ms: Optional[float] = None,
) -> MemoryAccess:
    """Persist a memory read/lookup made during a step."""
    memory = MemoryAccess(
        step_id=step_id,
        memory_type=memory_type,
        query=query,
        retrieved_text=retrieved_text,
        similarity_score=similarity_score,
        used=used,
        latency_ms=latency_ms,
    )
    db.session.add(memory)
    db.session.commit()
    return memory


def create_retriever_trace(
    step_id: int,
    query: Optional[str] = None,
    retrieved_documents: Optional[list] = None,
    embedding_time_ms: Optional[float] = None,
    retrieval_time_ms: Optional[float] = None,
    num_documents: Optional[int] = None,
) -> RetrieverTrace:
    """Persist a retrieval (RAG) call made during a step."""
    if num_documents is None and retrieved_documents is not None:
        num_documents = len(retrieved_documents)
    retriever = RetrieverTrace(
        step_id=step_id,
        query=query,
        retrieved_documents=retrieved_documents,
        embedding_time_ms=embedding_time_ms,
        retrieval_time_ms=retrieval_time_ms,
        num_documents=num_documents,
    )
    db.session.add(retriever)
    db.session.commit()
    return retriever


# ---------------------------------------------------------------------------
# Agent execution tracing - read/query layer (v0.2 API)
#
# Query, pagination, sorting, filtering and aggregation logic lives here so the
# routes stay thin and free of business logic.
# ---------------------------------------------------------------------------

# Fields that agent runs may be sorted by (exposed for route validation).
AGENT_RUN_SORTABLE = {
    "created_at",
    "start_time",
    "end_time",
    "latency_ms",
    "agent_name",
    "status",
}

_AGENT_RUN_SORT_COLUMNS = {name: getattr(AgentRun, name) for name in AGENT_RUN_SORTABLE}


def is_valid_agent_run_sort(sort: str) -> bool:
    """Return True if ``sort`` targets an allowed field (optional ``-`` prefix)."""
    if not sort:
        return False
    field = sort[1:] if sort.startswith("-") else sort
    return field in AGENT_RUN_SORTABLE


def _apply_agent_run_sort(query, sort: str):
    """Apply ordering to an AgentRun query. Assumes ``sort`` already validated."""
    descending = sort.startswith("-")
    field = sort[1:] if descending else sort
    column = _AGENT_RUN_SORT_COLUMNS[field]
    return query.order_by(desc(column) if descending else asc(column))


def list_agent_runs(
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
    agent_type: Optional[str] = None,
    sort: str = "-created_at",
    q: Optional[str] = None,
) -> tuple[list[AgentRun], int]:
    """Return a page of agent runs and the total matching count.

    Filtering by ``status`` / ``agent_type``, free-text search (``q``), sorting
    and pagination are all applied at the database level. Search matches the
    agent name, type, status and (numeric) run/request ids, case-insensitively.
    """
    query = AgentRun.query
    if status is not None:
        query = query.filter(AgentRun.status == status)
    if agent_type is not None:
        query = query.filter(AgentRun.agent_type == agent_type)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                AgentRun.agent_name.ilike(like),
                AgentRun.agent_type.ilike(like),
                AgentRun.status.ilike(like),
                cast(AgentRun.id, String).ilike(like),
                cast(AgentRun.request_id, String).ilike(like),
            )
        )

    total = query.count()
    query = _apply_agent_run_sort(query, sort)
    items = query.limit(limit).offset((page - 1) * limit).all()
    return items, total


def get_agent_run(run_id: int) -> Optional[AgentRun]:
    """Return a single agent run by id, or None."""
    return db.session.get(AgentRun, run_id)


def list_agent_runs_for_request(request_id: int) -> list[AgentRun]:
    """Return every agent run belonging to a request, most recent first."""
    return (
        AgentRun.query.filter(AgentRun.request_id == request_id)
        .order_by(AgentRun.created_at.desc())
        .all()
    )


def get_agent_metrics() -> dict:
    """Compute aggregate dashboard metrics across all agent runs."""
    total_runs = db.session.query(func.count(AgentRun.id)).scalar() or 0

    if total_runs == 0:
        return {
            "total_agent_runs": 0,
            "average_latency": 0,
            "average_steps": 0,
            "average_tool_calls": 0,
            "average_memory_calls": 0,
            "average_retrievals": 0,
            "average_cost": 0,
            "success_rate": 0,
        }

    avg_latency = db.session.query(func.avg(AgentRun.latency_ms)).scalar() or 0
    total_steps = db.session.query(func.count(AgentStep.id)).scalar() or 0
    total_tools = db.session.query(func.count(ToolExecution.id)).scalar() or 0
    total_memory = db.session.query(func.count(MemoryAccess.id)).scalar() or 0
    total_retrievals = db.session.query(func.count(RetrieverTrace.id)).scalar() or 0
    total_cost = db.session.query(func.coalesce(func.sum(AgentStep.cost), 0.0)).scalar() or 0
    success_runs = (
        db.session.query(func.count(AgentRun.id))
        .filter(AgentRun.status == AgentStatus.SUCCESS)
        .scalar()
        or 0
    )

    return {
        "total_agent_runs": total_runs,
        "average_latency": round(float(avg_latency), 2),
        "average_steps": round(total_steps / total_runs, 2),
        "average_tool_calls": round(total_tools / total_runs, 2),
        "average_memory_calls": round(total_memory / total_runs, 2),
        "average_retrievals": round(total_retrievals / total_runs, 2),
        "average_cost": round(float(total_cost) / total_runs, 6),
        "success_rate": round(success_runs / total_runs * 100, 2),
    }
