"""Database layer for RAG / prompt-assembly tracing (v0.3).

This module is purely additive. It introduces three new tables that hang off the
existing v0.2 tracing models **without modifying them**:

* :class:`RetrievedDocument` and :class:`EmbeddingTrace` extend a
  :class:`~app.models.agent_trace.RetrieverTrace` with the individual documents
  it returned and the embedding call it made.
* :class:`PromptAssembly` extends an
  :class:`~app.models.agent_trace.AgentRun` with a breakdown of how the final
  prompt was assembled from its various context sources.

Relationships back to the existing models are declared here using ``backref`` so
the parent classes gain their reverse accessors (``documents``,
``embedding_trace``, ``prompt_assembly``) without their definitions being
touched.

Conventions mirror :mod:`app.models.agent_trace`:

* All column types (``JSON``, ``DateTime`` ...) are portable across SQLite and
  PostgreSQL.
* SQLAlchemy reserves the attribute name ``metadata``, so the requested
  "metadata" field is exposed on the Python model as ``doc_metadata`` /
  ``embedding_metadata`` while mapping to a column literally named ``metadata``.
* ``ON DELETE CASCADE`` on the foreign keys plus ``cascade="all, delete-orphan"``
  on the relationships ensure children are removed with their parent at both the
  database and ORM levels.
"""
from sqlalchemy import JSON, Index

from ..extensions import db
from ..utils.timeutils import utcnow


class RetrievedDocument(db.Model):
    """A single document/chunk returned by a retriever call.

    Multiple ``RetrievedDocument`` rows belong to one
    :class:`~app.models.agent_trace.RetrieverTrace`, capturing exactly what the
    retriever surfaced, its ranking (``similarity_score``) and whether it was
    ultimately ``selected`` for the prompt.
    """

    __tablename__ = "retrieved_documents"
    __table_args__ = (
        # Fetching a trace's documents filtered/ordered by selection or score.
        Index("ix_retrieved_documents_trace_selected", "retriever_trace_id", "selected"),
        Index("ix_retrieved_documents_trace_score", "retriever_trace_id", "similarity_score"),
        # The relationship loads documents ordered by chunk_index per trace.
        Index("ix_retrieved_documents_trace_chunk", "retriever_trace_id", "chunk_index"),
    )

    id = db.Column(db.Integer, primary_key=True)

    retriever_trace_id = db.Column(
        db.Integer,
        db.ForeignKey("retriever_traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    document_id = db.Column(db.String(255), nullable=True, index=True)
    document_name = db.Column(db.String(512), nullable=True)
    document_source = db.Column(db.String(512), nullable=True)

    chunk_index = db.Column(db.Integer, nullable=True)
    chunk_text = db.Column(db.Text, nullable=True)

    similarity_score = db.Column(db.Float, nullable=True)
    selected = db.Column(db.Boolean, nullable=False, default=False)

    doc_metadata = db.Column("metadata", JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    # RetrieverTrace -> RetrievedDocuments (one-to-many). Backref is named
    # ``documents`` because ``retrieved_documents`` is already a JSON column on
    # RetrieverTrace.
    retriever_trace = db.relationship(
        "RetrieverTrace",
        backref=db.backref(
            "documents",
            cascade="all, delete-orphan",
            order_by="RetrievedDocument.chunk_index",
            lazy="selectin",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<RetrievedDocument id={self.id} trace_id={self.retriever_trace_id} "
            f"name={self.document_name!r} selected={self.selected}>"
        )


class EmbeddingTrace(db.Model):
    """The embedding call made to service a retriever trace.

    Modeled one-to-one with :class:`~app.models.agent_trace.RetrieverTrace`
    (a retrieval embeds its query once), recording the embedding model, output
    dimensionality, token usage, latency and cost.
    """

    __tablename__ = "embedding_traces"
    __table_args__ = (
        Index("ix_embedding_traces_model", "embedding_model"),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Unique so the relationship is genuinely one-to-one at the database level.
    retriever_trace_id = db.Column(
        db.Integer,
        db.ForeignKey("retriever_traces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    embedding_model = db.Column(db.String(255), nullable=True)
    embedding_dimension = db.Column(db.Integer, nullable=True)
    input_tokens = db.Column(db.Integer, nullable=True)
    latency_ms = db.Column(db.Float, nullable=True)
    cost = db.Column(db.Float, nullable=True)

    embedding_metadata = db.Column("metadata", JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    # RetrieverTrace -> EmbeddingTrace (one-to-one via ``uselist=False``).
    retriever_trace = db.relationship(
        "RetrieverTrace",
        backref=db.backref(
            "embedding_trace",
            uselist=False,
            cascade="all, delete-orphan",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<EmbeddingTrace id={self.id} trace_id={self.retriever_trace_id} "
            f"model={self.embedding_model!r} dim={self.embedding_dimension}>"
        )


class PromptAssembly(db.Model):
    """A breakdown of how an agent run assembled its final prompt.

    Modeled one-to-one with :class:`~app.models.agent_trace.AgentRun`. Stores the
    individual context sources (system, conversation, retrieved, memory, user),
    the fully ``assembled_prompt`` and a per-source token accounting so callers
    can see exactly where the context budget was spent.
    """

    __tablename__ = "prompt_assemblies"
    __table_args__ = (
        Index("ix_prompt_assemblies_run", "agent_run_id"),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Unique so the relationship is genuinely one-to-one at the database level.
    agent_run_id = db.Column(
        db.Integer,
        db.ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Context sources that feed the assembled prompt.
    system_prompt = db.Column(db.Text, nullable=True)
    conversation_context = db.Column(db.Text, nullable=True)
    retrieved_context = db.Column(db.Text, nullable=True)
    memory_context = db.Column(db.Text, nullable=True)
    user_prompt = db.Column(db.Text, nullable=True)
    assembled_prompt = db.Column(db.Text, nullable=True)

    # Per-source token accounting.
    system_tokens = db.Column(db.Integer, nullable=True)
    conversation_tokens = db.Column(db.Integer, nullable=True)
    retrieval_tokens = db.Column(db.Integer, nullable=True)
    memory_tokens = db.Column(db.Integer, nullable=True)
    user_tokens = db.Column(db.Integer, nullable=True)
    total_tokens = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    # AgentRun -> PromptAssembly (one-to-one via ``uselist=False``).
    agent_run = db.relationship(
        "AgentRun",
        backref=db.backref(
            "prompt_assembly",
            uselist=False,
            cascade="all, delete-orphan",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PromptAssembly id={self.id} run_id={self.agent_run_id} "
            f"total_tokens={self.total_tokens}>"
        )
