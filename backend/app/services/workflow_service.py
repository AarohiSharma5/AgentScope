"""Business logic and persistence for multi-agent workflows (v0.4).

All SQLAlchemy session handling for the workflow-orchestration models lives here
so the Multi-Agent SDK (:mod:`app.orchestration`) can stay a thin, lightweight
layer that only orchestrates and never touches the session directly.
"""
import logging
from datetime import datetime
from typing import Optional

from ..extensions import db
from ..models.agent_trace import AgentStatus
from ..models.workflow_trace import (
    AgentMessage,
    AgentNode,
    ConversationRun,
    WorkflowDefinition,
    WorkflowExecution,
)
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
    return execution
