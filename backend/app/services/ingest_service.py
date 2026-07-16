"""HTTP ingestion of full agent runs and standalone retrievals.

These power ``POST /api/agent-runs`` and ``POST /api/retrievals`` so external
applications (e.g. a chatbot service) can populate the **Agent Runs** and **RAG
Observatory** views, not just the flat request-trace list. Previously the only
public write endpoint was ``POST /api/traces``, which stores a single flat
request trace; the structured agent/step/retrieval hierarchy could only be
built in-process by :class:`~app.utils.trace_recorder.TraceRecorder`.

This module only validates and orchestrates: all persistence is delegated to
:mod:`app.services.trace_service`, reusing the exact create/finish functions the
in-process recorder uses, so the ingested data is identical in shape to
natively recorded data.

Auth note: these endpoints are intentionally open, matching ``POST /api/traces``
so the integration works with no extra config. To require API-key auth later,
gate the two routes with the existing ``app.auth`` layer — no change to this
module is needed.
"""
import json
from typing import Any, Optional

from ..extensions import db
from ..models.agent_trace import AgentStatus
from ..utils.timeutils import utcnow
from ..utils.unit_of_work import deferred_commits
from ..utils.validation import ValidationError
from . import trace_service

# All status values accepted on ingested runs/steps/tools.
_ALLOWED_STATUS = {
    AgentStatus.PENDING,
    AgentStatus.RUNNING,
    AgentStatus.SUCCESS,
    AgentStatus.FAILED,
    AgentStatus.CANCELLED,
    AgentStatus.TIMEOUT,
}

# Fields forwarded verbatim to ``create_prompt_assembly``.
_PROMPT_ASSEMBLY_FIELDS = (
    "system_prompt",
    "conversation_context",
    "retrieved_context",
    "memory_context",
    "user_prompt",
    "assembled_prompt",
    "system_tokens",
    "conversation_tokens",
    "retrieval_tokens",
    "memory_tokens",
    "user_tokens",
    "total_tokens",
)


def ingest_agent_run(data: dict):
    """Create a full agent run (with steps, tools, memory, retrievals) from a payload.

    Links to an existing request trace via ``request_id`` when provided; otherwise
    a minimal parent request trace is created from the top-level fields so the run
    always has a parent. Returns the persisted, eagerly-loaded run.
    """
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")

    agent_name = data.get("agent_name")
    if not agent_name or not str(agent_name).strip():
        raise ValidationError("agent_name is required")

    _validate_status(data.get("status"), "status")

    steps = data.get("steps")
    if steps is None:
        steps = []
    elif not isinstance(steps, list):
        raise ValidationError("steps must be a list")

    parent_run_id = data.get("parent_run_id")
    if parent_run_id is not None:
        if not isinstance(parent_run_id, int) or trace_service.get_agent_run(parent_run_id) is None:
            raise ValidationError("parent_run_id must reference an existing agent run")

    # Persist the whole nested payload as ONE transaction: child creators flush
    # (assigning ids) instead of committing, and we commit once at the end. This
    # avoids a commit-per-row "transaction storm" (which exhausts the connection
    # pool) and makes ingestion atomic — a failure part-way through rolls the
    # entire run back rather than leaving orphaned partial rows.
    try:
        with deferred_commits():
            request_id = _resolve_request_id(data)
            run = trace_service.create_agent_run(
                request_id=request_id,
                agent_name=str(agent_name),
                agent_type=data.get("agent_type"),
                parent_run_id=parent_run_id,
                status=AgentStatus.RUNNING,
                start_time=utcnow(),
                metadata=data.get("metadata"),
            )
            run_id = run.id

            for index, step_data in enumerate(steps, start=1):
                _ingest_step(run_id, index, step_data)

            prompt_assembly = data.get("prompt_assembly")
            if isinstance(prompt_assembly, dict):
                trace_service.create_prompt_assembly(
                    run_id, **{k: prompt_assembly.get(k) for k in _PROMPT_ASSEMBLY_FIELDS}
                )

            trace_service.finish_agent_run(
                run,
                status=data.get("status", AgentStatus.SUCCESS),
                latency_ms=_as_number(data.get("latency_ms"), "latency_ms"),
            )
            org_id = run.organization_id
        db.session.commit()
        # Per-row invalidation is skipped inside the deferred batch; do it once
        # here now that the whole run is durably committed.
        trace_service.invalidate_metrics_cache(org_id)
    except Exception:
        db.session.rollback()
        raise

    # Re-fetch with the detail eager-loaders so serialization avoids N+1 queries.
    return trace_service.get_agent_run(run_id)


def ingest_retrieval(data: dict):
    """Ingest a single retrieval, wrapping it in a minimal run+step.

    RAG Observatory lists ``RetrieverTrace`` rows, which live under an agent step,
    which lives under a run tied to a request trace. To let a caller log just a
    retrieval, we transparently create that thin wrapper so the retrieval shows up
    in the RAG Observatory. Returns the persisted, eagerly-loaded retrieval.
    """
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")

    # One atomic transaction for the run + step + retrieval + documents (see
    # ingest_agent_run for why: no per-row commit storm, all-or-nothing).
    try:
        with deferred_commits():
            request_id = _resolve_request_id(data)
            run = trace_service.create_agent_run(
                request_id=request_id,
                agent_name=data.get("agent_name") or "Retriever",
                agent_type=data.get("agent_type") or "retriever",
                status=AgentStatus.RUNNING,
                start_time=utcnow(),
                metadata=data.get("metadata"),
            )
            step = trace_service.create_agent_step(
                agent_run_id=run.id,
                step_number=1,
                step_type="retrieval",
                name="Retriever",
                input=data.get("query"),
                status=AgentStatus.RUNNING,
                started_at=utcnow(),
            )

            retriever = _ingest_retrieval_into_step(step.id, data)
            retriever_id = retriever.id

            trace_service.finish_agent_step(
                step,
                status=AgentStatus.SUCCESS,
                latency_ms=_as_number(data.get("retrieval_time_ms"), "retrieval_time_ms"),
            )
            trace_service.finish_agent_run(run, status=AgentStatus.SUCCESS)
            org_id = run.organization_id
        db.session.commit()
        # Per-row invalidation is skipped inside the deferred batch; do it once
        # here now that the whole retrieval is durably committed.
        trace_service.invalidate_metrics_cache(org_id)
    except Exception:
        db.session.rollback()
        raise

    return trace_service.get_retrieval(retriever_id)


# -- internals -------------------------------------------------------------


def _resolve_request_id(data: dict) -> int:
    """Return an existing ``request_id`` or create a minimal parent request trace."""
    request_id = data.get("request_id")
    if request_id is not None:
        if not isinstance(request_id, int) or isinstance(request_id, bool):
            raise ValidationError("request_id must be an integer")
        if trace_service.get_trace(request_id) is None:
            raise ValidationError(f"request_id {request_id} does not reference an existing trace")
        return request_id

    status = data.get("status", AgentStatus.SUCCESS)
    trace = trace_service.create_trace(
        {
            "user_prompt": data.get("user_prompt"),
            "system_prompt": data.get("system_prompt"),
            "model_name": data.get("model_name") or "unknown",
            "final_response": data.get("final_response"),
            "input_tokens": data.get("input_tokens"),
            "output_tokens": data.get("output_tokens"),
            "total_tokens": data.get("total_tokens"),
            "estimated_cost": data.get("estimated_cost"),
            "latency_ms": data.get("latency_ms"),
            "status": "failed" if status == AgentStatus.FAILED else "success",
        }
    )
    return trace.id


def _ingest_step(agent_run_id: int, index: int, step_data: Any):
    if not isinstance(step_data, dict):
        raise ValidationError("each step must be a JSON object")

    _validate_status(step_data.get("status"), "step status")

    step = trace_service.create_agent_step(
        agent_run_id=agent_run_id,
        step_number=step_data.get("step_number", index),
        step_type=step_data.get("step_type"),
        name=step_data.get("name"),
        input=step_data.get("input"),
        status=AgentStatus.RUNNING,
        started_at=utcnow(),
        metadata=step_data.get("metadata"),
    )

    for tool in _as_list(step_data.get("tool_calls") or step_data.get("tool_executions"), "tool_calls"):
        if not isinstance(tool, dict) or not tool.get("tool_name"):
            raise ValidationError("each tool call needs a 'tool_name'")
        _validate_status(tool.get("status"), "tool status")
        trace_service.create_tool_execution(
            step_id=step.id,
            tool_name=tool["tool_name"],
            arguments=tool.get("arguments"),
            result=_stringify(tool.get("result")),
            status=tool.get("status", AgentStatus.SUCCESS),
            latency_ms=_as_number(tool.get("latency_ms"), "tool latency_ms"),
            error_message=tool.get("error_message"),
        )

    for memory in _as_list(step_data.get("memory_accesses"), "memory_accesses"):
        if not isinstance(memory, dict):
            raise ValidationError("each memory access must be a JSON object")
        trace_service.create_memory_access(
            step_id=step.id,
            memory_type=memory.get("memory_type"),
            query=memory.get("query"),
            retrieved_text=memory.get("retrieved_text"),
            similarity_score=_as_number(memory.get("similarity_score"), "similarity_score"),
            used=memory.get("used"),
            latency_ms=_as_number(memory.get("latency_ms"), "memory latency_ms"),
        )

    for retrieval in _as_list(step_data.get("retrievals"), "retrievals"):
        if not isinstance(retrieval, dict):
            raise ValidationError("each retrieval must be a JSON object")
        _ingest_retrieval_into_step(step.id, retrieval)

    trace_service.finish_agent_step(
        step,
        status=step_data.get("status", AgentStatus.SUCCESS),
        output=step_data.get("output"),
        token_usage=step_data.get("token_usage"),
        cost=_as_number(step_data.get("cost"), "cost"),
        latency_ms=_as_number(step_data.get("latency_ms"), "step latency_ms"),
    )
    return step


def _ingest_retrieval_into_step(step_id: int, retrieval: dict):
    """Create a RetrieverTrace on ``step_id`` plus its documents and embedding."""
    documents = _as_list(retrieval.get("documents"), "documents")

    # ``num_documents`` reflects however many documents were surfaced: an explicit
    # count wins, else the JSON summary list, else the rich document rows.
    num_documents = retrieval.get("num_documents")
    if num_documents is None and documents:
        num_documents = len(documents)

    retriever = trace_service.create_retriever_trace(
        step_id=step_id,
        query=retrieval.get("query"),
        retrieved_documents=retrieval.get("retrieved_documents"),
        embedding_time_ms=_as_number(retrieval.get("embedding_time_ms"), "embedding_time_ms"),
        retrieval_time_ms=_as_number(retrieval.get("retrieval_time_ms"), "retrieval_time_ms"),
        num_documents=num_documents,
    )

    for i, doc in enumerate(documents):
        if not isinstance(doc, dict):
            raise ValidationError("each document must be a JSON object")
        trace_service.create_retrieved_document(
            retriever.id,
            document_id=doc.get("document_id"),
            document_name=doc.get("document_name") or doc.get("title"),
            document_source=doc.get("document_source") or doc.get("source"),
            chunk_index=doc.get("chunk_index", i),
            chunk_text=doc.get("chunk_text") or doc.get("snippet"),
            similarity_score=_as_number(doc.get("similarity_score", doc.get("score")), "similarity_score"),
            selected=bool(doc.get("selected", False)),
            metadata=doc.get("metadata"),
        )

    embedding = retrieval.get("embedding")
    if isinstance(embedding, dict):
        trace_service.create_embedding_trace(
            retriever.id,
            embedding_model=embedding.get("embedding_model") or embedding.get("model"),
            embedding_dimension=embedding.get("embedding_dimension") or embedding.get("dimension"),
            input_tokens=embedding.get("input_tokens"),
            input_text=embedding.get("input") or embedding.get("input_text"),
            latency_ms=_as_number(embedding.get("latency_ms"), "embedding latency_ms"),
            cost=_as_number(embedding.get("cost"), "embedding cost"),
            metadata=embedding.get("metadata"),
        )
    return retriever


def _validate_status(value: Optional[str], field: str) -> None:
    if value is not None and value not in _ALLOWED_STATUS:
        raise ValidationError(
            f"invalid {field}: {value!r}; allowed: {sorted(_ALLOWED_STATUS)}"
        )


def _as_list(value: Any, field: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list")
    return value


def _as_number(value: Any, field: str) -> Optional[float]:
    # bool is a subclass of int; treat it as "not a number" and ignore it.
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    raise ValidationError(f"{field} must be a number")


def _stringify(value: Any) -> Optional[str]:
    """Coerce a tool result to text for the string column (JSON for structures)."""
    if value is None or isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)
