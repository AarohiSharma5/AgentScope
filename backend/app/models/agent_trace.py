"""Database layer for Agent Execution Tracing (v0.2).

This module is purely additive: it introduces new tables for tracing agent
runs, steps, tool executions, memory accesses and retriever calls. It does not
modify the existing ``Trace`` model, API, or dashboard in any way.

All column types (``JSON``, ``DateTime``, etc.) are chosen to remain compatible
with both SQLite and PostgreSQL.

Note on ``metadata``: SQLAlchemy's declarative base reserves the attribute name
``metadata``, so the requested "metadata" field is exposed on the Python model
as ``run_metadata`` / ``step_metadata`` while still mapping to a database column
literally named ``metadata``.
"""
from sqlalchemy import JSON, Index

from ..extensions import db
from ..utils.timeutils import utcnow


class AgentStatus:
    """Shared status values for agent runs and steps."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    # Additional terminal states used by the workflow engine (v0.4).
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class AgentRun(db.Model):
    """A single agent invocation, optionally nested under a parent run.

    An ``AgentRun`` is tied to a :class:`Trace` (the originating LLM request)
    and can form a tree via ``parent_run_id`` to represent multi-agent or
    recursive execution.
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        # Fetching every run for a request, newest first, is a hot path.
        Index("ix_agent_runs_request_created", "request_id", "created_at"),
        # Dashboard/list filtering by status ordered by recency.
        Index("ix_agent_runs_status_created", "status", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)

    request_id = db.Column(
        db.Integer,
        db.ForeignKey("traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_run_id = db.Column(
        db.Integer,
        db.ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    agent_name = db.Column(db.String(255), nullable=False, index=True)
    agent_type = db.Column(db.String(120), nullable=True, index=True)

    status = db.Column(db.String(20), nullable=False, default=AgentStatus.PENDING, index=True)

    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    latency_ms = db.Column(db.Float, nullable=True)

    run_metadata = db.Column("metadata", JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    # RequestTrace (Trace) -> AgentRuns. Backref added without touching Trace.
    request = db.relationship(
        "Trace",
        backref=db.backref("agent_runs", cascade="all, delete-orphan", lazy="select"),
    )

    # AgentRun -> child AgentRuns (self-referential tree).
    children = db.relationship(
        "AgentRun",
        backref=db.backref("parent", remote_side=[id]),
        cascade="all, delete-orphan",
        lazy="select",
    )

    # AgentRun -> AgentSteps. ``selectin`` batches child loads across a page of
    # runs to avoid N+1 queries when serializing lists and details.
    steps = db.relationship(
        "AgentStep",
        back_populates="agent_run",
        cascade="all, delete-orphan",
        order_by="AgentStep.step_number",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<AgentRun id={self.id} agent={self.agent_name!r} "
            f"status={self.status} request_id={self.request_id}>"
        )


class AgentStep(db.Model):
    """A single step within an agent run (e.g. a reasoning or action step)."""

    __tablename__ = "agent_steps"
    __table_args__ = (
        # Steps are almost always fetched per-run in step order.
        Index("ix_agent_steps_run_number", "agent_run_id", "step_number"),
    )

    id = db.Column(db.Integer, primary_key=True)

    agent_run_id = db.Column(
        db.Integer,
        db.ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    step_number = db.Column(db.Integer, nullable=True)
    step_type = db.Column(db.String(120), nullable=True)
    name = db.Column(db.String(255), nullable=True)

    input = db.Column(db.Text, nullable=True)
    output = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), nullable=False, default=AgentStatus.PENDING, index=True)
    latency_ms = db.Column(db.Float, nullable=True)

    token_usage = db.Column(JSON, nullable=True)
    cost = db.Column(db.Float, nullable=True)

    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    step_metadata = db.Column("metadata", JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    agent_run = db.relationship("AgentRun", back_populates="steps")

    # AgentStep -> many ToolExecutions. ``selectin`` avoids per-step queries when
    # building a run's timeline / detail view.
    tool_executions = db.relationship(
        "ToolExecution",
        back_populates="step",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # AgentStep -> MemoryAccess.
    memory_accesses = db.relationship(
        "MemoryAccess",
        back_populates="step",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # AgentStep -> RetrieverTrace.
    retriever_traces = db.relationship(
        "RetrieverTrace",
        back_populates="step",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<AgentStep id={self.id} run_id={self.agent_run_id} "
            f"step={self.step_number} type={self.step_type!r} status={self.status}>"
        )


class ToolExecution(db.Model):
    """A tool/function call made during an agent step."""

    __tablename__ = "tool_executions"

    id = db.Column(db.Integer, primary_key=True)

    step_id = db.Column(
        db.Integer,
        db.ForeignKey("agent_steps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    tool_name = db.Column(db.String(255), nullable=False)
    arguments = db.Column(JSON, nullable=True)
    result = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), nullable=False, default=AgentStatus.PENDING, index=True)
    latency_ms = db.Column(db.Float, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    step = db.relationship("AgentStep", back_populates="tool_executions")

    def __repr__(self) -> str:
        return (
            f"<ToolExecution id={self.id} step_id={self.step_id} "
            f"tool={self.tool_name!r} status={self.status}>"
        )


class MemoryAccess(db.Model):
    """A read/lookup against an agent's memory during a step."""

    __tablename__ = "memory_accesses"

    id = db.Column(db.Integer, primary_key=True)

    step_id = db.Column(
        db.Integer,
        db.ForeignKey("agent_steps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    memory_type = db.Column(db.String(120), nullable=True)
    query = db.Column(db.Text, nullable=True)
    retrieved_text = db.Column(db.Text, nullable=True)
    similarity_score = db.Column(db.Float, nullable=True)
    used = db.Column(db.Boolean, nullable=True)
    latency_ms = db.Column(db.Float, nullable=True)

    step = db.relationship("AgentStep", back_populates="memory_accesses")

    def __repr__(self) -> str:
        return (
            f"<MemoryAccess id={self.id} step_id={self.step_id} "
            f"type={self.memory_type!r} used={self.used}>"
        )


class RetrieverTrace(db.Model):
    """A retrieval (RAG) call made during an agent step."""

    __tablename__ = "retriever_traces"

    id = db.Column(db.Integer, primary_key=True)

    step_id = db.Column(
        db.Integer,
        db.ForeignKey("agent_steps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    query = db.Column(db.Text, nullable=True)
    retrieved_documents = db.Column(JSON, nullable=True)
    embedding_time_ms = db.Column(db.Float, nullable=True)
    retrieval_time_ms = db.Column(db.Float, nullable=True)
    num_documents = db.Column(db.Integer, nullable=True)

    step = db.relationship("AgentStep", back_populates="retriever_traces")

    def __repr__(self) -> str:
        return (
            f"<RetrieverTrace id={self.id} step_id={self.step_id} "
            f"num_documents={self.num_documents}>"
        )
