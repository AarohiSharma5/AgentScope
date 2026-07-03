"""Real-time streaming subsystem (v0.6).

Exposes the process-wide :data:`live_trace_manager`, the exception-safe
:func:`emit` helper used by the service layer, the :class:`EventType` taxonomy
and the :class:`Event` model. Transports live in :mod:`app.routes.stream`.
"""
from .events import ALL_EVENT_TYPES, ALL_TOPICS, Event, EventType, parse_topics
from .manager import LiveTraceManager, Subscriber, emit, live_trace_manager

__all__ = [
    "ALL_EVENT_TYPES",
    "ALL_TOPICS",
    "Event",
    "EventType",
    "LiveTraceManager",
    "Subscriber",
    "emit",
    "live_trace_manager",
    "parse_topics",
]
