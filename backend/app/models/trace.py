"""SQLAlchemy model representing a single captured LLM request (a "trace")."""
from sqlalchemy import JSON, Index

from ..extensions import db
from ..utils.timeutils import utcnow


class TraceStatus:
    """Allowed values for a trace's status field."""

    SUCCESS = "success"
    FAILED = "failed"


class Trace(db.Model):
    """A single LLM request/response cycle with all captured metadata."""

    __tablename__ = "traces"

    # Composite indexes for the hot list/dashboard query paths: newest-first
    # listing (optionally filtered by application/status/model). These back the
    # ORDER BY timestamp DESC + WHERE project/status/model queries without a full
    # scan at scale. ``project`` is the primary segmentation axis (see below), so
    # it gets its own timestamp-composite index.
    __table_args__ = (
        Index("ix_traces_project_timestamp", "project", "timestamp"),
        Index("ix_traces_status_timestamp", "status", "timestamp"),
        Index("ix_traces_model_timestamp", "model_name", "timestamp"),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Application / area of concern this request belongs to (e.g. "refunds-bot",
    # "revenue-analytics"). This is the axis teams actually organize around: many
    # surfaces share one model, so segmenting by model is useless, whereas the
    # owner of a surface wants to see only their surface. Optional and client-set;
    # when absent the UI falls back to grouping by system_prompt.
    project = db.Column(db.String(120), nullable=True)

    # Prompts & model
    user_prompt = db.Column(db.Text, nullable=True)
    system_prompt = db.Column(db.Text, nullable=True)
    model_name = db.Column(db.String(120), nullable=False, index=True)

    # Timing
    timestamp = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    latency_ms = db.Column(db.Float, nullable=True)

    # Token usage & cost
    input_tokens = db.Column(db.Integer, nullable=True)
    output_tokens = db.Column(db.Integer, nullable=True)
    total_tokens = db.Column(db.Integer, nullable=True)
    estimated_cost = db.Column(db.Float, nullable=True)

    # Optional rich context (stored as JSON)
    retrieved_documents = db.Column(JSON, nullable=True)
    tool_calls = db.Column(JSON, nullable=True)

    # Outcome
    final_response = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default=TraceStatus.SUCCESS, index=True)
    error_message = db.Column(db.Text, nullable=True)

    # Tenant ownership (v1.0, phase 1). Nullable so single-tenant / auth-off use
    # is unchanged; stamped from the writing API-key identity when present.
    # SET NULL keeps observability history if an organization is deleted.
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    def to_dict(self) -> dict:
        """Serialize the trace to a JSON-friendly dictionary."""
        return {
            "id": self.id,
            "project": self.project,
            "user_prompt": self.user_prompt,
            "system_prompt": self.system_prompt,
            "model_name": self.model_name,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost": self.estimated_cost,
            "retrieved_documents": self.retrieved_documents,
            "tool_calls": self.tool_calls,
            "final_response": self.final_response,
            "status": self.status,
            "error_message": self.error_message,
            "organization_id": self.organization_id,
        }

    def __repr__(self) -> str:
        return f"<Trace id={self.id} model={self.model_name} status={self.status}>"
