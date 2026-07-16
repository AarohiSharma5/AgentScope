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
from ..utils.cache import cached
from ..utils.sorting import apply_sort, is_valid_sort
from ..utils.timeutils import utcnow
from ..utils.validation import ensure_json_object

logger = logging.getLogger("agentscope")


# -- Conversation runs ------------------------------------------------------


def _current_org_id() -> Optional[int]:
    """Organization of the writing API-key identity (best-effort, None if absent)."""
    from ..auth.context import current_organization_id

    return current_organization_id()


def _tenant_scope() -> Optional[int]:
    """Organization id reads should be restricted to, or None for no scoping."""
    from ..auth.context import tenant_scope

    return tenant_scope()


def _scoped(query, column):
    """Filter ``query`` to the caller's tenant on ``column`` (no-op when unscoped)."""
    org_id = _tenant_scope()
    if org_id is not None:
        query = query.filter(column == org_id)
    return query


def invalidate_workflow_metrics_cache() -> None:
    """Drop cached workflow aggregates after a workflow-affecting write.

    Node/message rows are not org-stamped (their tenant is resolved by joining up
    to the owning conversation), so rather than reconstruct the org per write we
    drop the whole ``_workflow_metrics_for_org`` namespace. Workflow writes are
    far rarer than dashboard reads, and this is a handful of dict removals.
    """
    _workflow_metrics_for_org.invalidate()


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
        organization_id=_current_org_id(),
    )
    db.session.add(conversation)
    db.session.commit()
    invalidate_workflow_metrics_cache()
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
    invalidate_workflow_metrics_cache()
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
    invalidate_workflow_metrics_cache()
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
    invalidate_workflow_metrics_cache()
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
    invalidate_workflow_metrics_cache()
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
        organization_id=_current_org_id(),
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
    """Return a page of workflow definitions and the total matching count.

    The list only needs each workflow's execution *count*, so we avoid eager
    loading the full execution history (which would pull every execution row per
    workflow) and instead attach an index-backed ``func.count()`` per page.
    """
    query = _scoped(WorkflowDefinition.query, WorkflowDefinition.organization_id)
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
    _attach_execution_counts(items)
    return items, total


def _attach_execution_counts(definitions: list[WorkflowDefinition]) -> None:
    """Stamp ``execution_count`` on each definition via one grouped count query.

    Lets the list serializer report the count without triggering a lazy load of
    the (potentially large) executions collection per row.
    """
    ids = [d.id for d in definitions]
    if not ids:
        return
    counts = dict(
        db.session.query(
            WorkflowExecution.workflow_definition_id, func.count(WorkflowExecution.id)
        )
        .filter(WorkflowExecution.workflow_definition_id.in_(ids))
        .group_by(WorkflowExecution.workflow_definition_id)
        .all()
    )
    for definition in definitions:
        definition.execution_count = counts.get(definition.id, 0)


def get_workflow(definition_id: int) -> Optional[WorkflowDefinition]:
    """Return a workflow definition with its execution history, or None (tenant-scoped)."""
    definition = (
        db.session.query(WorkflowDefinition)
        .options(selectinload(WorkflowDefinition.executions))
        .filter(WorkflowDefinition.id == definition_id)
        .one_or_none()
    )
    if definition is None:
        return None
    org_id = _tenant_scope()
    if org_id is not None and definition.organization_id != org_id:
        return None
    return definition


def list_conversations(
    page: int = 1,
    limit: int = 20,
    q: Optional[str] = None,
    status: Optional[str] = None,
    sort: str = "-created_at",
) -> tuple[list[ConversationRun], int]:
    """Return a page of conversation runs and the total matching count.

    The list only needs each conversation's agent/message *counts*, so we avoid
    eager loading the full node tree and message bodies (whose size grows with
    conversation content) and attach index-backed ``func.count()`` values per
    page instead.
    """
    query = ConversationRun.query
    org_id = _tenant_scope()
    if org_id is not None:
        query = query.filter(ConversationRun.organization_id == org_id)
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
    _attach_conversation_counts(items)
    return items, total


def _attach_conversation_counts(conversations: list[ConversationRun]) -> None:
    """Stamp ``agent_count`` and ``message_count`` on each conversation.

    Uses two grouped count queries per page (not per row) so the list serializer
    never triggers a lazy load of the node tree / message bodies.
    """
    ids = [c.id for c in conversations]
    if not ids:
        return
    node_counts = dict(
        db.session.query(AgentNode.conversation_run_id, func.count(AgentNode.id))
        .filter(AgentNode.conversation_run_id.in_(ids))
        .group_by(AgentNode.conversation_run_id)
        .all()
    )
    message_counts = dict(
        db.session.query(AgentMessage.conversation_run_id, func.count(AgentMessage.id))
        .filter(AgentMessage.conversation_run_id.in_(ids))
        .group_by(AgentMessage.conversation_run_id)
        .all()
    )
    for conversation in conversations:
        conversation.agent_count = node_counts.get(conversation.id, 0)
        conversation.message_count = message_counts.get(conversation.id, 0)


def get_conversation(conversation_id: int) -> Optional[ConversationRun]:
    """Return a conversation eager-loaded with its agent tree, runs/steps and messages.

    Hidden (returns ``None``) when it belongs to a different tenant.
    """
    conversation = (
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
    if conversation is None:
        return None
    org_id = _tenant_scope()
    if org_id is not None and conversation.organization_id != org_id:
        return None
    return conversation


def get_workflow_metrics() -> dict:
    """Aggregate multi-agent workflow metrics for the dashboard (tenant-scoped)."""
    return _workflow_metrics_for_org(_tenant_scope())


@cached()
def _workflow_metrics_for_org(organization_id: Optional[int] = None) -> dict:
    """Compute aggregate workflow metrics for one org (or all).

    The unit of a "workflow" here is a :class:`ConversationRun` (one run of a
    multi-agent workflow). ``total_agents`` counts agent nodes; cost is summed
    from the underlying agent-run steps. When ``organization_id`` is set,
    conversation-owned rows filter on their org and child tables (nodes,
    messages, steps) join up to their owning conversation/run. Cached for a few
    seconds (keyed by org) to absorb concurrent dashboard traffic.
    """

    def _own(query):
        """Scope a ConversationRun-rooted query to the org (no-op when unscoped)."""
        if organization_id is None:
            return query
        return query.filter(ConversationRun.organization_id == organization_id)

    def _by_conversation(query):
        """Join an AgentNode query to ConversationRun and scope by org."""
        if organization_id is None:
            return query
        return query.join(
            ConversationRun, AgentNode.conversation_run_id == ConversationRun.id
        ).filter(ConversationRun.organization_id == organization_id)

    total_workflows = _own(
        db.session.query(func.count(ConversationRun.id))
    ).scalar() or 0
    total_agents = _by_conversation(
        db.session.query(func.count(AgentNode.id))
    ).scalar() or 0

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

    messages_query = db.session.query(func.count(AgentMessage.id))
    if organization_id is not None:
        messages_query = messages_query.join(
            ConversationRun, AgentMessage.conversation_run_id == ConversationRun.id
        ).filter(ConversationRun.organization_id == organization_id)
    total_messages = messages_query.scalar() or 0

    # Parallel branches: average size of a parallel group (nodes sharing one
    # non-null parallel_group), i.e. total grouped nodes / distinct groups.
    grouped_nodes = _by_conversation(
        db.session.query(func.count(AgentNode.id))
        .filter(AgentNode.parallel_group.isnot(None))
    ).scalar() or 0
    distinct_groups = _by_conversation(
        db.session.query(func.count(func.distinct(AgentNode.parallel_group)))
        .filter(AgentNode.parallel_group.isnot(None))
    ).scalar() or 0

    avg_latency = _own(
        db.session.query(func.avg(ConversationRun.latency_ms))
    ).scalar() or 0
    cost_query = db.session.query(func.coalesce(func.sum(AgentStep.cost), 0.0))
    if organization_id is not None:
        cost_query = cost_query.join(
            AgentRun, AgentStep.agent_run_id == AgentRun.id
        ).filter(AgentRun.organization_id == organization_id)
    total_cost = cost_query.scalar() or 0
    success_workflows = (
        _own(db.session.query(func.count(ConversationRun.id)))
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
