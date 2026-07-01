"""Serializers for the agent execution tracing models.

These are pure functions (no DB access) that turn ORM instances into
JSON-serializable dictionaries. They are reused across list, detail and
per-request endpoints so response shapes stay consistent.
"""
from ..models.agent_trace import (
    AgentRun,
    AgentStep,
    ToolExecution,
    MemoryAccess,
    RetrieverTrace,
)
from .common import iso as _iso


def serialize_tool(tool: ToolExecution) -> dict:
    """Serialize a tool/function execution."""
    return {
        "id": tool.id,
        "step_id": tool.step_id,
        "tool_name": tool.tool_name,
        "arguments": tool.arguments,
        "result": tool.result,
        "status": tool.status,
        "latency_ms": tool.latency_ms,
        "error_message": tool.error_message,
        "created_at": _iso(tool.created_at),
    }


def serialize_memory(memory: MemoryAccess) -> dict:
    """Serialize a memory read/lookup record."""
    return {
        "id": memory.id,
        "step_id": memory.step_id,
        "memory_type": memory.memory_type,
        "query": memory.query,
        "retrieved_text": memory.retrieved_text,
        "similarity_score": memory.similarity_score,
        "used": memory.used,
        "latency_ms": memory.latency_ms,
    }


def serialize_retriever(retriever: RetrieverTrace) -> dict:
    """Serialize a retrieval (RAG) trace record."""
    return {
        "id": retriever.id,
        "step_id": retriever.step_id,
        "query": retriever.query,
        "retrieved_documents": retriever.retrieved_documents,
        "embedding_time_ms": retriever.embedding_time_ms,
        "retrieval_time_ms": retriever.retrieval_time_ms,
        "num_documents": retriever.num_documents,
    }


def serialize_step(step: AgentStep) -> dict:
    """Serialize a step with its nested tool/memory/retriever records."""
    return {
        "id": step.id,
        "agent_run_id": step.agent_run_id,
        "step_number": step.step_number,
        "step_type": step.step_type,
        "name": step.name,
        "input": step.input,
        "output": step.output,
        "status": step.status,
        "latency_ms": step.latency_ms,
        "token_usage": step.token_usage,
        "cost": step.cost,
        "started_at": _iso(step.started_at),
        "finished_at": _iso(step.finished_at),
        "metadata": step.step_metadata,
        "tool_executions": [serialize_tool(t) for t in step.tool_executions],
        "memory_accesses": [serialize_memory(m) for m in step.memory_accesses],
        "retriever_traces": [serialize_retriever(r) for r in step.retriever_traces],
    }


def serialize_run_summary(run: AgentRun) -> dict:
    """Lightweight run representation for list endpoints."""
    return {
        "id": run.id,
        "request_id": run.request_id,
        "parent_run_id": run.parent_run_id,
        "agent_name": run.agent_name,
        "agent_type": run.agent_type,
        "status": run.status,
        "start_time": _iso(run.start_time),
        "end_time": _iso(run.end_time),
        "latency_ms": run.latency_ms,
        "metadata": run.run_metadata,
        "created_at": _iso(run.created_at),
        "step_count": len(run.steps),
    }


def build_timeline(run: AgentRun) -> list[dict]:
    """Build an ordered event timeline for a run.

    Events follow the logical execution order (steps by ``step_number``, then
    the tool/memory/retriever records attached to each step). Any available
    timestamp and latency is included; sub-records without their own timestamp
    are ordered relative to their parent step.
    """
    timeline: list[dict] = []
    for step in run.steps:
        timeline.append(
            {
                "type": "step",
                "step_id": step.id,
                "step_number": step.step_number,
                "label": step.name or step.step_type,
                "status": step.status,
                "timestamp": _iso(step.started_at),
                "finished_at": _iso(step.finished_at),
                "latency_ms": step.latency_ms,
            }
        )
        for tool in step.tool_executions:
            timeline.append(
                {
                    "type": "tool",
                    "step_id": step.id,
                    "label": tool.tool_name,
                    "status": tool.status,
                    "timestamp": _iso(tool.created_at),
                    "latency_ms": tool.latency_ms,
                }
            )
        for memory in step.memory_accesses:
            timeline.append(
                {
                    "type": "memory",
                    "step_id": step.id,
                    "label": memory.memory_type,
                    "status": None,
                    "timestamp": None,
                    "latency_ms": memory.latency_ms,
                }
            )
        for retriever in step.retriever_traces:
            timeline.append(
                {
                    "type": "retriever",
                    "step_id": step.id,
                    "label": (
                        f"{retriever.num_documents} documents"
                        if retriever.num_documents is not None
                        else "retrieval"
                    ),
                    "status": None,
                    "timestamp": None,
                    "latency_ms": retriever.retrieval_time_ms,
                }
            )
    return timeline


def serialize_run_detail(run: AgentRun) -> dict:
    """Full run representation: general info, steps, flattened sub-records, timeline."""
    steps = list(run.steps)
    tools = [t for step in steps for t in step.tool_executions]
    memory = [m for step in steps for m in step.memory_accesses]
    retrievers = [r for step in steps for r in step.retriever_traces]

    detail = serialize_run_summary(run)
    detail.update(
        {
            "steps": [serialize_step(step) for step in steps],
            "tool_executions": [serialize_tool(t) for t in tools],
            "memory_accesses": [serialize_memory(m) for m in memory],
            "retriever_traces": [serialize_retriever(r) for r in retrievers],
            "timeline": build_timeline(run),
        }
    )
    return detail
