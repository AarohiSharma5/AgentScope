"""Cross-process fan-out brokers for real-time streaming.

The in-process :class:`~app.streaming.manager.LiveTraceManager` only reaches
subscribers on the **same** worker. Under multiple gunicorn workers, an event
emitted on worker A must also reach a client whose SSE/WebSocket connection is
pinned to worker B. A *broker* bridges that gap:

* the manager asks the broker for each event's ``id`` (so ids stay globally
  monotonic for ``Last-Event-ID`` reconnection), and
* publishes every locally-produced event to the broker; a background listener
  feeds events produced on *other* workers back into this manager's local
  fan-out.

Two implementations:

* :class:`InProcessBroker` (default) — no external dependency. Ids come from a
  local counter and nothing crosses a process boundary, i.e. exactly the old
  single-worker behaviour.
* :class:`RedisBroker` — publishes events to a Redis pub/sub channel and runs a
  listener thread that feeds remote events back in. Ids come from a Redis
  ``INCR`` counter so reconnection stays coherent across workers. Degrades
  gracefully: if Redis is unreachable, id allocation falls back to a local
  counter and publish failures are logged and swallowed (streaming must never
  break the request that produced the event).

Selection is by config: a ``STREAM_BROKER_URL`` (``redis://…``) turns on the
Redis broker; unset keeps the in-process one.
"""
from __future__ import annotations

import itertools
import json
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger("agentscope")

#: Callback the manager registers to receive events produced by *other* workers.
RemoteHandler = Callable[[dict], None]


class InProcessBroker:
    """Default single-process broker: local ids, no cross-process fan-out."""

    def __init__(self) -> None:
        self._ids = itertools.count(1)

    def next_id(self) -> int:
        return next(self._ids)

    def publish(self, wire: dict) -> None:  # noqa: ARG002 - nothing to fan out
        return None

    def history_since(self, last_event_id: int, limit: Optional[int] = None):  # noqa: ARG002
        """No shared history — the manager replays from its local ring buffer."""
        return None

    def start(self, on_remote: RemoteHandler) -> None:  # noqa: ARG002
        return None

    def stop(self) -> None:
        return None


class RedisBroker:
    """Redis pub/sub broker for cross-worker event fan-out."""

    DEFAULT_CHANNEL = "agentscope:stream:events"
    SEQ_KEY = "agentscope:stream:seq"
    HISTORY_KEY = "agentscope:stream:history"
    DEFAULT_HISTORY_MAXLEN = 1000
    DEFAULT_HISTORY_TTL = 86400  # seconds; keeps the buffer from living forever

    def __init__(
        self,
        url: str,
        channel: str = DEFAULT_CHANNEL,
        history_maxlen: int = DEFAULT_HISTORY_MAXLEN,
        history_ttl: int = DEFAULT_HISTORY_TTL,
    ) -> None:
        import redis  # lazy import: only required when a broker URL is configured

        # ``from_url`` is lazy — no socket is opened until the first command, so
        # constructing the broker never blocks app startup on Redis being up.
        self._redis = redis.Redis.from_url(url, socket_timeout=5)
        self._channel = channel
        self._history_maxlen = history_maxlen
        self._history_ttl = history_ttl
        self._local_ids = itertools.count(1)
        self._on_remote: Optional[RemoteHandler] = None
        self._pubsub = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def next_id(self) -> int:
        """Globally-monotonic id via Redis ``INCR``; local fallback if Redis is down."""
        try:
            return int(self._redis.incr(self.SEQ_KEY))
        except Exception:  # noqa: BLE001 - never break emission on a Redis hiccup
            logger.warning("stream broker INCR failed; using local id fallback", exc_info=True)
            return next(self._local_ids)

    def publish(self, wire: dict) -> None:
        # Persist to the shared history first (durable, cluster-wide replay)…
        self._append_history(wire)
        # …then fan the event out live to peer workers.
        try:
            self._redis.publish(self._channel, json.dumps(wire))
        except Exception:  # noqa: BLE001 - publish is best-effort
            logger.warning("stream broker publish failed", exc_info=True)

    def _append_history(self, wire: dict) -> None:
        """Store an event in a capped, shared sorted set (score = event id).

        Any worker can then replay recent events on ``Last-Event-ID`` reconnect,
        regardless of which worker produced them or when this worker started —
        which the per-worker in-memory buffer cannot do. Best-effort: a Redis
        hiccup must never break emission.
        """
        eid = wire.get("id")
        if not eid:
            return
        try:
            pipe = self._redis.pipeline()
            pipe.zadd(self.HISTORY_KEY, {json.dumps(wire): eid})
            # Trim to the newest ``history_maxlen`` (drop the lowest-scored ids).
            pipe.zremrangebyrank(self.HISTORY_KEY, 0, -self._history_maxlen - 1)
            pipe.expire(self.HISTORY_KEY, self._history_ttl)
            pipe.execute()
        except Exception:  # noqa: BLE001 - history is best-effort
            logger.warning("stream broker history append failed", exc_info=True)

    def history_since(self, last_event_id: int, limit: Optional[int] = None):
        """Return wire dicts for events with ``id > last_event_id`` (oldest→newest).

        Returns ``None`` on a Redis error so the manager falls back to its local
        ring buffer rather than losing replay entirely.
        """
        num = limit or self._history_maxlen
        try:
            raw = self._redis.zrangebyscore(
                self.HISTORY_KEY, f"({last_event_id}", "+inf", start=0, num=num
            )
        except Exception:  # noqa: BLE001
            logger.warning("stream broker history read failed", exc_info=True)
            return None
        out = []
        for item in raw:
            if isinstance(item, bytes):
                item = item.decode("utf-8", "replace")
            try:
                out.append(json.loads(item))
            except (ValueError, TypeError):
                continue
        return out

    def start(self, on_remote: RemoteHandler) -> None:
        self._on_remote = on_remote
        self._thread = threading.Thread(
            target=self._listen, name="agentscope-stream-broker", daemon=True
        )
        self._thread.start()

    def _subscribe(self) -> None:
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        self._pubsub.subscribe(self._channel)

    def _listen(self) -> None:
        """Deliver peer events into the local manager until stopped.

        Resilient to Redis blips: on any error it drops the pubsub, backs off
        and re-subscribes, so a transient outage doesn't kill live streaming.
        """
        while not self._stop.is_set():
            try:
                if self._pubsub is None:
                    self._subscribe()
                message = self._pubsub.get_message(timeout=1.0)
                if not message:
                    continue
                raw = message.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", "replace")
                wire = json.loads(raw)
                if self._on_remote is not None:
                    self._on_remote(wire)
            except Exception:  # noqa: BLE001 - keep the listener alive
                if self._stop.is_set():
                    break
                logger.warning("stream broker listener error; reconnecting", exc_info=True)
                self._reset_pubsub()
                self._stop.wait(1.0)

    def _reset_pubsub(self) -> None:
        try:
            if self._pubsub is not None:
                self._pubsub.close()
        except Exception:  # noqa: BLE001
            pass
        self._pubsub = None

    def stop(self) -> None:
        self._stop.set()
        self._reset_pubsub()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


def build_broker(url: Optional[str]):
    """Build the configured broker, falling back to in-process on any problem.

    ``url`` empty/None → :class:`InProcessBroker`. A ``redis://`` url →
    :class:`RedisBroker`, unless the ``redis`` package is missing or the URL is
    unusable, in which case we log and fall back so the app still boots.
    """
    if not url:
        return InProcessBroker()
    try:
        broker = RedisBroker(url)
        logger.info("real-time streaming using Redis broker (cross-worker fan-out)")
        return broker
    except ImportError:
        logger.error(
            "STREAM_BROKER_URL is set but the 'redis' package is not installed; "
            "falling back to in-process streaming (single-worker). `pip install redis`."
        )
    except Exception:  # noqa: BLE001
        logger.error("failed to initialise Redis stream broker; falling back", exc_info=True)
    return InProcessBroker()
