"""REST endpoints for multi-agent workflows, conversations and messages (v0.4).

Routes stay thin: parse and validate input, delegate all querying/aggregation to
the service layer, and shape responses via reusable serializers. No business
logic or SQLAlchemy session access lives here.

Response conventions (shared with the rest of the API):

* Collections -> ``{"data": [...], "pagination": {page, limit, total, pages}}``
* Single resource -> the serialized object directly
* Errors -> ``{"error": message, "details": {...optional}}`` (see ``errors``)
"""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from ..errors import error_response
from ..models.agent_trace import AgentStatus
from ..models.workflow_trace import MessageType
from ..serializers.message import serialize_message
from ..serializers.workflow import (
    serialize_conversation_detail,
    serialize_conversation_summary,
    serialize_workflow_detail,
    serialize_workflow_summary,
)
from ..services import workflow_service
from ..services.message_service import message_service
from ..utils.pagination import PaginationError, paginated, parse_page_limit

workflows_bp = Blueprint("workflows", __name__)

_CONVERSATION_STATUSES = {
    AgentStatus.PENDING,
    AgentStatus.RUNNING,
    AgentStatus.SUCCESS,
    AgentStatus.FAILED,
    AgentStatus.CANCELLED,
    AgentStatus.TIMEOUT,
}


def _clean(value):
    """Trim a query-string value to a non-empty string or None."""
    if value is None:
        return None
    return value.strip() or None


def _parse_when(value):
    """Parse an ISO date or datetime string into a ``datetime`` (or None).

    Accepts a trailing 'Z' (UTC) and bare dates ("2026-07-20") alike.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


# -- Workflows --------------------------------------------------------------


@workflows_bp.get("/workflows")
def list_workflows():
    """List workflow definitions with pagination, search, filtering and sorting."""
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)

    q = _clean(request.args.get("q"))
    sort = request.args.get("sort", "-created_at")
    if not workflow_service.is_valid_workflow_sort(sort):
        return error_response(
            "invalid sort field",
            400,
            {
                "allowed": sorted(workflow_service.WORKFLOW_SORTABLE),
                "hint": "prefix with '-' for descending, e.g. -created_at",
            },
        )

    items, total = workflow_service.list_workflows(page=page, limit=limit, q=q, sort=sort)
    return jsonify(paginated([serialize_workflow_summary(w) for w in items], page, limit, total))


@workflows_bp.get("/workflows/<int:workflow_id>")
def get_workflow(workflow_id: int):
    """Return a workflow with its nodes, edges and execution history."""
    workflow = workflow_service.get_workflow(workflow_id)
    if workflow is None:
        return error_response("workflow not found", 404)
    return jsonify(serialize_workflow_detail(workflow))


# -- Conversations ----------------------------------------------------------


@workflows_bp.get("/conversations")
def list_conversations():
    """List conversations with pagination, search, filtering and sorting."""
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)

    status = request.args.get("status")
    if status is not None and status not in _CONVERSATION_STATUSES:
        return error_response(
            "invalid status", 400, {"allowed": sorted(_CONVERSATION_STATUSES)}
        )

    q = _clean(request.args.get("q"))
    sort = request.args.get("sort", "-created_at")
    if not workflow_service.is_valid_conversation_sort(sort):
        return error_response(
            "invalid sort field",
            400,
            {
                "allowed": sorted(workflow_service.CONVERSATION_SORTABLE),
                "hint": "prefix with '-' for descending, e.g. -created_at",
            },
        )

    # Optional created_at bounds. ``on=YYYY-MM-DD`` is a convenience for a single
    # calendar day (used by the "investigate a change" deep-link).
    since = _parse_when(request.args.get("since"))
    until = _parse_when(request.args.get("until"))
    on = _parse_when(request.args.get("on"))
    if on is not None:
        day = on.replace(hour=0, minute=0, second=0, microsecond=0)
        since = day
        until = day + timedelta(days=1)

    items, total = workflow_service.list_conversations(
        page=page, limit=limit, q=q, status=status, sort=sort, since=since, until=until
    )
    return jsonify(
        paginated([serialize_conversation_summary(c) for c in items], page, limit, total)
    )


@workflows_bp.get("/conversations/<int:conversation_id>")
def get_conversation(conversation_id: int):
    """Return a conversation with its agent tree, messages, timeline and steps."""
    conversation = workflow_service.get_conversation(conversation_id)
    if conversation is None:
        return error_response("conversation not found", 404)
    return jsonify(serialize_conversation_detail(conversation))


# -- Messages ---------------------------------------------------------------


@workflows_bp.get("/messages")
def list_messages():
    """List messages filtered by sender, receiver, conversation and free-text search."""
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)

    message_type = request.args.get("message_type")
    if message_type is not None and message_type not in MessageType.ALL:
        return error_response(
            "invalid message_type", 400, {"allowed": sorted(MessageType.ALL)}
        )

    def _int_arg(name):
        raw = request.args.get(name)
        if raw is None or raw.strip() == "":
            return None
        return int(raw)

    try:
        sender = _int_arg("sender")
        receiver = _int_arg("receiver")
        conversation = _int_arg("conversation")
    except (TypeError, ValueError):
        return error_response("sender, receiver and conversation must be integers", 400)

    items, total = message_service.search(
        text=_clean(request.args.get("q")),
        conversation_run_id=conversation,
        message_type=message_type,
        sender_node_id=sender,
        receiver_node_id=receiver,
        limit=limit,
        offset=(page - 1) * limit,
    )
    return jsonify(paginated([serialize_message(m) for m in items], page, limit, total))


# -- Dashboard --------------------------------------------------------------


@workflows_bp.get("/dashboard/workflow-metrics")
def workflow_metrics():
    """Return aggregate multi-agent workflow metrics for the dashboard."""
    return jsonify(workflow_service.get_workflow_metrics())
