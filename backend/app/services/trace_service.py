"""Business logic for creating, querying and aggregating traces.

Keeping persistence logic here (rather than in the routes) keeps the API thin
and makes the same logic reusable from the middleware/SDK helper.

This module also owns the persistence layer for **agent execution tracing**
(v0.2). All SQLAlchemy session handling lives here so routes and the
``TraceRecorder`` SDK never touch the session directly.
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import selectinload

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
from ..models.rag_trace import EmbeddingTrace, PromptAssembly, RetrievedDocument
from ..utils.sorting import apply_sort, is_valid_sort
from ..utils.timeutils import utcnow
from ..utils.tokens import estimate_tokens
from ..utils.validation import ensure_json_array, ensure_json_object

logger = logging.getLogger("agentscope")

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
        retrieved_documents=ensure_json_array(data.get("retrieved_documents"), "retrieved_documents"),
        tool_calls=ensure_json_array(data.get("tool_calls"), "tool_calls"),
        final_response=data.get("final_response"),
        status=data.get("status", TraceStatus.SUCCESS),
        error_message=data.get("error_message"),
    )
    db.session.add(trace)
    db.session.commit()
    logger.debug("Created trace id=%s model=%s", trace.id, trace.model_name)
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


def create_agent_run(
    request_id: int,
    agent_name: str,
    agent_type: Optional[str] = None,
    parent_run_id: Optional[int] = None,
    status: str = AgentStatus.RUNNING,
    start_time: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> AgentRun:
    """Persist a new agent run and return it (committed, so ``id`` is set)."""
    run = AgentRun(
        request_id=request_id,
        agent_name=agent_name,
        agent_type=agent_type,
        parent_run_id=parent_run_id,
        status=status,
        start_time=start_time or utcnow(),
        run_metadata=ensure_json_object(metadata, "metadata"),
    )
    db.session.add(run)
    db.session.commit()
    logger.debug("Started agent run id=%s name=%s request_id=%s", run.id, agent_name, request_id)
    return run


def finish_agent_run(
    run: AgentRun,
    status: str = AgentStatus.SUCCESS,
    end_time: Optional[datetime] = None,
    latency_ms: Optional[float] = None,
    metadata: Optional[dict] = None,
) -> AgentRun:
    """Mark an agent run finished, recording end time, latency and status."""
    run.end_time = end_time or utcnow()
    run.status = status
    if latency_ms is not None:
        run.latency_ms = latency_ms
    if metadata is not None:
        run.run_metadata = ensure_json_object(metadata, "metadata")
    db.session.commit()
    logger.debug("Finished agent run id=%s status=%s latency_ms=%s", run.id, status, run.latency_ms)
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
        started_at=started_at or utcnow(),
        token_usage=ensure_json_object(token_usage, "token_usage"),
        cost=cost,
        step_metadata=ensure_json_object(metadata, "metadata"),
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
    step.finished_at = finished_at or utcnow()
    step.status = status
    if output is not None:
        step.output = output
    if token_usage is not None:
        step.token_usage = ensure_json_object(token_usage, "token_usage")
    if cost is not None:
        step.cost = cost
    if latency_ms is not None:
        step.latency_ms = latency_ms
    if metadata is not None:
        step.step_metadata = ensure_json_object(metadata, "metadata")
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
        arguments=ensure_json_object(arguments, "arguments"),
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
    retrieved_documents = ensure_json_array(retrieved_documents, "retrieved_documents")
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


def update_retriever_trace(
    retriever_trace_id: int,
    embedding_time_ms: Optional[float] = None,
    retrieval_time_ms: Optional[float] = None,
    num_documents: Optional[int] = None,
    retrieved_documents: Optional[list] = None,
) -> Optional[RetrieverTrace]:
    """Enrich an existing retriever trace with timings and document counts.

    Used by the RetrievalService once embedding + search timings are known.
    """
    retriever = db.session.get(RetrieverTrace, retriever_trace_id)
    if retriever is None:
        return None
    if embedding_time_ms is not None:
        retriever.embedding_time_ms = embedding_time_ms
    if retrieval_time_ms is not None:
        retriever.retrieval_time_ms = retrieval_time_ms
    if num_documents is not None:
        retriever.num_documents = num_documents
    if retrieved_documents is not None:
        retriever.retrieved_documents = ensure_json_array(retrieved_documents, "retrieved_documents")
    db.session.commit()
    logger.debug(
        "Updated retriever trace id=%s num_documents=%s retrieval_time_ms=%s",
        retriever_trace_id, retriever.num_documents, retriever.retrieval_time_ms,
    )
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
    return is_valid_sort(sort, AGENT_RUN_SORTABLE)


def _apply_agent_run_sort(query, sort: str):
    """Apply ordering to an AgentRun query. Assumes ``sort`` already validated."""
    return apply_sort(query, sort, _AGENT_RUN_SORT_COLUMNS)


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


# ---------------------------------------------------------------------------
# RAG / prompt-assembly tracing (v0.3)
#
# Persistence + business logic (token counting, cost estimation, reranking) for
# the v0.3 models. The TraceRecorder SDK only orchestrates and calls into here.
# ---------------------------------------------------------------------------

# Embedding price table (USD per 1K input tokens). Extend per provider.
_EMBEDDING_PRICE_PER_1K = {
    "text-embedding-3-small": 0.00002,
    "text-embedding-3-large": 0.00013,
    "text-embedding-ada-002": 0.0001,
}


def estimate_embedding_cost(model: Optional[str], input_tokens: Optional[int]) -> Optional[float]:
    """Estimate embedding cost in USD, or None if the model/tokens are unknown."""
    if not model or input_tokens is None:
        return None
    price = _EMBEDDING_PRICE_PER_1K.get(model)
    if price is None:
        return None
    return round(input_tokens / 1000 * price, 8)


def create_embedding_trace(
    retriever_trace_id: int,
    embedding_model: Optional[str] = None,
    embedding_dimension: Optional[int] = None,
    input_tokens: Optional[int] = None,
    input_text: Optional[str] = None,
    latency_ms: Optional[float] = None,
    cost: Optional[float] = None,
    metadata: Optional[dict] = None,
) -> EmbeddingTrace:
    """Persist an embedding call for a retriever trace.

    Token count is derived from ``input_text`` when ``input_tokens`` is omitted,
    and cost is estimated from the model + tokens when not supplied.
    """
    if input_tokens is None and input_text is not None:
        input_tokens = estimate_tokens(input_text)
    if cost is None:
        cost = estimate_embedding_cost(embedding_model, input_tokens)

    embedding = EmbeddingTrace(
        retriever_trace_id=retriever_trace_id,
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        input_tokens=input_tokens,
        latency_ms=latency_ms,
        cost=cost,
        embedding_metadata=ensure_json_object(metadata, "metadata"),
    )
    db.session.add(embedding)
    db.session.commit()
    logger.debug(
        "Recorded embedding id=%s trace_id=%s model=%s tokens=%s",
        embedding.id, retriever_trace_id, embedding_model, input_tokens,
    )
    return embedding


def create_retrieved_document(
    retriever_trace_id: int,
    document_id: Optional[str] = None,
    document_name: Optional[str] = None,
    document_source: Optional[str] = None,
    chunk_index: Optional[int] = None,
    chunk_text: Optional[str] = None,
    similarity_score: Optional[float] = None,
    selected: bool = False,
    metadata: Optional[dict] = None,
) -> RetrievedDocument:
    """Persist a single retrieved document/chunk for a retriever trace."""
    document = RetrievedDocument(
        retriever_trace_id=retriever_trace_id,
        document_id=document_id,
        document_name=document_name,
        document_source=document_source,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        similarity_score=similarity_score,
        selected=bool(selected),
        doc_metadata=ensure_json_object(metadata, "metadata"),
    )
    db.session.add(document)
    db.session.commit()
    logger.debug(
        "Recorded retrieved document id=%s trace_id=%s selected=%s score=%s",
        document.id, retriever_trace_id, document.selected, document.similarity_score,
    )
    return document


def update_retrieved_document(
    document_id: int,
    similarity_score: Optional[float] = None,
    selected: Optional[bool] = None,
    metadata: Optional[dict] = None,
) -> Optional[RetrievedDocument]:
    """Update a retrieved document's score/selection (used for similarity/rerank)."""
    document = db.session.get(RetrievedDocument, document_id)
    if document is None:
        return None
    if similarity_score is not None:
        document.similarity_score = similarity_score
    if selected is not None:
        document.selected = bool(selected)
    if metadata is not None:
        document.doc_metadata = ensure_json_object(metadata, "metadata")
    db.session.commit()
    return document


def create_prompt_assembly(
    agent_run_id: int,
    system_prompt: Optional[str] = None,
    conversation_context: Optional[str] = None,
    retrieved_context: Optional[str] = None,
    memory_context: Optional[str] = None,
    user_prompt: Optional[str] = None,
    assembled_prompt: Optional[str] = None,
    system_tokens: Optional[int] = None,
    conversation_tokens: Optional[int] = None,
    retrieval_tokens: Optional[int] = None,
    memory_tokens: Optional[int] = None,
    user_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
) -> PromptAssembly:
    """Persist a prompt assembly for an agent run.

    Per-source token counts are derived from their text when not provided, the
    total is summed when omitted, and ``assembled_prompt`` defaults to the
    non-empty context sources joined in order.
    """
    sources = [
        ("system", system_prompt, system_tokens),
        ("conversation", conversation_context, conversation_tokens),
        ("retrieved", retrieved_context, retrieval_tokens),
        ("memory", memory_context, memory_tokens),
        ("user", user_prompt, user_tokens),
    ]
    counts = {
        name: (tokens if tokens is not None else estimate_tokens(text))
        for name, text, tokens in sources
    }
    if total_tokens is None:
        total_tokens = sum(counts.values())
    if assembled_prompt is None:
        assembled_prompt = "\n\n".join(text for _, text, _ in sources if text)

    assembly = PromptAssembly(
        agent_run_id=agent_run_id,
        system_prompt=system_prompt,
        conversation_context=conversation_context,
        retrieved_context=retrieved_context,
        memory_context=memory_context,
        user_prompt=user_prompt,
        assembled_prompt=assembled_prompt,
        system_tokens=counts["system"],
        conversation_tokens=counts["conversation"],
        retrieval_tokens=counts["retrieved"],
        memory_tokens=counts["memory"],
        user_tokens=counts["user"],
        total_tokens=total_tokens,
    )
    db.session.add(assembly)
    db.session.commit()
    logger.debug(
        "Recorded prompt assembly id=%s run_id=%s total_tokens=%s",
        assembly.id, agent_run_id, total_tokens,
    )

    # Automatically capture a versioned, hashed snapshot of the assembled prompt
    # (de-duplicated by hash) so prompts can be diffed across runs over time.
    from . import prompt_service

    prompt_service.record_prompt_version(
        agent_run_id,
        assembled_prompt,
        metadata={"prompt_assembly_id": assembly.id, "total_tokens": total_tokens},
    )
    return assembly


def apply_reranking(
    retriever_trace_id: int,
    ranking: Optional[list] = None,
    top_k: Optional[int] = None,
) -> list[RetrievedDocument]:
    """Apply reranking results to a retriever trace's documents.

    ``ranking`` is an optional list of dicts identifying documents (by
    ``document_id`` or ``chunk_index``) with a new ``score`` and/or ``selected``
    flag. When ``top_k`` is given, documents are ordered by score (descending)
    and only the top ``k`` are marked ``selected``. Returns the documents in
    (reranked) score order.
    """
    documents = (
        RetrievedDocument.query.filter_by(retriever_trace_id=retriever_trace_id).all()
    )
    by_doc_id = {d.document_id: d for d in documents if d.document_id is not None}
    by_chunk = {d.chunk_index: d for d in documents if d.chunk_index is not None}

    for item in ranking or []:
        target = None
        if item.get("document_id") is not None:
            target = by_doc_id.get(item["document_id"])
        elif item.get("chunk_index") is not None:
            target = by_chunk.get(item["chunk_index"])
        if target is None:
            continue
        if item.get("score") is not None:
            target.similarity_score = item["score"]
        if item.get("selected") is not None:
            target.selected = bool(item["selected"])

    ordered = sorted(
        documents,
        key=lambda d: (d.similarity_score if d.similarity_score is not None else float("-inf")),
        reverse=True,
    )
    if top_k is not None:
        for position, document in enumerate(ordered):
            document.selected = position < top_k

    db.session.commit()
    return ordered


# ---------------------------------------------------------------------------
# RAG read/query layer (v0.3 API)
#
# Query, pagination, sorting, filtering and aggregation for retriever traces,
# retrieved documents, embeddings and prompt assemblies. Note: RetrieverTrace
# has a mapped column named ``query`` which shadows Flask-SQLAlchemy's ``.query``
# attribute, so ``db.session.query(RetrieverTrace)`` is used here.
# ---------------------------------------------------------------------------

# Fields a retrieval may be sorted by (RetrieverTrace has no timestamp column,
# so ``id`` stands in for recency).
RETRIEVAL_SORTABLE = {
    "id",
    "num_documents",
    "embedding_time_ms",
    "retrieval_time_ms",
}

_RETRIEVAL_SORT_COLUMNS = {name: getattr(RetrieverTrace, name) for name in RETRIEVAL_SORTABLE}


def _retrieval_summary_loaders():
    """Eager-load options for the fields a retrieval *summary* touches.

    Serializing a list reads each trace's documents, embedding and owning run
    (via its step); eager-loading them here turns a per-row N+1 into a handful of
    batched ``SELECT ... IN`` queries.
    """
    return (
        selectinload(RetrieverTrace.documents),
        selectinload(RetrieverTrace.embedding_trace),
        selectinload(RetrieverTrace.step).selectinload(AgentStep.agent_run),
    )


def _retrieval_detail_loaders():
    """Eager-load options for a retrieval *detail* (adds the run's prompt assembly)."""
    return (
        selectinload(RetrieverTrace.documents),
        selectinload(RetrieverTrace.embedding_trace),
        selectinload(RetrieverTrace.step)
        .selectinload(AgentStep.agent_run)
        .selectinload(AgentRun.prompt_assembly),
    )


def is_valid_retrieval_sort(sort: str) -> bool:
    """Return True if ``sort`` targets an allowed field (optional ``-`` prefix)."""
    return is_valid_sort(sort, RETRIEVAL_SORTABLE)


def _apply_retrieval_sort(query, sort: str):
    """Apply ordering to a retrieval query. Assumes ``sort`` already validated."""
    return apply_sort(query, sort, _RETRIEVAL_SORT_COLUMNS)


def list_retrievals(
    page: int = 1,
    limit: int = 20,
    q: Optional[str] = None,
    sort: str = "-id",
    embedding_model: Optional[str] = None,
    min_documents: Optional[int] = None,
) -> tuple[list[RetrieverTrace], int]:
    """Return a page of retriever traces and the total matching count.

    Search (``q``) matches the query text and (numeric) trace/step ids. Filtering
    by ``embedding_model`` joins the embedding trace; ``min_documents`` filters on
    the retrieved document count. Sorting/pagination happen in the database.
    """
    query = db.session.query(RetrieverTrace).options(*_retrieval_summary_loaders())

    if embedding_model is not None:
        query = query.join(
            EmbeddingTrace, EmbeddingTrace.retriever_trace_id == RetrieverTrace.id
        ).filter(EmbeddingTrace.embedding_model == embedding_model)
    if min_documents is not None:
        query = query.filter(RetrieverTrace.num_documents >= min_documents)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                RetrieverTrace.query.ilike(like),
                cast(RetrieverTrace.id, String).ilike(like),
                cast(RetrieverTrace.step_id, String).ilike(like),
            )
        )

    total = query.count()
    query = _apply_retrieval_sort(query, sort)
    items = query.limit(limit).offset((page - 1) * limit).all()
    return items, total


def get_retrieval(retrieval_id: int) -> Optional[RetrieverTrace]:
    """Return a single retriever trace by id (with related data eager-loaded), or None."""
    return (
        db.session.query(RetrieverTrace)
        .options(*_retrieval_detail_loaders())
        .filter(RetrieverTrace.id == retrieval_id)
        .one_or_none()
    )


def get_prompt_assembly(prompt_id: int) -> Optional[PromptAssembly]:
    """Return a single prompt assembly by id, or None."""
    return db.session.get(PromptAssembly, prompt_id)


def get_rag_metrics() -> dict:
    """Compute aggregate RAG metrics across all retrievals."""
    total_retrievals = db.session.query(func.count(RetrieverTrace.id)).scalar() or 0

    if total_retrievals == 0:
        return {
            "total_retrievals": 0,
            "average_similarity": 0,
            "average_documents_retrieved": 0,
            "average_documents_used": 0,
            "average_embedding_latency": 0,
            "average_retrieval_latency": 0,
            "average_prompt_size": 0,
            "total_embedding_cost": 0,
            "success_rate": 0,
        }

    avg_similarity = db.session.query(func.avg(RetrievedDocument.similarity_score)).scalar() or 0
    avg_docs_retrieved = db.session.query(func.avg(RetrieverTrace.num_documents)).scalar() or 0
    selected_docs = (
        db.session.query(func.count(RetrievedDocument.id))
        .filter(RetrievedDocument.selected.is_(True))
        .scalar()
        or 0
    )
    avg_embedding_latency = db.session.query(func.avg(EmbeddingTrace.latency_ms)).scalar() or 0
    avg_retrieval_latency = db.session.query(func.avg(RetrieverTrace.retrieval_time_ms)).scalar() or 0
    avg_prompt_size = db.session.query(func.avg(PromptAssembly.total_tokens)).scalar() or 0
    total_embedding_cost = (
        db.session.query(func.coalesce(func.sum(EmbeddingTrace.cost), 0.0)).scalar() or 0
    )
    # "Success" = a retrieval that returned at least one document.
    successful = (
        db.session.query(func.count(RetrieverTrace.id))
        .filter(RetrieverTrace.num_documents > 0)
        .scalar()
        or 0
    )

    return {
        "total_retrievals": total_retrievals,
        "average_similarity": round(float(avg_similarity), 4),
        "average_documents_retrieved": round(float(avg_docs_retrieved), 2),
        "average_documents_used": round(selected_docs / total_retrievals, 2),
        "average_embedding_latency": round(float(avg_embedding_latency), 2),
        "average_retrieval_latency": round(float(avg_retrieval_latency), 2),
        "average_prompt_size": round(float(avg_prompt_size), 2),
        "total_embedding_cost": round(float(total_embedding_cost), 8),
        "success_rate": round(successful / total_retrievals * 100, 2),
    }
