"""The :class:`Tracer` — owns span lifecycle, nesting and export dispatch.

Nesting is tracked with :mod:`contextvars`, so traces are correct across
threads *and* async tasks without any work from the caller. A process-wide
singleton tracer is created lazily; :func:`configure` (re)builds it.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Tuple

from .config import Config, _merge
from .exporters import ConsoleExporter, Exporter, HTTPExporter, LoggingExporter, MemoryExporter
from .span import Span, SpanKind, SpanStatus, Trace, _new_id

logger = logging.getLogger("agentscope")


class Tracer:
    """Creates spans, maintains the active span stack and dispatches traces."""

    def __init__(self, config: Optional[Config] = None):
        self._config = config or Config.from_env()
        self._span_stack: ContextVar[Tuple[Span, ...]] = ContextVar(
            "agentscope_span_stack", default=()
        )
        self._current_trace: ContextVar[Optional[Trace]] = ContextVar(
            "agentscope_trace", default=None
        )
        self._memory = MemoryExporter(self._config.max_retained_traces)
        self._exporters: List[Exporter] = self._build_exporters(self._config)

    # -- configuration ------------------------------------------------------

    @property
    def config(self) -> Config:
        return self._config

    def configure(self, **changes) -> Config:
        """Apply configuration changes and rebuild exporters."""
        self._config = _merge(self._config, **changes)
        self._memory = MemoryExporter(self._config.max_retained_traces)
        self._exporters = self._build_exporters(self._config)
        return self._config

    def _build_exporters(self, config: Config) -> List[Exporter]:
        exporters: List[Exporter] = []
        if config.endpoint:
            exporters.append(
                HTTPExporter(
                    endpoint=config.endpoint,
                    api_key=config.api_key,
                    timeout=config.timeout,
                    default_model=config.default_model,
                    headers=config.headers,
                )
            )
        if config.console:
            exporters.append(ConsoleExporter())
        if config.log:
            exporters.append(LoggingExporter())
        return exporters

    def add_exporter(self, exporter: Exporter) -> None:
        """Register an additional custom exporter at runtime."""
        self._exporters.append(exporter)

    # -- span lifecycle -----------------------------------------------------

    def start_span(
        self,
        name: str,
        kind: str = SpanKind.STEP,
        attributes: Optional[Dict[str, Any]] = None,
        input: Any = None,  # noqa: A002 - public, mirrors platform API
    ) -> Span:
        """Open a new span nested under the current one (if any)."""
        if not self._config.enabled:
            span = Span(name=name, kind=kind, attributes=dict(attributes or {}), input=input)
            span._recording = False
            return span

        stack = self._span_stack.get()
        parent = stack[-1] if stack else None
        span = Span(
            name=name,
            kind=kind,
            trace_id=parent.trace_id if parent else _new_id(),
            parent_id=parent.span_id if parent else None,
            attributes=dict(attributes or {}),
            input=input,
        )

        if parent is None:
            trace = Trace(trace_id=span.trace_id, root=span)
            self._current_trace.set(trace)
        else:
            trace = self._current_trace.get()

        if trace is not None:
            trace.spans.append(span)
        self._span_stack.set(stack + (span,))
        return span

    def end_span(
        self,
        span: Span,
        status: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Span:
        """Close a span; flush the whole trace once the root span ends."""
        span._finalize(status=status, error=error)
        if not getattr(span, "_recording", True):
            return span

        stack = self._span_stack.get()
        if stack and stack[-1] is span:
            self._span_stack.set(stack[:-1])
        elif span in stack:
            self._span_stack.set(tuple(s for s in stack if s is not span))

        if span.parent_id is None:
            trace = self._current_trace.get()
            self._current_trace.set(None)
            if trace is not None:
                self._dispatch(trace)
        return span

    def _dispatch(self, trace: Trace) -> None:
        """Send a finished trace to the in-memory buffer and every exporter."""
        self._memory.export(trace)
        for exporter in self._exporters:
            try:
                exporter.export(trace)
            except Exception:  # noqa: BLE001 - observability must never crash the app
                logger.debug("exporter %s failed", type(exporter).__name__, exc_info=True)

    # -- introspection ------------------------------------------------------

    def current_span(self) -> Optional[Span]:
        """The innermost active span, or ``None`` outside any trace."""
        stack = self._span_stack.get()
        return stack[-1] if stack else None

    def finished_traces(self) -> List[Trace]:
        """Recently finished traces retained in memory (oldest first)."""
        return self._memory.traces

    def clear(self) -> None:
        """Drop retained traces (does not affect external exporters)."""
        self._memory.clear()


# -- process-wide singleton -------------------------------------------------

_tracer: Optional[Tracer] = None


def get_tracer() -> Tracer:
    """Return the lazily-created global tracer."""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


def configure(**changes) -> Config:
    """Configure the global tracer (see :class:`~agentscope.config.Config`)."""
    return get_tracer().configure(**changes)


def get_config() -> Config:
    """Return the global tracer's current configuration."""
    return get_tracer().config


__all__ = ["Tracer", "get_tracer", "configure", "get_config", "SpanStatus"]
