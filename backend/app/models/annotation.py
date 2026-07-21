"""Timeline annotations (deploy / change markers) for the analytics dashboard.

An :class:`Annotation` records a point-in-time event — e.g. "v2 prompt shipped"
or "switched to gpt-4o" — so quality/cost/latency movements on the trend charts
can be tied back to the change that caused them. Purely additive: a standalone
table that does not touch any existing model.
"""
from sqlalchemy import Index

from ..extensions import db
from ..utils.timeutils import utcnow


class Annotation(db.Model):
    """A user-authored marker placed on the analytics timeline."""

    __tablename__ = "annotations"
    __table_args__ = (
        # Listing a tenant's annotations within a time window, in order.
        Index("ix_annotations_org_date", "organization_id", "annotated_at"),
    )

    id = db.Column(db.Integer, primary_key=True)

    label = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # The moment the annotated event happened (e.g. the deploy time).
    annotated_at = db.Column(db.DateTime, nullable=False, index=True)

    # Tenant ownership (mirrors the other resources): nullable + SET NULL, stamped
    # from the writing principal's active organization.
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    def __repr__(self) -> str:
        return f"<Annotation id={self.id} label={self.label!r} at={self.annotated_at}>"
