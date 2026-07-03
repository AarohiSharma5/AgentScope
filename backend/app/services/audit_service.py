"""Audit logging (v1.0).

Records security-relevant actions as append-only :class:`AuditLog` rows and
exposes a scoped listing for admins. Recording never raises — an auditing
failure must not break the action being audited.
"""
import logging
from typing import Optional

from flask import request

from ..extensions import db
from ..models.auth import AuditLog

logger = logging.getLogger("agentscope")


def record(
    action: str,
    *,
    identity=None,
    organization_id: Optional[int] = None,
    project_id: Optional[int] = None,
    target_type: Optional[str] = None,
    target_id=None,
    metadata: Optional[dict] = None,
    capture_request: bool = True,
) -> Optional[AuditLog]:
    """Persist an audit log entry. Best-effort: swallows its own errors."""
    try:
        user_id = getattr(identity, "user_id", None) if identity else None
        api_key_id = getattr(identity, "api_key_id", None) if identity else None
        if organization_id is None and identity is not None:
            organization_id = getattr(identity, "organization_id", None)

        ip = user_agent = None
        if capture_request and request:
            ip = request.headers.get("X-Forwarded-For", request.remote_addr)
            user_agent = (request.user_agent.string or None) if request.user_agent else None

        entry = AuditLog(
            organization_id=organization_id,
            project_id=project_id,
            user_id=user_id,
            api_key_id=api_key_id,
            action=action,
            target_type=target_type,
            target_id=None if target_id is None else str(target_id),
            ip=ip,
            user_agent=(user_agent or "")[:400] or None,
            log_metadata=metadata,
        )
        db.session.add(entry)
        db.session.commit()
        return entry
    except Exception:  # noqa: BLE001 - auditing must never break the request
        logger.exception("Failed to record audit log for action=%s", action)
        db.session.rollback()
        return None


def list_for_org(org_id: int, page: int, limit: int, action: Optional[str] = None):
    """Return ``(items, total)`` of audit logs for an organization."""
    query = AuditLog.query.filter_by(organization_id=org_id)
    if action:
        query = query.filter(AuditLog.action == action)
    total = query.count()
    items = (
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return items, total
