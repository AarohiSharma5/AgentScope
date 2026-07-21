"""Persistence for saved analytics views (custom dashboards).

Thin CRUD over :class:`~app.models.saved_view.SavedView`, tenant-scoped exactly
like the other resources: reads are restricted to the caller's organization and
writes are stamped with their active organization. The ``config`` blob is
validated as a JSON object before persistence.
"""
from typing import Optional

from ..extensions import db
from ..models.saved_view import SavedView
from ..utils.validation import ensure_json_object


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
        query = query.filter(SavedView.organization_id == org_id)
    return query


def list_saved_views() -> list[SavedView]:
    """Return the caller's saved views, newest first."""
    return _scoped(SavedView.query).order_by(SavedView.created_at.desc()).all()


def create_saved_view(name: str, config: dict) -> SavedView:
    """Persist a new saved view stamped with the caller's organization."""
    view = SavedView(
        name=name,
        config=ensure_json_object(config, "config") or {},
        organization_id=_current_org(),
    )
    db.session.add(view)
    db.session.commit()
    return view


def get_saved_view(view_id: int) -> Optional[SavedView]:
    """Return a saved view by id, or None if missing / not the caller's tenant."""
    view = db.session.get(SavedView, view_id)
    if view is None:
        return None
    org_id = _tenant_scope()
    if org_id is not None and view.organization_id != org_id:
        return None
    return view


def delete_saved_view(view_id: int) -> bool:
    """Delete a saved view (tenant-scoped). Returns True if one was removed."""
    view = get_saved_view(view_id)
    if view is None:
        return False
    db.session.delete(view)
    db.session.commit()
    return True
