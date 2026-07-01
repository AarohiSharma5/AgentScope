"""Database layer for multi-agent workflow orchestration (v0.4).

This module is purely additive. It introduces five new tables that model
*conversations* between multiple agents and the *workflows* that drive them,
hanging off the existing tracing models **without modifying them**:

* :class:`ConversationRun` groups a multi-agent conversation, tied to the
  originating :class:`~app.models.trace.Trace` (the LLM request).
* :class:`AgentNode` is an individual agent participating in a conversation. It
  is *recursive* (``parent_node_id``) so hierarchical / sub-agent topologies can
  be represented, and it cross-links to a v0.2
  :class:`~app.models.agent_trace.AgentRun` for the concrete execution trace.
* :class:`AgentMessage` captures communication (sender → receiver) between nodes.
* :class:`WorkflowDefinition` stores a reusable workflow specification.
* :class:`WorkflowExecution` records one run of a definition, linked to the
  :class:`ConversationRun` it produced.

Conventions mirror :mod:`app.models.agent_trace` and
:mod:`app.models.rag_trace`:

* Column types (``JSON``, ``DateTime`` ...) are portable across SQLite and
  PostgreSQL.
* SQLAlchemy reserves the attribute name ``metadata``, so the requested
  "metadata" field is exposed on each Python model under a prefixed name
  (``conversation_metadata``, ``node_metadata`` ...) while mapping to a column
  literally named ``metadata``.
* ``ON DELETE CASCADE`` on the foreign keys plus ``cascade="all, delete-orphan"``
  on the owning relationships ensure children are removed with their parent at
  both the database and ORM levels. Cross-links to independently-managed traces
  (an ``AgentRun``) use ``SET NULL`` so cleaning up a trace never destroys the
  workflow topology.
"""
from sqlalchemy import JSON, Index

from ..extensions import db
from ..models.agent_trace import AgentStatus
from ..utils.timeutils import utcnow


class ConversationRun(db.Model):
    """A multi-agent conversation, tied to the originating request trace.

    Groups the :class:`AgentNode` participants and their :class:`AgentMessage`
    exchanges under a single, timed unit of work.
    """

    __tablename__ = "conversation_runs"
    __table_args__ = (
        # Listing/filtering conversations by status, most recent first.
        Index("ix_conversation_runs_status_created", "status", "created_at"),
        # Every conversation for a request, newest first.
        Index("ix_conversation_runs_request_created", "request_trace_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)

    request_trace_id = db.Column(
        db.Integer,
        db.ForeignKey("traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    conversation_name = db.Column(db.String(255), nullable=True)

    status = db.Column(db.String(20), nullable=False, default=AgentStatus.PENDING, index=True)

    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    latency_ms = db.Column(db.Float, nullable=True)

    conversation_metadata = db.Column("metadata", JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    # Trace -> ConversationRuns. Backref added without touching the Trace model.
    request = db.relationship(
        "Trace",
        backref=db.backref("conversation_runs", cascade="all, delete-orphan", lazy="select"),
    )

    # ConversationRun -> AgentNodes (all nodes, root and nested). ``selectin``
    # batches child loads across a page of conversations.
    nodes = db.relationship(
        "AgentNode",
        back_populates="conversation_run",
        cascade="all, delete-orphan",
        order_by="AgentNode.execution_order",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationRun id={self.id} name={self.conversation_name!r} "
            f"status={self.status} request_trace_id={self.request_trace_id}>"
        )


class AgentNode(db.Model):
    """An individual agent participating in a :class:`ConversationRun`.

    Recursive via ``parent_node_id`` to model hierarchical or sub-agent
    topologies, and ordered within its conversation via ``execution_order``.
    ``parallel_group`` tags nodes that run concurrently. ``agent_run_id``
    cross-links to the concrete v0.2 execution trace (nullable; ``SET NULL`` so
    trace cleanup does not delete the node).
    """

    __tablename__ = "agent_nodes"
    __table_args__ = (
        # Fetching a conversation's nodes in execution order is the hot path.
        Index("ix_agent_nodes_conversation_order", "conversation_run_id", "execution_order"),
        # Filtering nodes by status within a conversation.
        Index("ix_agent_nodes_conversation_status", "conversation_run_id", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)

    conversation_run_id = db.Column(
        db.Integer,
        db.ForeignKey("conversation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Cross-link to the v0.2 agent-run trace. Nullable + SET NULL: a node may be
    # planned before it runs, and deleting a trace must not delete the node.
    agent_run_id = db.Column(
        db.Integer,
        db.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    parent_node_id = db.Column(
        db.Integer,
        db.ForeignKey("agent_nodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    agent_role = db.Column(db.String(120), nullable=True)
    display_name = db.Column(db.String(255), nullable=True)

    execution_order = db.Column(db.Integer, nullable=True, index=True)
    parallel_group = db.Column(db.String(120), nullable=True, index=True)

    status = db.Column(db.String(20), nullable=False, default=AgentStatus.PENDING, index=True)

    node_metadata = db.Column("metadata", JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    conversation_run = db.relationship("ConversationRun", back_populates="nodes")

    # AgentNode -> AgentRun cross-link. Backref added without touching AgentRun;
    # no delete-orphan (the run is independently owned via its request trace).
    agent_run = db.relationship(
        "AgentRun",
        backref=db.backref("workflow_nodes", lazy="select"),
    )

    # AgentNode -> child AgentNodes (self-referential tree).
    children = db.relationship(
        "AgentNode",
        backref=db.backref("parent", remote_side=[id]),
        cascade="all, delete-orphan",
        order_by="AgentNode.execution_order",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<AgentNode id={self.id} role={self.agent_role!r} "
            f"order={self.execution_order} status={self.status} "
            f"conversation_run_id={self.conversation_run_id}>"
        )


class AgentMessage(db.Model):
    """A message exchanged between two :class:`AgentNode` instances.

    ``sender_node_id`` is required and owns the message (deleting the sender
    removes its messages). ``receiver_node_id`` is optional (e.g. broadcasts) and
    uses ``SET NULL`` so removing a receiver leaves the message intact.
    """

    __tablename__ = "agent_messages"
    __table_args__ = (
        # Conversation transcript ordering and per-node lookups.
        Index("ix_agent_messages_sender_created", "sender_node_id", "created_at"),
        Index("ix_agent_messages_receiver_created", "receiver_node_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)

    sender_node_id = db.Column(
        db.Integer,
        db.ForeignKey("agent_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    receiver_node_id = db.Column(
        db.Integer,
        db.ForeignKey("agent_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    message_type = db.Column(db.String(120), nullable=True, index=True)
    content = db.Column(db.Text, nullable=True)

    token_usage = db.Column(JSON, nullable=True)
    latency_ms = db.Column(db.Float, nullable=True)

    message_metadata = db.Column("metadata", JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    # Two FKs to the same table, so ``foreign_keys`` disambiguates each side.
    sender = db.relationship(
        "AgentNode",
        foreign_keys=[sender_node_id],
        backref=db.backref("sent_messages", cascade="all, delete-orphan", lazy="selectin"),
    )
    receiver = db.relationship(
        "AgentNode",
        foreign_keys=[receiver_node_id],
        backref=db.backref("received_messages", lazy="selectin"),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentMessage id={self.id} type={self.message_type!r} "
            f"sender={self.sender_node_id} receiver={self.receiver_node_id}>"
        )


class WorkflowDefinition(db.Model):
    """A reusable, versioned workflow specification.

    ``workflow_json`` stores the declarative graph (nodes, edges, roles, ...)
    that a :class:`WorkflowExecution` runs.
    """

    __tablename__ = "workflow_definitions"
    __table_args__ = (
        # Look up a workflow by name (and version) quickly.
        Index("ix_workflow_definitions_name_version", "workflow_name", "version"),
    )

    id = db.Column(db.Integer, primary_key=True)

    workflow_name = db.Column(db.String(255), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    version = db.Column(db.String(60), nullable=True)

    workflow_json = db.Column(JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    # WorkflowDefinition -> WorkflowExecutions.
    executions = db.relationship(
        "WorkflowExecution",
        back_populates="workflow_definition",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowDefinition id={self.id} name={self.workflow_name!r} "
            f"version={self.version!r}>"
        )


class WorkflowExecution(db.Model):
    """One run of a :class:`WorkflowDefinition`.

    Linked one-to-one to the :class:`ConversationRun` it produced (a conversation
    is driven by at most one workflow execution).
    """

    __tablename__ = "workflow_executions"
    __table_args__ = (
        # Executions of a definition, filtered by status / recency.
        Index("ix_workflow_executions_definition_status", "workflow_definition_id", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)

    workflow_definition_id = db.Column(
        db.Integer,
        db.ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Unique so the relationship is genuinely one-to-one at the database level.
    conversation_run_id = db.Column(
        db.Integer,
        db.ForeignKey("conversation_runs.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
        index=True,
    )

    status = db.Column(db.String(20), nullable=False, default=AgentStatus.PENDING, index=True)

    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    latency_ms = db.Column(db.Float, nullable=True)

    execution_metadata = db.Column("metadata", JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    workflow_definition = db.relationship("WorkflowDefinition", back_populates="executions")

    # ConversationRun -> WorkflowExecution (one-to-one via ``uselist=False``).
    conversation_run = db.relationship(
        "ConversationRun",
        backref=db.backref(
            "workflow_execution",
            uselist=False,
            cascade="all, delete-orphan",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowExecution id={self.id} "
            f"workflow_definition_id={self.workflow_definition_id} "
            f"status={self.status}>"
        )
