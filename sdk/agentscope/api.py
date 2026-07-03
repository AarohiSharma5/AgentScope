"""The public ``trace`` object: decorator, context manager and manual API.

``trace`` is a single, ergonomic entry point that works three ways::

    from agentscope import trace

    # 1) Decorator — every call is traced automatically
    @trace
    def plan(question): ...

    @trace("custom-name", kind="llm", model="gpt-4o")
    def generate(prompt): ...

    # 2) Context manager — scope an arbitrary block
    with trace("retrieval", kind="retriever") as span:
        docs = search(q)
        span.set_output(docs)

    # 3) Manual — full control over start/end
    span = trace.start("generation", kind="llm")
    span.set_output(text).set_tokens(input=12, output=40).set_cost(0.001)
    trace.end(span)

Exceptions raised inside a traced scope mark the span ``failed`` (recording the
error) and are then re-raised unchanged.
"""
from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Optional

from .span import Span, SpanKind, SpanStatus
from .tracer import get_tracer


class SpanScope:
    """A started-or-not span usable as a context manager *and* a decorator."""

    def __init__(self, name: Optional[str], kind: str, attributes: dict, input: Any = None):
        self._name = name
        self._kind = kind
        self._attributes = attributes
        self._input = input
        self._span: Optional[Span] = None

    # -- context manager ----------------------------------------------------

    def __enter__(self) -> Span:
        self._span = get_tracer().start_span(
            name=self._name or "span",
            kind=self._kind,
            attributes=self._attributes,
            input=self._input,
        )
        return self._span

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._span is None:
            return False
        if exc is not None:
            get_tracer().end_span(
                self._span, status=SpanStatus.FAILED, error=f"{exc_type.__name__}: {exc}"
            )
        else:
            get_tracer().end_span(self._span, status=SpanStatus.SUCCESS)
        return False  # never suppress exceptions

    # -- decorator ----------------------------------------------------------

    def __call__(self, func: Callable) -> Callable:
        name = self._name or getattr(func, "__name__", "span")
        return _wrap(func, name=name, kind=self._kind, attributes=self._attributes)


def _wrap(func: Callable, name: str, kind: str, attributes: dict) -> Callable:
    """Wrap ``func`` so each call runs inside a span (sync or async)."""
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            span = tracer.start_span(name, kind=kind, attributes=dict(attributes), input=_first(args, kwargs))
            try:
                result = await func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - record then re-raise
                tracer.end_span(span, status=SpanStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
                raise
            span.set_output(result)
            tracer.end_span(span, status=SpanStatus.SUCCESS)
            return result

        async_wrapper.__agentscope_traced__ = True
        return async_wrapper

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        tracer = get_tracer()
        span = tracer.start_span(name, kind=kind, attributes=dict(attributes), input=_first(args, kwargs))
        try:
            result = func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            tracer.end_span(span, status=SpanStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
            raise
        span.set_output(result)
        tracer.end_span(span, status=SpanStatus.SUCCESS)
        return result

    wrapper.__agentscope_traced__ = True
    return wrapper


def _first(args, kwargs):
    """Best-effort capture of a call's primary input for the span."""
    if args:
        # Skip a leading ``self``/``cls`` for bound methods where possible.
        return args[0] if len(args) == 1 else list(args)
    if kwargs:
        return kwargs
    return None


class _TraceAPI:
    """The callable ``trace`` singleton exposing every tracing entry point."""

    SpanKind = SpanKind
    SpanStatus = SpanStatus

    def __call__(self, name_or_func: Any = None, *, kind: str = SpanKind.STEP, **attributes) -> Any:
        """Trace a function (decorator) or a block (context manager).

        ``@trace`` (bare) decorates a function; ``trace("name", **attrs)`` or
        ``@trace("name")`` returns a :class:`SpanScope`.
        """
        if callable(name_or_func) and not attributes and kind == SpanKind.STEP:
            return _wrap(
                name_or_func,
                name=getattr(name_or_func, "__name__", "span"),
                kind=kind,
                attributes={},
            )
        return SpanScope(name=name_or_func, kind=kind, attributes=attributes)

    # -- typed scope helpers (context manager or decorator) -----------------

    def agent(self, name: str, **attributes) -> SpanScope:
        """Scope an agent span."""
        return SpanScope(name, SpanKind.AGENT, attributes)

    def workflow(self, name: str, **attributes) -> SpanScope:
        """Scope a workflow span."""
        return SpanScope(name, SpanKind.WORKFLOW, attributes)

    def step(self, name: str, **attributes) -> SpanScope:
        """Scope a generic step span."""
        return SpanScope(name, SpanKind.STEP, attributes)

    def tool(self, name: str, **attributes) -> SpanScope:
        """Scope a tool-call span."""
        return SpanScope(name, SpanKind.TOOL, attributes)

    def llm(self, name: str = "llm", **attributes) -> SpanScope:
        """Scope an LLM-generation span."""
        return SpanScope(name, SpanKind.LLM, attributes)

    def retriever(self, name: str = "retriever", **attributes) -> SpanScope:
        """Scope a retriever span."""
        return SpanScope(name, SpanKind.RETRIEVER, attributes)

    def memory(self, name: str = "memory", **attributes) -> SpanScope:
        """Scope a memory-access span."""
        return SpanScope(name, SpanKind.MEMORY, attributes)

    # -- manual API ---------------------------------------------------------

    def start(
        self,
        name: str,
        kind: str = SpanKind.STEP,
        input: Any = None,  # noqa: A002 - public, mirrors platform API
        **attributes,
    ) -> Span:
        """Manually start a span. Remember to call :meth:`end`."""
        return get_tracer().start_span(name, kind=kind, attributes=attributes, input=input)

    def end(self, span: Span, status: Optional[str] = None, error: Optional[str] = None) -> Span:
        """Manually end a span previously opened with :meth:`start`."""
        return get_tracer().end_span(span, status=status, error=error)

    def current(self) -> Optional[Span]:
        """The innermost active span, or ``None``."""
        return get_tracer().current_span()

    # -- configuration & introspection --------------------------------------

    def configure(self, **changes):
        """Configure the global tracer (see :func:`agentscope.configure`)."""
        return get_tracer().configure(**changes)

    def get_config(self):
        """Return the active configuration."""
        return get_tracer().config

    def finished(self):
        """Recently finished traces retained in memory (oldest first)."""
        return get_tracer().finished_traces()

    def clear(self) -> None:
        """Drop retained in-memory traces."""
        get_tracer().clear()

    def add_exporter(self, exporter) -> None:
        """Register a custom exporter at runtime."""
        get_tracer().add_exporter(exporter)


#: The singleton used as ``from agentscope import trace``.
trace = _TraceAPI()
