"""Database layer for replay & evaluation (v0.5).

This module is purely additive. It introduces five new tables that support
*replaying*, *versioning*, *evaluating* and *comparing* the runs captured by the
earlier tracing layers, hanging off the existing models **without modifying
them**:

* :class:`ReplayRun` re-executes an existing
  :class:`~app.models.workflow_trace.ConversationRun` under different model
  parameters (model, temperature, top_p, system-prompt override) so results can
  be compared.
* :class:`PromptVersion` captures a versioned, content-hashed snapshot of the
  prompt used by a v0.2 :class:`~app.models.agent_trace.AgentRun`.
* :class:`EvaluationRun` records an evaluation pass over a ``ConversationRun``,
  aggregating one or more :class:`EvaluationMetric` scores.
* :class:`EvaluationMetric` is a single named metric belonging to an
  ``EvaluationRun``.
* :class:`ModelComparison` records a head-to-head comparison of two models for a
  ``ConversationRun``, with the winner and the cost/latency/token deltas.

Conventions mirror :mod:`app.models.agent_trace`,
:mod:`app.models.rag_trace` and :mod:`app.models.workflow_trace`:

* Column types (``JSON``, ``DateTime`` ...) are portable across SQLite and
  PostgreSQL.
* SQLAlchemy reserves the attribute name ``metadata``, so the requested
  "metadata" field is exposed on each Python model under a prefixed name
  (``replay_metadata``, ``prompt_metadata`` ...) while mapping to a column
  literally named ``metadata``.
* ``ON DELETE CASCADE`` on the foreign keys plus ``cascade="all, delete-orphan"``
  on the owning relationships ensure children are removed with their parent at
  both the database and ORM levels. Backrefs are declared here so the parent
  models gain reverse accessors without their definitions being touched.
"""
from sqlalchemy import JSON, Index

from ..extensions import db
from ..models.agent_trace import AgentStatus
from ..utils.timeutils import utcnow


class ReplayRun(db.Model):
    """A re-execution of an existing conversation under new model parameters.

    Anchored to the original :class:`~app.models.workflow_trace.ConversationRun`
    so an experiment (different ``replayed_model`` / ``temperature`` / ``top_p``
    / ``system_prompt_override``) can be traced and compared against the source.
    """

    __tablename__ = "replay_runs"
    __table_args__ = (
        # Listing/filtering replays of a conversation, most recent first.
        Index("ix_replay_runs_original_created", "original_conversation_run_id", "created_at"),
        # Dashboard filtering by status ordered by recency.
        Index("ix_replay_runs_status_created", "status", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)

    original_conversation_run_id = db.Column(
        db.Integer,
        db.ForeignKey("conversation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    replayed_model = db.Column(db.String(255), nullable=True)
    temperature = db.Column(db.Float, nullable=True)
    top_p = db.Column(db.Float, nullable=True)
    system_prompt_override = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), nullable=False, default=AgentStatus.PENDING, index=True)

    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    latency_ms = db.Column(db.Float, nullable=True)
    cost = db.Column(db.Float, nullable=True)

    replay_metadata = db.Column("metadata", JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    # Tenant ownership (v1.0, phase 2). Denormalized from the original
    # ConversationRun; nullable + SET NULL, mirrors traces.organization_id.
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ConversationRun -> ReplayRuns. Backref added without touching the model.
    original_conversation_run = db.relationship(
        "ConversationRun",
        backref=db.backref(
            "replay_runs",
            cascade="all, delete-orphan",
            order_by="ReplayRun.created_at",
            lazy="select",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ReplayRun id={self.id} model={self.replayed_model!r} "
            f"status={self.status} original={self.original_conversation_run_id}>"
        )


class PromptVersion(db.Model):
    """A versioned, content-hashed snapshot of an agent run's prompt.

    Belongs to a v0.2 :class:`~app.models.agent_trace.AgentRun`. ``hash`` lets
    identical prompts be de-duplicated / detected across versions and runs.
    """

    __tablename__ = "prompt_versions"
    __table_args__ = (
        # Fetching a run's versions in version order is the hot path.
        Index("ix_prompt_versions_run_version", "agent_run_id", "version"),
    )

    id = db.Column(db.Integer, primary_key=True)

    agent_run_id = db.Column(
        db.Integer,
        db.ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    version = db.Column(db.String(50), nullable=True)
    prompt_text = db.Column(db.Text, nullable=True)
    hash = db.Column(db.String(64), nullable=True, index=True)

    prompt_metadata = db.Column("metadata", JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    # AgentRun -> PromptVersions. Backref added without touching AgentRun.
    agent_run = db.relationship(
        "AgentRun",
        backref=db.backref(
            "prompt_versions",
            cascade="all, delete-orphan",
            order_by="PromptVersion.version",
            lazy="select",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PromptVersion id={self.id} run_id={self.agent_run_id} "
            f"version={self.version} hash={self.hash!r}>"
        )


class EvaluationRun(db.Model):
    """An evaluation pass over a conversation, aggregating scored metrics.

    Anchored to a :class:`~app.models.workflow_trace.ConversationRun`. Owns one
    or more :class:`EvaluationMetric` rows; ``overall_score`` is the aggregate.
    """

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        # Listing a conversation's evaluations, most recent first.
        Index("ix_evaluation_runs_conversation_created", "conversation_run_id", "created_at"),
        # Filtering by evaluation type / status ordered by recency.
        Index("ix_evaluation_runs_type_created", "evaluation_type", "created_at"),
        Index("ix_evaluation_runs_status_created", "status", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)

    conversation_run_id = db.Column(
        db.Integer,
        db.ForeignKey("conversation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    evaluation_type = db.Column(db.String(120), nullable=True, index=True)
    model_name = db.Column(db.String(255), nullable=True)
    overall_score = db.Column(db.Float, nullable=True)

    status = db.Column(db.String(20), nullable=False, default=AgentStatus.PENDING, index=True)

    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    evaluation_metadata = db.Column("metadata", JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    # Tenant ownership (v1.0, phase 2). Denormalized from the ConversationRun;
    # nullable + SET NULL, mirrors traces.organization_id.
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ConversationRun -> EvaluationRuns. Backref added without touching the model.
    conversation_run = db.relationship(
        "ConversationRun",
        backref=db.backref(
            "evaluation_runs",
            cascade="all, delete-orphan",
            order_by="EvaluationRun.created_at",
            lazy="select",
        ),
    )

    # EvaluationRun -> EvaluationMetrics. ``selectin`` batches child loads across
    # a page of runs to avoid N+1 queries when serializing lists/details.
    metrics = db.relationship(
        "EvaluationMetric",
        back_populates="evaluation_run",
        cascade="all, delete-orphan",
        order_by="EvaluationMetric.metric_name",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<EvaluationRun id={self.id} type={self.evaluation_type!r} "
            f"score={self.overall_score} status={self.status} "
            f"conversation_run_id={self.conversation_run_id}>"
        )


class EvaluationMetric(db.Model):
    """A single named metric belonging to an :class:`EvaluationRun`."""

    __tablename__ = "evaluation_metrics"
    __table_args__ = (
        # Metrics are almost always fetched per-run, by name.
        Index("ix_evaluation_metrics_run_name", "evaluation_run_id", "metric_name"),
    )

    id = db.Column(db.Integer, primary_key=True)

    evaluation_run_id = db.Column(
        db.Integer,
        db.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    metric_name = db.Column(db.String(255), nullable=False)
    metric_value = db.Column(db.Float, nullable=True)
    weight = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    evaluation_run = db.relationship("EvaluationRun", back_populates="metrics")

    def __repr__(self) -> str:
        return (
            f"<EvaluationMetric id={self.id} run_id={self.evaluation_run_id} "
            f"name={self.metric_name!r} value={self.metric_value}>"
        )


class ModelComparison(db.Model):
    """A head-to-head comparison of two models for a conversation.

    Anchored to a :class:`~app.models.workflow_trace.ConversationRun`. Records
    the two contenders, the ``winner`` and the cost / latency / token deltas
    (``model_a`` minus ``model_b`` by convention).
    """

    __tablename__ = "model_comparisons"
    __table_args__ = (
        # Listing a conversation's comparisons, most recent first.
        Index("ix_model_comparisons_conversation_created", "conversation_run_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)

    conversation_run_id = db.Column(
        db.Integer,
        db.ForeignKey("conversation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    model_a = db.Column(db.String(255), nullable=True)
    model_b = db.Column(db.String(255), nullable=True)
    winner = db.Column(db.String(255), nullable=True)
    reason = db.Column(db.Text, nullable=True)

    cost_difference = db.Column(db.Float, nullable=True)
    latency_difference = db.Column(db.Float, nullable=True)
    token_difference = db.Column(db.Integer, nullable=True)

    comparison_metadata = db.Column("metadata", JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    # Tenant ownership (v1.0, phase 2). Denormalized from the ConversationRun;
    # nullable + SET NULL, mirrors traces.organization_id.
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ConversationRun -> ModelComparisons. Backref added without touching model.
    conversation_run = db.relationship(
        "ConversationRun",
        backref=db.backref(
            "model_comparisons",
            cascade="all, delete-orphan",
            order_by="ModelComparison.created_at",
            lazy="select",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ModelComparison id={self.id} a={self.model_a!r} b={self.model_b!r} "
            f"winner={self.winner!r} conversation_run_id={self.conversation_run_id}>"
        )
