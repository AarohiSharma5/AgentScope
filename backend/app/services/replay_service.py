"""Business logic and persistence for replay & evaluation (v0.5).

All SQLAlchemy session handling for the replay models lives here so the
:class:`~app.orchestration.replay_engine.ReplayEngine` can stay a thin control
layer that only orchestrates re-execution and never touches the session
directly.

Responsibilities:

* CRUD for :class:`~app.models.evaluation_trace.ReplayRun` and
  :class:`~app.models.evaluation_trace.ModelComparison`.
* Reconstructing a portable *snapshot* of a traced conversation (its workflow,
  agent sequence, prompts, memory, retrieved documents and tool calls) that the
  engine replays.
* Aggregating a conversation's cost / token / latency totals for comparison.
"""
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import or_

from ..extensions import db
from ..models.agent_trace import AgentStatus, AgentStep
from ..models.evaluation_trace import ModelComparison, ReplayRun
from ..models.workflow_trace import AgentNode, ConversationRun
from ..services import workflow_service
from ..utils.sorting import apply_sort, is_valid_sort
from ..utils.timeutils import utcnow
from ..utils.validation import ensure_json_object

logger = logging.getLogger("agentscope")


# -- ReplayRun --------------------------------------------------------------


def create_replay_run(
    original_conversation_run_id: int,
    replayed_model: Optional[str] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    system_prompt_override: Optional[str] = None,
    status: str = AgentStatus.RUNNING,
    started_at: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> ReplayRun:
    """Persist a new replay run (committed) and return it."""
    replay = ReplayRun(
        original_conversation_run_id=original_conversation_run_id,
        replayed_model=replayed_model,
        temperature=temperature,
        top_p=top_p,
        system_prompt_override=system_prompt_override,
        status=status,
        started_at=started_at or utcnow(),
        replay_metadata=ensure_json_object(metadata, "metadata"),
    )
    db.session.add(replay)
    db.session.commit()
    logger.debug(
        "Started replay run id=%s original_conversation_run_id=%s model=%s",
        replay.id, original_conversation_run_id, replayed_model,
    )
    return replay


def finish_replay_run(
    replay: ReplayRun,
    status: str = AgentStatus.SUCCESS,
    latency_ms: Optional[float] = None,
    cost: Optional[float] = None,
    finished_at: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> ReplayRun:
    """Finish a replay run, recording status, latency and cost (committed).

    ``metadata`` is merged into any existing metadata rather than replacing it.
    """
    replay.status = status
    replay.finished_at = finished_at or utcnow()
    if latency_ms is not None:
        replay.latency_ms = latency_ms
    if cost is not None:
        replay.cost = cost
    if metadata:
        merged = dict(replay.replay_metadata or {})
        merged.update(metadata)
        replay.replay_metadata = ensure_json_object(merged, "metadata")
    db.session.commit()
    logger.debug("Finished replay run id=%s status=%s cost=%s", replay.id, status, cost)
    return replay


def get_replay_run(replay_run_id: int) -> Optional[ReplayRun]:
    """Return a replay run by id, or None."""
    return db.session.get(ReplayRun, replay_run_id)


REPLAY_SORTABLE = {"created_at", "started_at", "finished_at", "latency_ms", "cost", "status"}
_REPLAY_SORT_COLUMNS = {name: getattr(ReplayRun, name) for name in REPLAY_SORTABLE}


def is_valid_replay_sort(sort: str) -> bool:
    """Return True if ``sort`` targets an allowed replay field."""
    return is_valid_sort(sort, REPLAY_SORTABLE)


def list_replay_runs(
    page: int = 1,
    limit: int = 20,
    original_conversation_run_id: Optional[int] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = "-created_at",
) -> tuple[list[ReplayRun], int]:
    """Return a page of replay runs and the total matching count.

    ``q`` performs a case-insensitive search on the replayed model name.
    """
    query = ReplayRun.query
    if original_conversation_run_id is not None:
        query = query.filter(
            ReplayRun.original_conversation_run_id == original_conversation_run_id
        )
    if status is not None:
        query = query.filter(ReplayRun.status == status)
    if q:
        query = query.filter(ReplayRun.replayed_model.ilike(f"%{q}%"))
    total = query.count()
    query = apply_sort(query, sort, _REPLAY_SORT_COLUMNS)
    items = query.limit(limit).offset((page - 1) * limit).all()
    return items, total


# -- ModelComparison --------------------------------------------------------


def create_model_comparison(
    conversation_run_id: int,
    model_a: Optional[str] = None,
    model_b: Optional[str] = None,
    winner: Optional[str] = None,
    reason: Optional[str] = None,
    cost_difference: Optional[float] = None,
    latency_difference: Optional[float] = None,
    token_difference: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> ModelComparison:
    """Persist a model comparison (committed) and return it."""
    comparison = ModelComparison(
        conversation_run_id=conversation_run_id,
        model_a=model_a,
        model_b=model_b,
        winner=winner,
        reason=reason,
        cost_difference=cost_difference,
        latency_difference=latency_difference,
        token_difference=token_difference,
        comparison_metadata=ensure_json_object(metadata, "metadata"),
    )
    db.session.add(comparison)
    db.session.commit()
    logger.debug(
        "Recorded model comparison id=%s a=%s b=%s winner=%s",
        comparison.id, model_a, model_b, winner,
    )
    return comparison


def get_model_comparison(comparison_id: int) -> Optional[ModelComparison]:
    """Return a model comparison by id, or None."""
    return db.session.get(ModelComparison, comparison_id)


def list_model_comparisons(
    conversation_run_id: Optional[int] = None,
) -> list[ModelComparison]:
    """Return model comparisons, optionally scoped to one conversation."""
    query = ModelComparison.query
    if conversation_run_id is not None:
        query = query.filter(ModelComparison.conversation_run_id == conversation_run_id)
    return query.order_by(ModelComparison.created_at.desc()).all()


COMPARISON_SORTABLE = {
    "created_at", "cost_difference", "latency_difference", "token_difference"
}
_COMPARISON_SORT_COLUMNS = {name: getattr(ModelComparison, name) for name in COMPARISON_SORTABLE}


def is_valid_comparison_sort(sort: str) -> bool:
    """Return True if ``sort`` targets an allowed comparison field."""
    return is_valid_sort(sort, COMPARISON_SORTABLE)


def list_comparisons(
    page: int = 1,
    limit: int = 20,
    conversation_run_id: Optional[int] = None,
    q: Optional[str] = None,
    sort: str = "-created_at",
) -> tuple[list[ModelComparison], int]:
    """Return a page of model comparisons and the total matching count.

    ``q`` performs a case-insensitive search across the two model names and the
    winner label.
    """
    query = ModelComparison.query
    if conversation_run_id is not None:
        query = query.filter(ModelComparison.conversation_run_id == conversation_run_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                ModelComparison.model_a.ilike(like),
                ModelComparison.model_b.ilike(like),
                ModelComparison.winner.ilike(like),
            )
        )
    total = query.count()
    query = apply_sort(query, sort, _COMPARISON_SORT_COLUMNS)
    items = query.limit(limit).offset((page - 1) * limit).all()
    return items, total


# -- Aggregation ------------------------------------------------------------


def conversation_totals(conversation_run_id: int) -> dict:
    """Aggregate cost, tokens and latency for one conversation.

    Cost is summed from the agent-run steps of the conversation's nodes; tokens
    are summed from each step's ``token_usage`` JSON (``total`` or
    ``input`` + ``output``); latency is the conversation's own wall-clock time.
    """
    conversation = db.session.get(ConversationRun, conversation_run_id)
    run_ids = [
        n.agent_run_id
        for n in AgentNode.query.filter_by(conversation_run_id=conversation_run_id).all()
        if n.agent_run_id is not None
    ]
    total_cost = 0.0
    total_tokens = 0
    if run_ids:
        steps = AgentStep.query.filter(AgentStep.agent_run_id.in_(run_ids)).all()
        for step in steps:
            total_cost += step.cost or 0.0
            usage = step.token_usage or {}
            total_tokens += usage.get("total") or (
                (usage.get("input") or 0) + (usage.get("output") or 0)
            )
    return {
        "cost": round(total_cost, 6),
        "total_tokens": total_tokens,
        "latency_ms": conversation.latency_ms if conversation else None,
    }


# -- Snapshot reconstruction ------------------------------------------------


def build_snapshot(conversation_run_id: int) -> Optional[dict]:
    """Reconstruct a portable snapshot of a traced conversation.

    The snapshot is a plain (ORM-free) dict the replay engine re-executes. It
    captures the workflow, the ordered agent sequence, and — per agent — the
    assembled prompt, steps, tool calls, memory accesses and retrieved
    documents, so a replay can faithfully reuse them.
    """
    conversation = workflow_service.get_conversation(conversation_run_id)
    if conversation is None:
        return None

    execution = conversation.workflow_execution
    definition = execution.workflow_definition if execution else None
    request = conversation.request

    nodes = [
        _node_snapshot(node)
        for node in sorted(
            conversation.nodes, key=lambda n: (n.execution_order or 0, n.id)
        )
    ]
    return {
        "conversation_run_id": conversation.id,
        "conversation_name": conversation.conversation_name,
        "request_model": request.model_name if request else None,
        "user_prompt": request.user_prompt if request else None,
        "system_prompt": request.system_prompt if request else None,
        "workflow_definition_id": definition.id if definition else None,
        "workflow_json": definition.workflow_json if definition else None,
        "nodes": nodes,
    }


def _node_snapshot(node: AgentNode) -> dict:
    """Snapshot a single agent node (its prompt, steps and sub-records)."""
    run = node.agent_run
    steps = list(run.steps) if run is not None else []
    return {
        "node_id": node.id,
        "role": node.agent_role,
        "name": node.display_name,
        "parent_node_id": node.parent_node_id,
        "parallel_group": node.parallel_group,
        "prompt": _prompt_snapshot(run.prompt_assembly) if run is not None else None,
        "steps": [_step_snapshot(step) for step in steps],
        "output": _node_output(steps),
    }


def _prompt_snapshot(assembly) -> Optional[dict]:
    """Snapshot a run's prompt assembly (or None)."""
    if assembly is None:
        return None
    return {
        "system_prompt": assembly.system_prompt,
        "conversation_context": assembly.conversation_context,
        "retrieved_context": assembly.retrieved_context,
        "memory_context": assembly.memory_context,
        "user_prompt": assembly.user_prompt,
        "assembled_prompt": assembly.assembled_prompt,
    }


def _step_snapshot(step: AgentStep) -> dict:
    """Snapshot a step with its tool / memory / retriever sub-records."""
    return {
        "step_type": step.step_type,
        "name": step.name,
        "input": step.input,
        "output": step.output,
        "token_usage": step.token_usage,
        "cost": step.cost,
        "tools": [
            {
                "tool_name": t.tool_name,
                "arguments": t.arguments,
                "result": t.result,
                "status": t.status,
                "latency_ms": t.latency_ms,
            }
            for t in step.tool_executions
        ],
        "memory": [
            {
                "memory_type": m.memory_type,
                "query": m.query,
                "retrieved_text": m.retrieved_text,
                "similarity_score": m.similarity_score,
                "used": m.used,
                "latency_ms": m.latency_ms,
            }
            for m in step.memory_accesses
        ],
        "retrievers": [
            {
                "query": r.query,
                "retrieved_documents": r.retrieved_documents,
                "embedding_time_ms": r.embedding_time_ms,
                "retrieval_time_ms": r.retrieval_time_ms,
                "num_documents": r.num_documents,
                "documents": [
                    {
                        "document_id": d.document_id,
                        "document_name": d.document_name,
                        "document_source": d.document_source,
                        "chunk_index": d.chunk_index,
                        "chunk_text": d.chunk_text,
                        "similarity_score": d.similarity_score,
                        "selected": d.selected,
                    }
                    for d in r.documents
                ],
            }
            for r in step.retriever_traces
        ],
    }


def _node_output(steps: list) -> Any:
    """The node's final output: the last step's output, if any."""
    for step in reversed(steps):
        if step.output is not None:
            return step.output
    return None
