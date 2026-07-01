"""Agent communication layer (v0.4).

A reusable service for agents to communicate through **stored** messages. All
SQLAlchemy access lives here (never in routes). Every message records its
sender, receiver, timestamp, latency, token usage and metadata.

Supports:

* **direct** messages (one sender -> one receiver),
* **broadcast** (one sender -> every other participant in a conversation, or an
  explicit receiver list), linked by a shared ``broadcast_id``,
* **reply** (threaded back to the message it answers, addressed to its sender),
* **conversation history** (ordered transcript of a conversation),
* **message search** (full-text on content plus structured filters), and
* **message timeline** (compact, chronologically-ordered events).

Message types are constrained to :class:`~app.models.workflow_trace.MessageType`.
"""
import logging
import uuid
from typing import Optional, Union

from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models.workflow_trace import AgentMessage, AgentNode, MessageType
from ..services import workflow_service

logger = logging.getLogger("agentscope")

NodeRef = Union[int, AgentNode]
MessageRef = Union[int, AgentMessage]


class MessageService:
    """Reusable service for sending, storing and querying agent messages."""

    # -- Sending ------------------------------------------------------------

    def send(
        self,
        sender: NodeRef,
        receiver: Optional[NodeRef] = None,
        message_type: str = MessageType.INSTRUCTION,
        content: Optional[str] = None,
        token_usage: Optional[dict] = None,
        latency_ms: Optional[float] = None,
        metadata: Optional[dict] = None,
        reply_to: Optional[MessageRef] = None,
        conversation_run_id: Optional[int] = None,
    ) -> AgentMessage:
        """Send (persist) a direct message from ``sender`` to ``receiver``.

        ``receiver`` may be ``None`` for an undirected/broadcast-style message.
        The conversation is inferred from the sender when not supplied.
        """
        self._validate_type(message_type)
        sender_id = self._node_id(sender)
        receiver_id = self._node_id(receiver)
        reply_to_id = self._message_id(reply_to)
        if conversation_run_id is None:
            conversation_run_id = self._conversation_of(sender_id)

        return workflow_service.create_agent_message(
            sender_node_id=sender_id,
            receiver_node_id=receiver_id,
            message_type=message_type,
            content=content,
            token_usage=token_usage,
            latency_ms=latency_ms,
            metadata=metadata,
            conversation_run_id=conversation_run_id,
            reply_to_id=reply_to_id,
        )

    def broadcast(
        self,
        sender: NodeRef,
        message_type: str = MessageType.INSTRUCTION,
        content: Optional[str] = None,
        receivers: Optional[list[NodeRef]] = None,
        token_usage: Optional[dict] = None,
        latency_ms: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> list[AgentMessage]:
        """Broadcast a message to several receivers (one stored row each).

        When ``receivers`` is omitted, every other agent in the sender's
        conversation receives it. All rows share a ``broadcast_id`` in their
        metadata so the broadcast can be reconstructed.
        """
        sender_id = self._node_id(sender)
        conversation_run_id = self._conversation_of(sender_id)

        if receivers is None:
            receiver_ids = self._other_node_ids(conversation_run_id, sender_id)
        else:
            receiver_ids = [self._node_id(r) for r in receivers]

        broadcast_id = uuid.uuid4().hex
        base_metadata = dict(metadata or {})
        base_metadata["broadcast_id"] = broadcast_id

        messages = [
            self.send(
                sender=sender_id,
                receiver=receiver_id,
                message_type=message_type,
                content=content,
                token_usage=token_usage,
                latency_ms=latency_ms,
                metadata=base_metadata,
                conversation_run_id=conversation_run_id,
            )
            for receiver_id in receiver_ids
        ]
        logger.debug(
            "Broadcast id=%s from sender=%s to %s receivers",
            broadcast_id, sender_id, len(messages),
        )
        return messages

    def reply(
        self,
        to_message: MessageRef,
        sender: NodeRef,
        message_type: str = MessageType.ANSWER,
        content: Optional[str] = None,
        token_usage: Optional[dict] = None,
        latency_ms: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> AgentMessage:
        """Reply to a message, addressing the reply back to its original sender."""
        original = self._get_or_raise(to_message)
        return self.send(
            sender=sender,
            receiver=original.sender_node_id,
            message_type=message_type,
            content=content,
            token_usage=token_usage,
            latency_ms=latency_ms,
            metadata=metadata,
            reply_to=original.id,
            conversation_run_id=original.conversation_run_id,
        )

    # -- Querying -----------------------------------------------------------

    def conversation_history(
        self,
        conversation_run_id: int,
        ascending: bool = True,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[AgentMessage]:
        """Return a conversation's transcript ordered by time."""
        order = AgentMessage.created_at.asc() if ascending else AgentMessage.created_at.desc()
        query = (
            db.session.query(AgentMessage)
            .options(*self._participant_loaders())
            .filter(AgentMessage.conversation_run_id == conversation_run_id)
            .order_by(order, AgentMessage.id.asc() if ascending else AgentMessage.id.desc())
        )
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def thread(self, message: MessageRef) -> list[AgentMessage]:
        """Return a message together with its direct replies, in order."""
        original = self._get_or_raise(message)
        replies = (
            db.session.query(AgentMessage)
            .options(*self._participant_loaders())
            .filter(AgentMessage.reply_to_id == original.id)
            .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
            .all()
        )
        return [original, *replies]

    def search(
        self,
        text: Optional[str] = None,
        conversation_run_id: Optional[int] = None,
        message_type: Optional[str] = None,
        sender_node_id: Optional[int] = None,
        receiver_node_id: Optional[int] = None,
        reply_to_id: Optional[int] = None,
        ascending: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AgentMessage], int]:
        """Search messages by free text and/or structured filters.

        Returns ``(messages, total)`` where ``total`` is the unpaginated count.
        Text matching is case-insensitive via ``ILIKE`` (portable across SQLite
        and PostgreSQL).
        """
        query = db.session.query(AgentMessage)
        if conversation_run_id is not None:
            query = query.filter(AgentMessage.conversation_run_id == conversation_run_id)
        if message_type is not None:
            query = query.filter(AgentMessage.message_type == message_type)
        if sender_node_id is not None:
            query = query.filter(AgentMessage.sender_node_id == sender_node_id)
        if receiver_node_id is not None:
            query = query.filter(AgentMessage.receiver_node_id == receiver_node_id)
        if reply_to_id is not None:
            query = query.filter(AgentMessage.reply_to_id == reply_to_id)
        if text:
            query = query.filter(AgentMessage.content.ilike(f"%{text}%"))

        total = query.count()
        order = AgentMessage.created_at.asc() if ascending else AgentMessage.created_at.desc()
        items = (
            query.options(*self._participant_loaders())
            .order_by(order, AgentMessage.id.asc() if ascending else AgentMessage.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return items, total

    def timeline(self, conversation_run_id: int) -> list[AgentMessage]:
        """Return a conversation's messages in chronological order for a timeline."""
        return self.conversation_history(conversation_run_id, ascending=True)

    def get_message(self, message_id: int) -> Optional[AgentMessage]:
        """Return a single message by id, or None."""
        return db.session.get(AgentMessage, message_id)

    # -- Internal helpers ---------------------------------------------------

    @staticmethod
    def _participant_loaders():
        """Eager-load sender/receiver to avoid N+1 queries when serializing."""
        return (
            selectinload(AgentMessage.sender),
            selectinload(AgentMessage.receiver),
        )

    @staticmethod
    def _validate_type(message_type: str) -> None:
        if message_type not in MessageType.ALL:
            raise ValueError(
                f"unknown message_type {message_type!r}; "
                f"expected one of {sorted(MessageType.ALL)}"
            )

    @staticmethod
    def _node_id(node: Optional[NodeRef]) -> Optional[int]:
        if node is None:
            return None
        return node.id if isinstance(node, AgentNode) else int(node)

    @staticmethod
    def _message_id(message: Optional[MessageRef]) -> Optional[int]:
        if message is None:
            return None
        return message.id if isinstance(message, AgentMessage) else int(message)

    def _get_or_raise(self, message: MessageRef) -> AgentMessage:
        if isinstance(message, AgentMessage):
            return message
        found = self.get_message(int(message))
        if found is None:
            raise ValueError(f"message {message} not found")
        return found

    @staticmethod
    def _conversation_of(node_id: Optional[int]) -> Optional[int]:
        if node_id is None:
            return None
        node = db.session.get(AgentNode, node_id)
        if node is None:
            raise ValueError(f"agent node {node_id} not found")
        return node.conversation_run_id

    @staticmethod
    def _other_node_ids(conversation_run_id: Optional[int], sender_id: int) -> list[int]:
        if conversation_run_id is None:
            return []
        rows = (
            db.session.query(AgentNode.id)
            .filter(
                AgentNode.conversation_run_id == conversation_run_id,
                AgentNode.id != sender_id,
            )
            .order_by(AgentNode.execution_order.asc(), AgentNode.id.asc())
            .all()
        )
        return [row[0] for row in rows]


# A shared, stateless instance for convenient reuse (e.g. from the SDK).
message_service = MessageService()
