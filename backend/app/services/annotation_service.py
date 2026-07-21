"""Persistence for timeline annotations (deploy / change markers).

Thin CRUD over :class:`~app.models.annotation.Annotation`, tenant-scoped exactly
like the other resources: reads are restricted to the caller's organization and
writes are stamped with their active organization.
"""
from datetime import datetime, timedelta
from typing import Optional

from ..extensions import db
from ..models.annotation import Annotation
from ..utils.timeutils import utcnow


def _tenant_scope() -> Optional[int]:
    from ..auth.context import tenant_scope

    return tenant_scope()


def _current_org() -> Optional[int]:
    from ..auth.context import current_organization_id

    return current_organization_id()


def _scoped(query):
    """Restrict ``query`` to the caller's tenant (no-op when unscoped)."""
    org_id = _tenant_scope()
    if org_id is not None:
        query = query.filter(Annotation.organization_id == org_id)
    return query


def list_annotations(days: Optional[int] = None) -> list[Annotation]:
    """Return the caller's annotations (optionally within the last ``days``)."""
    query = _scoped(Annotation.query)
    if days and days > 0:
        since = utcnow() - timedelta(days=days)
        query = query.filter(Annotation.annotated_at >= since)
    return query.order_by(Annotation.annotated_at.asc()).all()


def create_annotation(
    label: str, annotated_at: datetime, description: Optional[str] = None
) -> Annotation:
    """Persist a new annotation stamped with the caller's organization."""
    annotation = Annotation(
        label=label,
        description=description,
        annotated_at=annotated_at,
        organization_id=_current_org(),
    )
    db.session.add(annotation)
    db.session.commit()
    return annotation


def get_annotation(annotation_id: int) -> Optional[Annotation]:
    """Return an annotation by id, or None if missing / not the caller's tenant."""
    annotation = db.session.get(Annotation, annotation_id)
    if annotation is None:
        return None
    org_id = _tenant_scope()
    if org_id is not None and annotation.organization_id != org_id:
        return None
    return annotation


def delete_annotation(annotation_id: int) -> bool:
    """Delete an annotation (tenant-scoped). Returns True if one was removed."""
    annotation = get_annotation(annotation_id)
    if annotation is None:
        return False
    db.session.delete(annotation)
    db.session.commit()
    return True
