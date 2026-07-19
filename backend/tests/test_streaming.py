"""Tests for the v0.6 real-time streaming subsystem.

Covered:
* LiveTraceManager / Subscriber core: delivery, topic filtering, backpressure
  (drop + disconnect), heartbeats, reconnection replay, graceful disconnect and
  thread-safe broadcasting under concurrency.
* Event serialization (SSE + JSON wire formats) and topic parsing.
* The SSE HTTP endpoint (headers + replayed events) via the Flask test client.
* The WebSocket handler logic via a fake socket.
* Non-breaking emission wiring: service-layer calls broadcast events.
"""
import itertools
import threading
import time

import pytest

from app.streaming import Event, EventType, parse_topics
from app.streaming.events import heartbeat_event, new_event
from app.streaming.manager import LiveTraceManager, live_trace_manager


# -- Event model ------------------------------------------------------------


def test_event_sse_and_json_wire_formats():
    event = new_event(7, EventType.AGENT_STARTED, {"run_id": 3})
    sse = event.to_sse()
    assert "id: 7\n" in sse
    assert f"event: {EventType.AGENT_STARTED}\n" in sse
    assert '"run_id": 3' in sse
    assert sse.endswith("\n\n")

    payload = event.to_dict()
    assert payload["id"] == 7
    assert payload["type"] == EventType.AGENT_STARTED
    assert payload["data"] == {"run_id": 3}
    assert "timestamp" in payload
    assert '"type": "agent.started"' in event.to_json()


def test_event_topic_is_prefix():
    assert Event(1, "tool.finished", {}, "t").topic == "tool"


def test_parse_topics():
    assert parse_topics(None) is None
    assert parse_topics("") is None
    assert parse_topics("nonsense") is None  # nothing valid -> everything
    assert parse_topics("agent") == frozenset({"agent"})
    assert parse_topics("agent, tool.finished ,bogus") == frozenset(
        {"agent", "tool.finished"}
    )


# -- Manager: delivery & filtering ------------------------------------------


def test_publish_delivers_to_subscriber():
    mgr = LiveTraceManager(heartbeat_interval=5)
    sub = mgr.subscribe()
    mgr.publish(EventType.TRACE_STARTED, {"trace_id": 1})

    gen = sub.stream()
    event = next(gen)
    assert event.type == EventType.TRACE_STARTED
    assert event.data == {"trace_id": 1}
    mgr.unsubscribe(sub)


def test_topic_filtering_only_matching_events():
    mgr = LiveTraceManager(heartbeat_interval=0.05)
    sub = mgr.subscribe(topics=frozenset({"agent"}))

    mgr.publish(EventType.TRACE_STARTED, {"trace_id": 1})  # filtered out
    mgr.publish(EventType.AGENT_STARTED, {"run_id": 2})  # matches topic
    mgr.publish(EventType.TOOL_FINISHED, {"tool_id": 3})  # filtered out

    gen = sub.stream()
    event = next(gen)
    assert event.type == EventType.AGENT_STARTED
    # Nothing else queued -> next yield is a heartbeat, not another real event.
    assert next(gen).type == EventType.HEARTBEAT
    mgr.unsubscribe(sub)


def test_exact_event_type_filtering():
    mgr = LiveTraceManager(heartbeat_interval=0.05)
    sub = mgr.subscribe(topics=frozenset({"tool.finished"}))
    mgr.publish(EventType.TOOL_STARTED, {"step_id": 1})  # filtered
    mgr.publish(EventType.TOOL_FINISHED, {"tool_id": 2})  # matches
    assert next(sub.stream()).type == EventType.TOOL_FINISHED
    mgr.unsubscribe(sub)


# -- Manager: tenant isolation (C4) -----------------------------------------


def test_org_scoped_subscriber_only_receives_its_own_tenant():
    """A subscriber bound to org 1 never sees org 2's or untagged events."""
    mgr = LiveTraceManager(heartbeat_interval=0.05)
    sub = mgr.subscribe(org_scope=1)
    mgr.publish(EventType.TRACE_STARTED, {"n": 1}, organization_id=1)     # match
    mgr.publish(EventType.TRACE_STARTED, {"n": 2}, organization_id=2)     # other tenant
    mgr.publish(EventType.TRACE_STARTED, {"n": 3}, organization_id=None)  # untagged

    gen = sub.stream()
    assert next(gen).data == {"n": 1}
    # Nothing else is visible -> next yield is a heartbeat, not another tenant's event.
    assert next(gen).type == EventType.HEARTBEAT
    mgr.unsubscribe(sub)


def test_unscoped_subscriber_sees_all_tenants():
    """An unscoped viewer (auth off / super-admin) still sees every event."""
    mgr = LiveTraceManager(queue_size=100, heartbeat_interval=5)
    sub = mgr.subscribe()  # org_scope=None
    mgr.publish(EventType.TRACE_STARTED, {"n": 1}, organization_id=1)
    mgr.publish(EventType.TRACE_STARTED, {"n": 2}, organization_id=2)
    mgr.publish(EventType.TRACE_STARTED, {"n": 3}, organization_id=None)

    gen = sub.stream()
    assert {next(gen).data["n"] for _ in range(3)} == {1, 2, 3}
    mgr.unsubscribe(sub)


def test_no_tenant_scope_sees_nothing():
    """A deny-by-default scope (sentinel org no event carries) receives nothing."""
    mgr = LiveTraceManager(heartbeat_interval=0.05)
    sub = mgr.subscribe(org_scope=-1)
    mgr.publish(EventType.TRACE_STARTED, {"n": 1}, organization_id=1)
    mgr.publish(EventType.TRACE_STARTED, {"n": 2}, organization_id=None)
    assert next(sub.stream()).type == EventType.HEARTBEAT
    mgr.unsubscribe(sub)


def test_reconnect_replay_is_tenant_scoped():
    """History replay on reconnect is filtered to the subscriber's org too."""
    mgr = LiveTraceManager(heartbeat_interval=0.05)
    e1 = mgr.publish(EventType.TRACE_STARTED, {"n": 1}, organization_id=1)
    mgr.publish(EventType.TRACE_STARTED, {"n": 2}, organization_id=2)  # must not replay
    e3 = mgr.publish(EventType.AGENT_STARTED, {"n": 3}, organization_id=1)

    sub = mgr.subscribe(last_event_id=e1.id, org_scope=1)
    gen = sub.stream()
    replayed = next(gen)
    assert replayed.id == e3.id and replayed.data == {"n": 3}
    assert next(gen).type == EventType.HEARTBEAT  # org 2's event was skipped
    mgr.unsubscribe(sub)


# -- Manager: backpressure --------------------------------------------------


def test_backpressure_drops_newest_when_queue_full():
    mgr = LiveTraceManager(queue_size=3, max_dropped=100)
    sub = mgr.subscribe()
    for i in range(10):
        mgr.publish(EventType.STEP_STARTED, {"n": i})

    assert sub.dropped == 7  # 3 kept, 7 dropped
    gen = sub.stream()
    received = [next(gen).data["n"] for _ in range(3)]
    assert received == [0, 1, 2]  # oldest retained (drop-newest policy)
    mgr.unsubscribe(sub)


def test_backpressure_disconnects_persistently_slow_subscriber():
    mgr = LiveTraceManager(queue_size=1, max_dropped=3)
    sub = mgr.subscribe()
    for i in range(10):
        mgr.publish(EventType.STEP_STARTED, {"n": i})
    # After 3 drops the subscriber is force-closed.
    assert sub.closed is True
    assert sub.dropped >= 3


# -- Manager: heartbeats ----------------------------------------------------


def test_heartbeat_emitted_when_idle():
    mgr = LiveTraceManager(heartbeat_interval=0.05)
    sub = mgr.subscribe()
    start = time.monotonic()
    event = next(sub.stream())  # nothing queued -> should heartbeat
    assert event.type == EventType.HEARTBEAT
    assert time.monotonic() - start >= 0.04
    mgr.unsubscribe(sub)


def test_heartbeat_event_has_zero_id():
    assert heartbeat_event().id == 0


# -- Manager: reconnection replay -------------------------------------------


def test_reconnect_replays_missed_events():
    mgr = LiveTraceManager(heartbeat_interval=0.05)
    e1 = mgr.publish(EventType.TRACE_STARTED, {"trace_id": 1})
    e2 = mgr.publish(EventType.AGENT_STARTED, {"run_id": 2})
    e3 = mgr.publish(EventType.STEP_STARTED, {"step_id": 3})

    # Reconnect having last seen e1: should replay e2 and e3 only.
    sub = mgr.subscribe(last_event_id=e1.id)
    gen = sub.stream()
    replayed = [next(gen), next(gen)]
    assert [ev.id for ev in replayed] == [e2.id, e3.id]
    assert next(gen).type == EventType.HEARTBEAT  # caught up
    mgr.unsubscribe(sub)


def test_reconnect_with_latest_id_replays_nothing():
    mgr = LiveTraceManager(heartbeat_interval=0.05)
    mgr.publish(EventType.TRACE_STARTED, {"trace_id": 1})
    latest = mgr.publish(EventType.TRACE_FINISHED, {"trace_id": 1})
    sub = mgr.subscribe(last_event_id=latest.id)
    assert next(sub.stream()).type == EventType.HEARTBEAT
    mgr.unsubscribe(sub)


# -- Manager: graceful disconnect -------------------------------------------


def test_close_stops_stream():
    mgr = LiveTraceManager(heartbeat_interval=5)
    sub = mgr.subscribe()
    collected = []

    def consume():
        for event in sub.stream():
            collected.append(event)

    thread = threading.Thread(target=consume)
    thread.start()
    time.sleep(0.05)
    mgr.unsubscribe(sub)  # graceful close
    thread.join(timeout=2)
    assert not thread.is_alive()  # stream ended promptly


def test_put_after_close_is_noop():
    mgr = LiveTraceManager()
    sub = mgr.subscribe()
    sub.close()
    assert sub.put(new_event(1, EventType.TRACE_STARTED)) is False


def test_unsubscribe_is_idempotent():
    mgr = LiveTraceManager()
    sub = mgr.subscribe()
    mgr.unsubscribe(sub)
    mgr.unsubscribe(sub)  # no error
    assert mgr.stats()["subscribers"] == 0


# -- Manager: thread-safety -------------------------------------------------


def test_thread_safe_broadcasting_under_concurrency():
    mgr = LiveTraceManager(queue_size=100_000, heartbeat_interval=5)
    subs = [mgr.subscribe() for _ in range(4)]
    num_publishers, per_publisher = 8, 200
    total = num_publishers * per_publisher

    def publish():
        for i in range(per_publisher):
            mgr.publish(EventType.STEP_STARTED, {"n": i})

    threads = [threading.Thread(target=publish) for _ in range(num_publishers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every subscriber received every event without loss or corruption.
    for sub in subs:
        assert sub.dropped == 0
        gen = sub.stream()
        received = [next(gen) for _ in range(total)]
        assert len(received) == total
        assert all(ev.type == EventType.STEP_STARTED for ev in received)
        mgr.unsubscribe(sub)


def test_concurrent_subscribe_unsubscribe_is_safe():
    mgr = LiveTraceManager()

    def churn():
        for _ in range(50):
            sub = mgr.subscribe()
            mgr.publish(EventType.AGENT_STARTED, {"x": 1})
            mgr.unsubscribe(sub)

    threads = [threading.Thread(target=churn) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert mgr.stats()["subscribers"] == 0


# -- Manager: emit safety & stats -------------------------------------------


def test_emit_swallows_exceptions(monkeypatch):
    mgr = LiveTraceManager()

    def boom(*_a, **_k):
        raise RuntimeError("nope")

    monkeypatch.setattr(mgr, "publish", boom)
    assert mgr.emit(EventType.TRACE_STARTED, {"trace_id": 1}) is None  # no raise


def test_stats_reports_activity():
    mgr = LiveTraceManager()
    mgr.subscribe()
    mgr.publish(EventType.TRACE_STARTED, {"trace_id": 1})
    stats = mgr.stats()
    assert stats["subscribers"] == 1
    assert stats["history_size"] == 1
    assert stats["events_published"] == 1


def test_shutdown_closes_all_subscribers():
    mgr = LiveTraceManager()
    subs = [mgr.subscribe() for _ in range(3)]
    mgr.shutdown()
    assert mgr.stats()["subscribers"] == 0
    assert all(s.closed for s in subs)


# -- Cross-worker broker (Redis-style fan-out) ------------------------------


class _Bus:
    """A stand-in for a shared pub/sub channel + global id counter (like Redis).

    Publishing on any attached broker delivers the wire message to *every*
    attached broker's remote handler, exactly like Redis pub/sub echoing to all
    subscribers (including the publisher). ``next_id`` is a single shared counter
    across all brokers, modelling ``INCR``.
    """

    def __init__(self):
        self._brokers = []
        self._seq = itertools.count(1)

    def next_id(self):
        return next(self._seq)

    def register(self, broker):
        self._brokers.append(broker)

    def deliver(self, wire):
        for broker in list(self._brokers):
            if broker._on_remote is not None:
                broker._on_remote(wire)


class _BusBroker:
    """Broker implementation backed by a shared :class:`_Bus` (test double)."""

    def __init__(self, bus):
        self._bus = bus
        self._on_remote = None
        bus.register(self)

    def next_id(self):
        return self._bus.next_id()

    def publish(self, wire):
        self._bus.deliver(wire)

    def start(self, on_remote):
        self._on_remote = on_remote

    def stop(self):
        pass


def test_event_wire_roundtrip_preserves_tenant_and_origin():
    event = new_event(9, EventType.TRACE_STARTED, {"n": 1}, organization_id=5)
    event.origin = "worker-x"
    wire = event.to_wire()
    assert wire["organization_id"] == 5 and wire["origin"] == "worker-x"

    back = Event.from_wire(wire)
    assert back.id == 9 and back.organization_id == 5 and back.origin == "worker-x"
    assert back.data == {"n": 1}

    # The client-facing encoding must never leak tenant id or origin.
    assert "organization_id" not in event.to_dict()
    assert "origin" not in event.to_dict()


def test_cross_worker_fan_out_via_broker():
    """An event published on one worker reaches a subscriber on another."""
    bus = _Bus()
    worker_a = LiveTraceManager(heartbeat_interval=5, broker=_BusBroker(bus))
    worker_b = LiveTraceManager(heartbeat_interval=5, broker=_BusBroker(bus))
    sub_b = worker_b.subscribe()

    published = worker_a.publish(EventType.TRACE_STARTED, {"n": 1})

    received = next(sub_b.stream())
    assert received.type == EventType.TRACE_STARTED
    assert received.data == {"n": 1}
    assert received.id == published.id  # global id carried across the bus


def test_broker_does_not_duplicate_local_delivery():
    """The publisher's own subscriber gets exactly one copy (echo is skipped)."""
    bus = _Bus()
    worker_a = LiveTraceManager(heartbeat_interval=0.05, broker=_BusBroker(bus))
    LiveTraceManager(heartbeat_interval=0.05, broker=_BusBroker(bus))  # peer on bus
    sub_a = worker_a.subscribe()

    worker_a.publish(EventType.AGENT_STARTED, {"n": 1})

    stream = sub_a.stream()
    first = next(stream)
    assert first.type == EventType.AGENT_STARTED
    # If the echo were re-delivered locally we'd get a second AGENT_STARTED;
    # instead the idle stream yields a heartbeat.
    assert next(stream).type == EventType.HEARTBEAT


def test_cross_worker_respects_tenant_scope():
    bus = _Bus()
    worker_a = LiveTraceManager(heartbeat_interval=0.05, broker=_BusBroker(bus))
    worker_b = LiveTraceManager(heartbeat_interval=0.05, broker=_BusBroker(bus))
    sub_org1 = worker_b.subscribe(org_scope=1)

    worker_a.publish(EventType.TRACE_STARTED, {"n": 1}, organization_id=2)  # other tenant
    worker_a.publish(EventType.TRACE_STARTED, {"n": 2}, organization_id=1)  # matches

    got = next(sub_org1.stream())
    assert got.data == {"n": 2}


def test_broker_ids_are_globally_monotonic():
    bus = _Bus()
    worker_a = LiveTraceManager(broker=_BusBroker(bus))
    worker_b = LiveTraceManager(broker=_BusBroker(bus))
    e1 = worker_a.publish(EventType.TRACE_STARTED, {})
    e2 = worker_b.publish(EventType.TRACE_STARTED, {})
    e3 = worker_a.publish(EventType.TRACE_STARTED, {})
    assert e1.id < e2.id < e3.id


def test_build_broker_defaults_to_in_process():
    from app.streaming.broker import InProcessBroker, build_broker

    assert isinstance(build_broker(None), InProcessBroker)
    assert isinstance(build_broker(""), InProcessBroker)


def test_build_broker_falls_back_when_redis_unavailable():
    # A syntactically-fine but unusable URL must not raise; it falls back so the
    # app still boots. (No connection is attempted at build time.)
    from app.streaming.broker import build_broker

    broker = build_broker("redis://nonexistent-host:6379/0")
    # Either a RedisBroker (lazy, not yet connected) or in-process fallback — both
    # are acceptable; the contract is simply "did not raise".
    assert hasattr(broker, "next_id") and hasattr(broker, "publish")


# -- SSE HTTP endpoint ------------------------------------------------------


@pytest.fixture()
def reset_global_manager():
    live_trace_manager.reset()
    yield
    live_trace_manager.reset()


def _read_chunks(response, count):
    """Read a bounded number of decoded SSE chunks from a streaming response."""
    iterator = response.iter_encoded()
    chunks = []
    for _ in range(count):
        chunks.append(next(iterator).decode())
    return chunks


def test_sse_endpoint_headers_and_replay(client, app, reset_global_manager):
    app.config["STREAM_HEARTBEAT_INTERVAL"] = 0.1
    live_trace_manager.publish(EventType.TRACE_STARTED, {"trace_id": 42})
    live_trace_manager.publish(EventType.AGENT_STARTED, {"run_id": 7})

    resp = client.get("/api/stream?last_event_id=0")
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"
    assert resp.headers["Cache-Control"] == "no-cache"
    assert resp.headers["X-Accel-Buffering"] == "no"

    # retry line + the two replayed events.
    chunks = _read_chunks(resp, 3)
    resp.close()
    assert chunks[0].startswith("retry:")
    assert "event: trace.started" in chunks[1]
    assert '"trace_id": 42' in chunks[1]
    assert "event: agent.started" in chunks[2]


def test_sse_endpoint_topic_filter(client, app, reset_global_manager):
    app.config["STREAM_HEARTBEAT_INTERVAL"] = 0.1
    live_trace_manager.publish(EventType.TRACE_STARTED, {"trace_id": 1})
    live_trace_manager.publish(EventType.AGENT_STARTED, {"run_id": 2})

    resp = client.get("/api/stream?events=agent&last_event_id=0")
    chunks = _read_chunks(resp, 2)  # retry line + only the agent event
    resp.close()
    assert "event: agent.started" in chunks[1]
    assert "trace.started" not in "".join(chunks)


def test_stream_info_endpoint(client, reset_global_manager):
    resp = client.get("/api/stream/info")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "subscribers" in body
    assert EventType.EVALUATION_FINISHED in body["events"]


# -- WebSocket handler ------------------------------------------------------


class _FakeWS:
    """Minimal stand-in for a flask-sock WebSocket connection."""

    def __init__(self, query="", stop_after=None):
        self.environ = {"QUERY_STRING": query}
        self.sent = []
        self.stop_after = stop_after

    def send(self, message):
        from simple_websocket import ConnectionClosed

        self.sent.append(message)
        if self.stop_after is not None and len(self.sent) >= self.stop_after:
            raise ConnectionClosed()


class _FakeSock:
    """Captures the handler registered by ``register_websocket``."""

    def __init__(self):
        self.handler = None

    def route(self, _path):
        def decorator(func):
            self.handler = func
            return func

        return decorator


def test_websocket_handler_streams_and_disconnects(app, reset_global_manager):
    from app.routes.stream import register_websocket

    sock = _FakeSock()
    register_websocket(sock)
    assert sock.handler is not None

    live_trace_manager.publish(EventType.TRACE_STARTED, {"trace_id": 5})
    live_trace_manager.publish(EventType.AGENT_FINISHED, {"run_id": 9})

    ws = _FakeWS(query="last_event_id=0", stop_after=2)
    with app.app_context():
        sock.handler(ws)  # returns when ConnectionClosed is raised on 2nd send

    assert len(ws.sent) == 2
    assert '"type": "trace.started"' in ws.sent[0]
    assert '"trace_id": 5' in ws.sent[0]
    # Graceful disconnect deregistered the subscriber.
    assert live_trace_manager.stats()["subscribers"] == 0


# -- Emission integration (non-breaking) ------------------------------------


def test_module_emit_tags_org_none_outside_request(reset_global_manager):
    """Outside a request the writer's org is unknown -> untagged (safe default)."""
    from app.streaming.manager import emit as module_emit

    ev = module_emit(EventType.TRACE_STARTED, {"trace_id": 1})
    assert ev is not None and ev.organization_id is None


def test_create_trace_emits_started_event(app_ctx, reset_global_manager):
    from app.services import trace_service

    sub = live_trace_manager.subscribe()
    trace = trace_service.create_trace({"user_prompt": "hi", "model_name": "gpt-4o"})

    event = next(sub.stream())
    assert event.type == EventType.TRACE_STARTED
    assert event.data["trace_id"] == trace.id
    assert event.data["model_name"] == "gpt-4o"
    live_trace_manager.unsubscribe(sub)


def test_agent_run_lifecycle_emits_events(app_ctx, reset_global_manager, request_trace):
    from app.services import trace_service

    sub = live_trace_manager.subscribe(topics=frozenset({"agent"}))
    run = trace_service.create_agent_run(request_trace.id, "Planner", "planner")
    trace_service.finish_agent_run(run)

    gen = sub.stream()
    started = next(gen)
    finished = next(gen)
    assert started.type == EventType.AGENT_STARTED
    assert started.data["run_id"] == run.id
    assert finished.type == EventType.AGENT_FINISHED
    live_trace_manager.unsubscribe(sub)
