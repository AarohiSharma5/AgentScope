"""Real-time streaming transports (v0.6): Server-Sent Events + WebSocket.

Both endpoints are thin adapters over :class:`~app.streaming.manager.Subscriber`:
they subscribe, then relay the shared event stream (including heartbeats) to the
client and unsubscribe on disconnect. All connection logic lives in the manager.

Endpoints (additive; no existing route is modified):

* ``GET /api/stream``      — Server-Sent Events (``text/event-stream``).
* ``GET /api/stream/info`` — broadcaster stats (JSON).
* ``WS  /api/ws``          — WebSocket (registered via flask-sock).

Both accept ``?events=`` (comma-separated topics/types) to filter, and support
resuming from a ``Last-Event-ID`` header or ``?last_event_id=`` query param.
"""
import logging
from urllib.parse import parse_qs

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from ..streaming import EventType, live_trace_manager, parse_topics

logger = logging.getLogger("agentscope")

stream_bp = Blueprint("stream", __name__)


def _heartbeat_interval() -> float:
    """Heartbeat cadence (seconds), overridable via ``STREAM_HEARTBEAT_INTERVAL``."""
    return float(current_app.config.get("STREAM_HEARTBEAT_INTERVAL", live_trace_manager.heartbeat_interval))


def _parse_int(value) -> "int | None":
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _last_event_id_from_request() -> "int | None":
    """Resolve a reconnect cursor from the SSE header or query param."""
    return _parse_int(request.headers.get("Last-Event-ID") or request.args.get("last_event_id"))


# -- Server-Sent Events -----------------------------------------------------


@stream_bp.get("/stream")
def sse_stream():
    """Stream live platform events to the client over SSE."""
    subscriber = live_trace_manager.subscribe(
        topics=parse_topics(request.args.get("events")),
        last_event_id=_last_event_id_from_request(),
        heartbeat_interval=_heartbeat_interval(),
    )

    @stream_with_context
    def generate():
        # Advise the browser's EventSource reconnect delay (ms), then relay.
        yield "retry: 3000\n\n"
        try:
            for event in subscriber.stream():
                if event.type == EventType.HEARTBEAT:
                    yield ": heartbeat\n\n"
                else:
                    yield event.to_sse()
        finally:
            live_trace_manager.unsubscribe(subscriber)

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"  # disable nginx proxy buffering
    return response


@stream_bp.get("/stream/info")
def stream_info():
    """Return broadcaster statistics (active subscribers, drops, etc.)."""
    data = dict(live_trace_manager.stats())
    data["events"] = sorted(t for t in vars(EventType).values()
                            if isinstance(t, str) and "." in t)
    return jsonify(data)


# -- WebSocket (flask-sock) -------------------------------------------------


def _ws_query(environ) -> dict:
    """Parse the WebSocket request's query string into a flat dict."""
    raw = parse_qs(environ.get("QUERY_STRING", ""))
    return {key: values[0] for key, values in raw.items() if values}


def register_websocket(sock) -> None:
    """Register the WebSocket endpoint on a flask-sock ``Sock`` instance.

    Called from the app factory. Kept separate from the blueprint because
    flask-sock routes attach to the ``Sock`` object, not a Blueprint.
    """

    @sock.route("/api/ws")
    def ws_stream(ws):  # pragma: no cover - exercised via a live server, not the test client
        from simple_websocket import ConnectionClosed

        params = _ws_query(ws.environ)
        subscriber = live_trace_manager.subscribe(
            topics=parse_topics(params.get("events")),
            last_event_id=_parse_int(params.get("last_event_id")),
            heartbeat_interval=float(
                current_app.config.get(
                    "STREAM_HEARTBEAT_INTERVAL", live_trace_manager.heartbeat_interval
                )
            ),
        )
        try:
            for event in subscriber.stream():
                # A heartbeat send doubles as liveness detection: if the client
                # has gone away, ``send`` raises ConnectionClosed and we stop.
                ws.send(event.to_json())
        except ConnectionClosed:
            pass
        except Exception:  # noqa: BLE001 - never let a socket error escape
            logger.exception("websocket stream error")
        finally:
            live_trace_manager.unsubscribe(subscriber)
