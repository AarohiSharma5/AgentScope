"""Budgets / SLOs / thresholds for the analytics dashboard.

A :class:`Budget` is a user-defined guardrail on a single metric — a cost cap
("stay under $50 / month"), a quality floor ("avg score must stay above 0.85"),
a latency ceiling or a failure-rate ceiling. The dashboard evaluates each one
over its own window and shows OK / warn / breach status, turning passive
analytics into active governance.

Purely additive: a standalone table that does not touch any existing model. The
metric is stored as a string (validated at the service layer) and ``comparison``
records whether the actual value must stay at/below (``lte``) or at/above
(``gte``) the threshold.
"""
from sqlalchemy import Index

from ..extensions import db
from ..utils.timeutils import utcnow


class Budget(db.Model):
    """A user-authored threshold on a single analytics metric."""

    __tablename__ = "budgets"
    __table_args__ = (
        # Listing a tenant's budgets newest-first.
        Index("ix_budgets_org_created", "organization_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(255), nullable=False)

    # Which metric this guardrail watches (validated against a fixed set in the
    # service): cost | avg_score | failure_rate | avg_latency.
    metric = db.Column(db.String(50), nullable=False)

    # Direction of the guardrail: 'lte' (actual must stay <= threshold, e.g. a
    # cost cap) or 'gte' (actual must stay >= threshold, e.g. a quality floor).
    comparison = db.Column(db.String(8), nullable=False, default="lte")

    threshold_value = db.Column(db.Float, nullable=False)

    # Evaluation window in days (0 = all history). A monthly cost budget uses 30.
    window_days = db.Column(db.Integer, nullable=False, default=30)

    # Optional scope to a single generating model (matches the analytics filter).
    model = db.Column(db.String(255), nullable=True)

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
        return (
            f"<Budget id={self.id} name={self.name!r} metric={self.metric} "
            f"{self.comparison} {self.threshold_value}>"
        )
