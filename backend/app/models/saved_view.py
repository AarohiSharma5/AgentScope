"""Saved analytics views (custom dashboards) for the analytics page.

A :class:`SavedView` stores a named dashboard configuration — the range and
model filter (and any future layout preferences) — so a user can re-apply a
preferred slice of the analytics in one click ("Last 7 days · gpt-4o"). The
configuration is an open JSON blob so new preferences can be added without a
schema change.

Purely additive: a standalone, tenant-scoped table that does not touch any
existing model.
"""
from sqlalchemy import Index
from sqlalchemy.types import JSON

from ..extensions import db
from ..utils.timeutils import utcnow


class SavedView(db.Model):
    """A user-authored, named analytics dashboard configuration."""

    __tablename__ = "saved_views"
    __table_args__ = (
        # Listing a tenant's views newest-first.
        Index("ix_saved_views_org_created", "organization_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(255), nullable=False)

    # Open configuration blob: currently ``{days, model}``; extensible to layout
    # preferences (pinned panels, ordering) without a migration.
    config = db.Column(JSON, nullable=False, default=dict)

    # Tenant ownership (mirrors the other resources): nullable + SET NULL,
    # stamped from the writing principal's active organization.
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    def __repr__(self) -> str:
        return f"<SavedView id={self.id} name={self.name!r}>"
