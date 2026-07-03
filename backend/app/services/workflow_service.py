"""Business logic and persistence for multi-agent workflows (v0.4).

All SQLAlchemy session handling for the workflow-orchestration models lives here
so the Multi-Agent SDK (:mod:`app.orchestration`) can stay a thin, lightweight
layer that only orchestrates and never touches the session directly.
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models.agent_trace import AgentRun, AgentStatus, AgentStep
from ..models.workflow_trace import (
    AgentMessage,
    AgentNode,
    ConversationRun,
    WorkflowDefinition,
    WorkflowExecution,
)
from ..streaming import EventType, emit
from ..utils.sorting import apply_sort, is_valid_sort
from ..utils.timeutils import utcnow
from ..utils.validation import ensure_json_object

logger = logging.getLogger("agentscope")


# -- Conversation runs ------------------------------------------------------


def create_conversation_run(
    request_trace_id: int,
    conversation_name: Optional[str] = None,
    status: str = AgentStatus.RUNNING,
    started_at: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> ConversationRun:
    """Persist a new conversation run and return it (committed)."""
    conversation = ConversationRun(
        request_trace_id=request_trace_id,
        conversation_name=conversation_name,
        status=status,
        started_at=started_at or utcnow(),
        conversation_metadata=ensure_json_object(metadata, "metadata"),
    )
    db.session.add(conversation)
    db.session.commit()
    logger.debug(
        "Started conversation run id=%s name=%s request_trace_id=%s",
        conversation.id, conversation_name, request_trace_id,
    )
    emit(
        EventType.WORKFLOW_UPDATED,
        conversation_run_id=conversation.id, conversation_name=conversation_name,
        request_trace_id=request_trace_id, status=conversation.status, phase="started",
    )
    return conversation


def finish_conversation_run(
    conversation: ConversationRun,
    status: str = AgentStatus.SUCCESS,
    finished_at: Optional[datetime] = None,
    latency_ms: Optional[float] = None,
    metadata: Optional[dict] = None,
) -> ConversationRun:
    """Mark a conversation run finished, recording end time, latency and status."""
    conversation.finished_at = finished_at or utcnow()
    conversation.status = status
    if latency_ms is not None:
        conversation.latency_ms = latency_ms
    if metadata is not None:
        conversation.conversation_metadata = ensure_json_object(metadata, "metadata")
    db.session.commit()
    logger.debug(
        "Finished conversation run id=%s status=%s latency_ms=%s",
        conversation.id, status, conversation.latency_ms,
    )
    emit(
        EventType.WORKFLOW_UPDATED,
        conversation_run_id=conversation.id, status=conversation.status,
        latency_ms=conversation.latency_ms, phase="finished",
    )
    return conversation


# -- Agent nodes ------------------------------------------------------------


def create_agent_node(
    conversation_run_id: int,
    agent_run_id: Optional[int] = None,
    agent_role: Optional[str] = None,
    display_name: Optional[str] = None,
    parent_node_id: Optional[int] = None,
    execution_order: Optional[int] = None,
    parallel_group: Optional[str] = None,
    status: str = AgentStatus.PENDING,
    metadata: Optional[dict] = None,
) -> AgentNode:
    """Persist a new agent node within a conversation and return it (committed)."""
    node = AgentNode(
        conversation_run_id=conversation_run_id,
        agent_run_id=agent_run_id,
        agent_role=agent_role,
        display_name=display_name,
        parent_node_id=parent_node_id,
        execution_order=execution_order,
        parallel_group=parallel_group,
        status=status,
        node_metadata=ensure_json_object(metadata, "metadata"),
    )
    db.session.add(node)
    db.session.commit()
    logger.debug(
        "Created agent node id=%s role=%s conversation_run_id=%s parent=%s",
        node.id, agent_role, conversation_run_id, parent_node_id,
    )
    return node


def update_agent_node(
    node: AgentNode,
    status: Optional[str] = None,
    agent_run_id: Optional[int] = None,
    parallel_group: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> AgentNode:
    """Update mutable fields on an agent node (status, run link, group, metadata)."""
    if status is not None:
        node.status = status
    if agent_run_id is not None:
        node.agent_run_id = agent_run_id
    if parallel_group is not None:
        node.parallel_group = parallel_group
    if metadata is not None:
        node.node_metadata = ensure_json_object(metadata, "metadata")
    db.session.commit()
    return node


# -- Agent messages ---------------------------------------------------------


def create_agent_message(
    sender_node_id: int,
    receiver_node_id: Optional[int] = None,
    message_type: Optional[str] = None,
    content: Optional[str] = None,
    token_usage: Optional[dict] = None,
    latency_ms: Optional[float] = None,
    metadata: Optional[dict] = None,
    conversation_run_id: Optional[int] = None,
    reply_to_id: Optional[int] = None,
) -> AgentMessage:
    """Persist a message between agent nodes and return it (committed)."""
    message = AgentMessage(
        conversation_run_id=conversation_run_id,
        sender_node_id=sender_node_id,
        receiver_node_id=receiver_node_id,
        reply_to_id=reply_to_id,
        message_type=message_type,
        content=content,
        token_usage=ensure_json_object(token_usage, "token_usage"),
        latency_ms=latency_ms,
        message_metadata=ensure_json_object(metadata, "metadata"),
    )
    db.session.add(message)
    db.session.commit()
    logger.debug(
        "Recorded agent message id=%s type=%s sender=%s receiver=%s reply_to=%s",
        message.id, message_type, sender_node_id, receiver_node_id, reply_to_id,
    )
    return message


# -- Workflow definitions / executions --------------------------------------


def create_workflow_definition(
    workflow_name: str,
    description: Optional[str] = None,
    version: Optional[str] = None,
    workflow_json: Optional[dict] = None,
) -> WorkflowDefinition:
    """Persist a reusable workflow definition and return it (committed)."""
    definition = WorkflowDefinition(
        workflow_name=workflow_name,
        description=description,
        version=version,
        workflow_json=ensure_json_object(workflow_json, "workflow_json"),
    )
    db.session.add(definition)
    db.session.commit()
    logger.debug(
        "Created workflow definition id=%s name=%s version=%s",
        definition.id, workflow_name, version,
    )
    return definition


def get_workflow_definition(definition_id: int) -> Optional[WorkflowDefinition]:
    """Return a workflow definition by id, or None."""
    return db.session.get(WorkflowDefinition, definition_id)


def create_workflow_execution(
    workflow_definition_id: int,
    conversation_run_id: Optional[int] = None,
    status: str = AgentStatus.RUNNING,
    started_at: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> WorkflowExecution:
    """Persist a workflow execution and return it (committed)."""
    execution = WorkflowExecution(
        workflow_definition_id=workflow_definition_id,
        conversation_run_id=conversation_run_id,
        status=status,
        started_at=started_at or utcnow(),
        execution_metadata=ensure_json_object(metadata, "metadata"),
    )
    db.session.add(execution)
    db.session.commit()
    logger.debug(
        "Started workflow execution id=%s definition_id=%s conversation_run_id=%s",
        execution.id, workflow_definition_id, conversation_run_id,
    )
    return execution


def finish_workflow_execution(
    execution: WorkflowExecution,
    status: str = AgentStatus.SUCCESS,
    finished_at: Optional[datetime] = None,
    latency_ms: Optional[float] = None,
    metadata: Optional[dict] = None,
) -> WorkflowExecution:
    """Mark a workflow execution finished, recording end time, latency and status."""
    execution.finished_at = finished_at or utcnow()
    execution.status = status
    if latency_ms is not None:
        execution.latency_ms = latency_ms
    if metadata is not None:
        execution.execution_metadata = ensure_json_object(metadata, "metadata")
    db.session.commit()
    logger.debug(
        "Finished workflow execution id=%s status=%s latency_ms=%s",
        execution.id, status, execution.latency_ms,
    )
    emit(
        EventType.WORKFLOW_UPDATED,
        workflow_execution_id=execution.id, conversation_run_id=execution.conversation_run_id,
        status=execution.status, latency_ms=execution.latency_ms, phase="execution_finished",
    )
    return execution


# -- Read / query layer (v0.4 REST API) -------------------------------------

WORKFLOW_SORTABLE = {"created_at", "updated_at", "workflow_name", "version"}
_WORKFLOW_SORT_COLUMNS = {name: getattr(WorkflowDefinition, name) for name in WORKFLOW_SORTABLE}

CONVERSATION_SORTABLE = {
    "created_at",
    "started_at",
    "finished_at",
    "latency_ms",
    "status",
    "conversation_name",
}
_CONVERSATION_SORT_COLUMNS = {
    name: getattr(ConversationRun, name) for name in CONVERSATION_SORTABLE
}


def is_valid_workflow_sort(sort: str) -> bool:
    """Return True if ``sort`` targets an allowed workflow field."""
    return is_valid_sort(sort, WORKFLOW_SORTABLE)


def is_valid_conversation_sort(sort: str) -> bool:
    """Return True if ``sort`` targets an allowed conversation field."""
    return is_valid_sort(sort, CONVERSATION_SORTABLE)


def list_workflows(
    page: int = 1,
    limit: int = 20,
    q: Optional[str] = None,
    sort: str = "-created_at",
) -> tuple[list[WorkflowDefinition], int]:
    """Return a page of workflow definitions and the total matching count."""
    query = WorkflowDefinition.query.options(selectinload(WorkflowDefinition.executions))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                WorkflowDefinition.workflow_name.ilike(like),
                WorkflowDefinition.description.ilike(like),
                WorkflowDefinition.version.ilike(like),
                cast(WorkflowDefinition.id, String).ilike(like),
            )
        )
    total = query.count()
    query = apply_sort(query, sort, _WORKFLOW_SORT_COLUMNS)
    items = query.limit(limit).offset((page - 1) * limit).all()
    return items, total


def get_workflow(definition_id: int) -> Optional[WorkflowDefinition]:
    """Return a workflow definition with its execution history, or None."""
    return (
        db.session.query(WorkflowDefinition)
        .options(selectinload(WorkflowDefinition.executions))
        .filter(WorkflowDefinition.id == definition_id)
        .one_or_none()
    )


def list_conversations(
    page: int = 1,
    limit: int = 20,
    q: Optional[str] = None,
    status: Optional[str] = None,
    sort: str = "-created_at",
) -> tuple[list[ConversationRun], int]:
    """Return a page of conversation runs and the total matching count."""
    query = ConversationRun.query.options(
        selectinload(ConversationRun.nodes),
        selectinload(ConversationRun.messages),
    )
    if status is not None:
        query = query.filter(ConversationRun.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                ConversationRun.conversation_name.ilike(like),
                ConversationRun.status.ilike(like),
                cast(ConversationRun.id, String).ilike(like),
                cast(ConversationRun.request_trace_id, String).ilike(like),
            )
        )
    total = query.count()
    query = apply_sort(query, sort, _CONVERSATION_SORT_COLUMNS)
    items = query.limit(limit).offset((page - 1) * limit).all()
    return items, total


def get_conversation(conversation_id: int) -> Optional[ConversationRun]:
    """Return a conversation eager-loaded with its agent tree, runs/steps and messages."""
    return (
        db.session.query(ConversationRun)
        .options(
            selectinload(ConversationRun.nodes)
            .selectinload(AgentNode.agent_run)
            .selectinload(AgentRun.steps),
            selectinload(ConversationRun.messages).selectinload(AgentMessage.sender),
            selectinload(ConversationRun.messages).selectinload(AgentMessage.receiver),
            selectinload(ConversationRun.workflow_execution),
        )
        .filter(ConversationRun.id == conversation_id)
        .one_or_none()
    )


def get_workflow_metrics() -> dict:
    """Compute aggregate multi-agent workflow metrics for the dashboard.

    The unit of a "workflow" here is a :class:`ConversationRun` (one run of a
    multi-agent workflow). ``total_agents`` counts agent nodes; cost is summed
    from the underlying agent-run steps.
    """
    total_workflows = db.session.query(func.count(ConversationRun.id)).scalar() or 0
    total_agents = db.session.query(func.count(AgentNode.id)).scalar() or 0

    if total_workflows == 0:
        return {
            "total_workflows": 0,
            "total_agents": total_agents,
            "average_agents_per_workflow": 0,
            "average_messages": 0,
            "average_parallel_branches": 0,
            "average_latency": 0,
            "average_cost": 0,
            "success_rate": 0,
        }

    total_messages = db.session.query(func.count(AgentMessage.id)).scalar() or 0

    # Parallel branches: average size of a parallel group (nodes sharing one
    # non-null parallel_group), i.e. total grouped nodes / distinct groups.
    grouped_nodes = (
        db.session.query(func.count(AgentNode.id))
        .filter(AgentNode.parallel_group.isnot(None))
        .scalar()
        or 0
    )
    distinct_groups = (
        db.session.query(func.count(func.distinct(AgentNode.parallel_group)))
        .filter(AgentNode.parallel_group.isnot(None))
        .scalar()
        or 0
    )

    avg_latency = db.session.query(func.avg(ConversationRun.latency_ms)).scalar() or 0
    total_cost = (
        db.session.query(func.coalesce(func.sum(AgentStep.cost), 0.0)).scalar() or 0
    )
    success_workflows = (
        db.session.query(func.count(ConversationRun.id))
        .filter(ConversationRun.status == AgentStatus.SUCCESS)
        .scalar()
        or 0
    )

    return {
        "total_workflows": total_workflows,
        "total_agents": total_agents,
        "average_agents_per_workflow": round(total_agents / total_workflows, 2),
        "average_messages": round(total_messages / total_workflows, 2),
        "average_parallel_branches": (
            round(grouped_nodes / distinct_groups, 2) if distinct_groups else 0
        ),
        "average_latency": round(float(avg_latency), 2),
        "average_cost": round(float(total_cost) / total_workflows, 6),
        "success_rate": round(success_workflows / total_workflows * 100, 2),
    }
