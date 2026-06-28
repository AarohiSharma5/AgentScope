"""Request logging middleware and a reusable LLM-call tracer.

Two responsibilities live here:

1. ``register_request_logging`` - lightweight Flask before/after hooks that log
   each incoming HTTP request and its latency to the app logger.

2. ``TraceRecorder`` - a context manager that wraps an LLM call so latency,
   status and metadata are captured *automatically* and persisted as a Trace.
   This is what an application embeds around its model calls.
"""
import logging
import time
from contextlib import contextmanager

from flask import g, request

from ..services import trace_service
from ..models.trace import TraceStatus

logger = logging.getLogger("agentscope")


def register_request_logging(app) -> None:
    """Attach before/after request hooks for basic HTTP access logging."""

    @app.before_request
    def _start_timer():
        g._start_time = time.perf_counter()

    @app.after_request
    def _log_request(response):
        start = getattr(g, "_start_time", None)
        duration_ms = (time.perf_counter() - start) * 1000 if start else 0
        logger.info(
            "%s %s -> %s (%.1f ms)",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
        )
        return response


@contextmanager
def TraceRecorder(model_name: str, **metadata):
    """Context manager that records an LLM call as a Trace.

    Usage::

        with TraceRecorder("gpt-4o", user_prompt=prompt) as trace:
            response = call_model(prompt)
            trace.update(
                final_response=response.text,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
            )

    Latency is measured automatically and the trace is persisted on exit,
    including when the wrapped call raises (status becomes ``failed``).
    """

    class _TraceContext:
        def __init__(self, base: dict):
            self.data = base

        def update(self, **kwargs):
            self.data.update(kwargs)

    ctx = _TraceContext({"model_name": model_name, **metadata})
    start = time.perf_counter()
    try:
        yield ctx
        ctx.data.setdefault("status", TraceStatus.SUCCESS)
    except Exception as exc:  # noqa: BLE001 - we record then re-raise
        ctx.data["status"] = TraceStatus.FAILED
        ctx.data.setdefault("error_message", str(exc))
        ctx.data["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
        trace_service.create_trace(ctx.data)
        raise
    else:
        ctx.data["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
        trace_service.create_trace(ctx.data)
