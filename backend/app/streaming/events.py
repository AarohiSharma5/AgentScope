"""Event model and taxonomy for real-time streaming (v0.6).

A single :class:`Event` type flows through the :class:`~app.streaming.manager.LiveTraceManager`
to every connected subscriber, over either SSE or WebSocket. Events are small,
JSON-serializable dicts (never ORM objects) so broadcasting is cheap and never
triggers lazy database loads.
"""
import json
from dataclasses import dataclass, field
from typing import Optional

from ..utils.timeutils import utcnow


class EventType:
    """Canonical event names broadcast by the platform."""

    # Request traces (v0.1)
    TRACE_STARTED = "trace.started"
    TRACE_UPDATED = "trace.updated"
    TRACE_FINISHED = "trace.finished"

    # Agent runs (v0.2)
    AGENT_STARTED = "agent.started"
    AGENT_FINISHED = "agent.finished"
    STEP_STARTED = "step.started"
    STEP_FINISHED = "step.finished"

    # Sub-records (v0.2 / v0.3)
    TOOL_STARTED = "tool.started"
    TOOL_FINISHED = "tool.finished"
    RETRIEVER_STARTED = "retriever.started"
    RETRIEVER_FINISHED = "retriever.finished"
    MEMORY_STARTED = "memory.started"
    MEMORY_FINISHED = "memory.finished"

    # Workflows (v0.4) & evaluation (v0.5)
    WORKFLOW_UPDATED = "workflow.updated"
    EVALUATION_FINISHED = "evaluation.finished"

    # Transport-level (not persisted in history, not replayable)
    HEARTBEAT = "heartbeat"


#: Every broadcastable (non-transport) event type.
ALL_EVENT_TYPES = frozenset(
    value
    for key, value in vars(EventType).items()
    if key.isupper() and value != EventType.HEARTBEAT
)

#: Coarse topics (the prefix before the dot) usable for subscription filtering.
ALL_TOPICS = frozenset(t.split(".", 1)[0] for t in ALL_EVENT_TYPES)


@dataclass
class Event:
    """A single broadcastable event.

    ``id`` is a per-manager monotonic sequence number used for SSE reconnection
    (``Last-Event-ID``); heartbeats use ``id=0`` and are never stored.
    """

    id: int
    type: str
    data: dict
    timestamp: str
    # Lazily-computed, cached wire encodings. A single broadcast event is
    # delivered to every subscriber and serialized once per subscriber; caching
    # collapses that to one json.dumps regardless of the fan-out size.
    _sse: Optional[str] = field(default=None, repr=False, compare=False)
    _json: Optional[str] = field(default=None, repr=False, compare=False)

    @property
    def topic(self) -> str:
        """The coarse topic (prefix before the dot), e.g. ``agent``."""
        return self.type.split(".", 1)[0]

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "timestamp": self.timestamp, "data": self.data}

    def to_json(self) -> str:
        """Serialize for a WebSocket text frame (cached)."""
        if self._json is None:
            self._json = json.dumps(self.to_dict())
        return self._json

    def to_sse(self) -> str:
        """Serialize into the Server-Sent Events wire format (cached)."""
        if self._sse is None:
            self._sse = (
                f"id: {self.id}\n"
                f"event: {self.type}\n"
                f"data: {json.dumps(self.data)}\n\n"
            )
        return self._sse


def new_event(event_id: int, event_type: str, data: Optional[dict] = None) -> Event:
    """Build an :class:`Event` with the current UTC timestamp."""
    return Event(
        id=event_id,
        type=event_type,
        data=data or {},
        timestamp=utcnow().isoformat(),
    )


def heartbeat_event() -> Event:
    """A transport-level heartbeat (id 0, not stored in history)."""
    return Event(id=0, type=EventType.HEARTBEAT, data={}, timestamp=utcnow().isoformat())


def parse_topics(raw: Optional[str]) -> Optional[frozenset]:
    """Parse a comma-separated ``events=`` filter into a set of topics/types.

    Returns ``None`` (meaning "everything") when nothing valid is supplied.
    Accepts both coarse topics (``agent``) and exact types (``agent.started``).
    """
    if not raw:
        return None
    wanted = {part.strip() for part in raw.split(",") if part.strip()}
    valid = {w for w in wanted if w in ALL_TOPICS or w in ALL_EVENT_TYPES}
    return frozenset(valid) or None
