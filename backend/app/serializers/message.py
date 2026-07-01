"""Serializers for the agent communication layer (v0.4)."""
from ..models.workflow_trace import AgentMessage
from .common import iso as _iso


def serialize_message(message: AgentMessage) -> dict:
    """Serialize an :class:`AgentMessage` into a JSON-ready dict.

    Records every required field: sender, receiver, timestamp, latency, token
    usage and metadata (plus reply threading and conversation linkage).
    """
    sender = message.sender
    receiver = message.receiver
    return {
        "id": message.id,
        "conversation_run_id": message.conversation_run_id,
        "message_type": message.message_type,
        "content": message.content,
        "sender_node_id": message.sender_node_id,
        "sender": sender.display_name if sender else None,
        "sender_role": sender.agent_role if sender else None,
        "receiver_node_id": message.receiver_node_id,
        "receiver": receiver.display_name if receiver else None,
        "receiver_role": receiver.agent_role if receiver else None,
        "reply_to_id": message.reply_to_id,
        "token_usage": message.token_usage,
        "latency_ms": message.latency_ms,
        "metadata": message.message_metadata,
        "timestamp": _iso(message.created_at),
    }


def serialize_timeline_event(message: AgentMessage) -> dict:
    """Serialize a message as a compact timeline event."""
    sender = message.sender
    receiver = message.receiver
    return {
        "id": message.id,
        "message_type": message.message_type,
        "from": sender.display_name if sender else None,
        "to": receiver.display_name if receiver else "broadcast",
        "reply_to_id": message.reply_to_id,
        "latency_ms": message.latency_ms,
        "token_usage": message.token_usage,
        "timestamp": _iso(message.created_at),
    }
