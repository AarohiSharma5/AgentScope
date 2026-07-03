"""Thread-safe real-time broadcaster — ``LiveTraceManager`` (v0.6).

An in-process publish/subscribe hub that fans events out to every connected
subscriber (SSE or WebSocket). It is transport-agnostic: transports only iterate
:meth:`Subscriber.stream`, so all connection concerns — heartbeats, backpressure,
graceful disconnect, reconnection replay — live here and are unit-testable
without a socket.

Design notes
------------
* **Thread-safe.** Subscriber registration is guarded by a lock; per-subscriber
  delivery uses a thread-safe :class:`queue.Queue`. Broadcasting snapshots the
  subscriber list under the lock, then delivers outside it (a slow consumer
  never blocks the publisher).
* **Backpressure.** Each subscriber has a bounded queue. When it is full, new
  events are dropped (and counted); a subscriber that keeps dropping past
  ``max_dropped`` is disconnected, protecting the server from a stuck client.
* **Heartbeat.** :meth:`Subscriber.stream` emits a heartbeat whenever it has been
  idle for ``heartbeat_interval`` seconds, keeping proxies/clients alive and
  surfacing dead connections promptly.
* **Reconnection.** A bounded ring buffer of recent events lets a reconnecting
  SSE client replay everything after its ``Last-Event-ID``.
* **Per-process.** State is in-memory, so under multiple gunicorn workers each
  worker broadcasts to its own subscribers. A cross-process fan-out (e.g. Redis
  pub/sub) can be layered on later without changing this interface.
"""
import itertools
import logging
import queue
import threading
from collections import deque
from typing import Iterator, Optional

from .events import Event, EventType, heartbeat_event, new_event

logger = logging.getLogger("agentscope")

DEFAULT_QUEUE_SIZE = 1000
DEFAULT_HEARTBEAT_INTERVAL = 15.0
DEFAULT_HISTORY = 500
DEFAULT_MAX_DROPPED = 5000

# Sentinel pushed onto a subscriber's queue to wake a blocked ``stream`` on close.
_CLOSE = object()


class Subscriber:
    """One connected client. Transports iterate :meth:`stream`."""

    def __init__(
        self,
        subscriber_id: int,
        topics: Optional[frozenset] = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
        max_dropped: int = DEFAULT_MAX_DROPPED,
    ) -> None:
        self.id = subscriber_id
        self.topics = topics
        self.heartbeat_interval = heartbeat_interval
        self.max_dropped = max_dropped
        self.dropped = 0
        self.delivered = 0
        self._queue: "queue.Queue" = queue.Queue(maxsize=queue_size)
        self._closed = threading.Event()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def wants(self, event: Event) -> bool:
        """Whether this subscriber's filter matches the event."""
        if self.topics is None:
            return True
        return event.type in self.topics or event.topic in self.topics

    def put(self, event: Event) -> bool:
        """Enqueue an event (non-blocking). Returns False if dropped/closed.

        Backpressure policy: drop-newest on a full queue and count it; disconnect
        a subscriber that keeps dropping past ``max_dropped``.
        """
        if self._closed.is_set():
            return False
        try:
            self._queue.put_nowait(event)
            return True
        except queue.Full:
            self.dropped += 1
            if self.max_dropped and self.dropped >= self.max_dropped:
                logger.warning(
                    "stream subscriber %s exceeded drop limit (%s); disconnecting",
                    self.id, self.dropped,
                )
                self.close()
            return False

    def close(self) -> None:
        """Mark closed and wake a blocked :meth:`stream`."""
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._queue.put_nowait(_CLOSE)
        except queue.Full:
            pass

    def stream(self) -> Iterator[Event]:
        """Yield events until closed, emitting a heartbeat when idle.

        This is the single loop both the SSE and WebSocket transports consume.
        A ``GeneratorExit`` (client hung up) closes the subscriber gracefully.
        """
        try:
            while not self._closed.is_set():
                try:
                    item = self._queue.get(timeout=self.heartbeat_interval)
                except queue.Empty:
                    yield heartbeat_event()
                    continue
                if item is _CLOSE:
                    break
                self.delivered += 1
                yield item
        except GeneratorExit:
            # Consumer (transport) closed the generator — disconnect cleanly.
            raise
        finally:
            self.close()


class LiveTraceManager:
    """In-process pub/sub hub broadcasting platform events to subscribers."""

    def __init__(
        self,
        history: int = DEFAULT_HISTORY,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
        max_dropped: int = DEFAULT_MAX_DROPPED,
    ) -> None:
        self.queue_size = queue_size
        self.heartbeat_interval = heartbeat_interval
        self.max_dropped = max_dropped
        self._subscribers: dict[int, Subscriber] = {}
        self._lock = threading.RLock()
        self._sub_ids = itertools.count(1)
        self._event_ids = itertools.count(1)
        self._history: "deque[Event]" = deque(maxlen=history)

    # -- Subscription -------------------------------------------------------

    def subscribe(
        self,
        topics: Optional[frozenset] = None,
        last_event_id: Optional[int] = None,
        queue_size: Optional[int] = None,
        heartbeat_interval: Optional[float] = None,
    ) -> Subscriber:
        """Register a subscriber, replaying missed events after ``last_event_id``."""
        subscriber = Subscriber(
            subscriber_id=next(self._sub_ids),
            topics=topics,
            queue_size=queue_size or self.queue_size,
            heartbeat_interval=heartbeat_interval or self.heartbeat_interval,
            max_dropped=self.max_dropped,
        )
        with self._lock:
            self._subscribers[subscriber.id] = subscriber
            if last_event_id is not None:
                for event in self._history:
                    if event.id > last_event_id and subscriber.wants(event):
                        subscriber.put(event)
            total = len(self._subscribers)
        logger.info("stream subscriber %s connected (%s active)", subscriber.id, total)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        """Deregister and close a subscriber (idempotent, graceful)."""
        with self._lock:
            self._subscribers.pop(subscriber.id, None)
            total = len(self._subscribers)
        subscriber.close()
        logger.info("stream subscriber %s disconnected (%s active)", subscriber.id, total)

    # -- Publishing ---------------------------------------------------------

    def publish(self, event_type: str, data: Optional[dict] = None, **fields) -> Event:
        """Build, store and fan out an event to all matching subscribers."""
        payload = dict(data or {})
        payload.update(fields)
        event = new_event(next(self._event_ids), event_type, payload)

        with self._lock:
            self._history.append(event)
            targets = list(self._subscribers.values())

        for subscriber in targets:
            if subscriber.wants(event):
                subscriber.put(event)
        return event

    def emit(self, event_type: str, data: Optional[dict] = None, **fields) -> Optional[Event]:
        """Exception-safe :meth:`publish` for use from the service layer.

        Emission must never disrupt persistence, so any failure here is logged
        and swallowed. Returns the event, or ``None`` on failure.
        """
        try:
            return self.publish(event_type, data, **fields)
        except Exception:  # noqa: BLE001 - streaming must never break the caller
            logger.exception("failed to emit stream event %s", event_type)
            return None

    # -- Introspection / lifecycle -----------------------------------------

    def stats(self) -> dict:
        """Current broadcaster statistics (for a status endpoint / debugging)."""
        with self._lock:
            subs = list(self._subscribers.values())
        return {
            "subscribers": len(subs),
            "history_size": len(self._history),
            "events_published": self._peek_event_count(),
            "total_dropped": sum(s.dropped for s in subs),
            "total_delivered": sum(s.delivered for s in subs),
            "heartbeat_interval": self.heartbeat_interval,
        }

    def _peek_event_count(self) -> int:
        # itertools.count has no public "current"; the last stored event's id is
        # the best cheap indicator of how many events have been published.
        return self._history[-1].id if self._history else 0

    def reset(self) -> None:
        """Drop all subscribers and history (primarily for tests)."""
        with self._lock:
            subs = list(self._subscribers.values())
            self._subscribers.clear()
            self._history.clear()
        for subscriber in subs:
            subscriber.close()

    def shutdown(self) -> None:
        """Close every subscriber (e.g. on app teardown)."""
        with self._lock:
            subs = list(self._subscribers.values())
            self._subscribers.clear()
        for subscriber in subs:
            subscriber.close()
        logger.info("LiveTraceManager shut down (%s subscribers closed)", len(subs))


#: Process-wide singleton used by the service layer and transports.
live_trace_manager = LiveTraceManager()


def emit(event_type: str, data: Optional[dict] = None, **fields) -> Optional[Event]:
    """Module-level, exception-safe emit against the process singleton."""
    return live_trace_manager.emit(event_type, data, **fields)


__all__ = ["LiveTraceManager", "Subscriber", "live_trace_manager", "emit", "EventType"]
