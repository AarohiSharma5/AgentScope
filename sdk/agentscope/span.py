"""The :class:`Span` — the atomic unit of a trace.

A span records a single timed operation (an agent run, a tool call, an LLM
generation, a workflow step, or an arbitrary block of code). Spans form a tree
via ``parent_id``; all spans sharing a ``trace_id`` belong to one trace.

Spans are plain, JSON-serializable value objects with no I/O of their own — the
:class:`~agentscope.tracer.Tracer` is responsible for timing and dispatching
them to exporters. This keeps the data model easy to test and to serialize.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class SpanKind:
    """Canonical span kinds, mirroring the AgentScope platform's taxonomy."""

    TRACE = "trace"
    AGENT = "agent"
    WORKFLOW = "workflow"
    STEP = "step"
    TOOL = "tool"
    LLM = "llm"
    RETRIEVER = "retriever"
    MEMORY = "memory"


class SpanStatus:
    """Terminal status values for a span."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


def _new_id() -> str:
    """A short, collision-resistant identifier for a span or trace."""
    return uuid.uuid4().hex[:16]


@dataclass
class Span:
    """A single timed operation within a trace.

    Attributes
    ----------
    name:
        Human-readable operation name (e.g. ``"Planner"`` or ``"search"``).
    kind:
        One of :class:`SpanKind` — how the span should be interpreted.
    trace_id:
        Identifier shared by every span in the same trace.
    span_id:
        This span's unique identifier.
    parent_id:
        The enclosing span's ``span_id``, or ``None`` for the root span.
    status:
        A :class:`SpanStatus` value; ``running`` until the span ends.
    attributes:
        Arbitrary JSON-serializable metadata (model name, temperature, …).
    input / output:
        Optional recorded input and output payloads.
    tokens:
        Optional ``{"input": int, "output": int, "total": int}`` usage.
    cost:
        Optional estimated cost in USD.
    error:
        A ``"TypeError: ..."``-style string when the span failed.
    """

    name: str
    kind: str = SpanKind.STEP
    trace_id: str = field(default_factory=_new_id)
    span_id: str = field(default_factory=_new_id)
    parent_id: Optional[str] = None

    status: str = SpanStatus.RUNNING
    attributes: Dict[str, Any] = field(default_factory=dict)
    input: Any = None
    output: Any = None
    tokens: Optional[Dict[str, Optional[int]]] = None
    cost: Optional[float] = None
    error: Optional[str] = None

    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    # High-resolution markers for accurate latency, independent of wall clock.
    _perf_start: float = field(default_factory=time.perf_counter, repr=False)
    _perf_end: Optional[float] = field(default=None, repr=False)

    # -- Fluent mutators (all return ``self`` for chaining) -----------------

    def set_attribute(self, key: str, value: Any) -> "Span":
        """Set a single metadata attribute."""
        self.attributes[key] = value
        return self

    def update(self, **attributes: Any) -> "Span":
        """Merge several metadata attributes at once."""
        self.attributes.update(attributes)
        return self

    def set_input(self, value: Any) -> "Span":
        """Record the span's input payload."""
        self.input = value
        return self

    def set_output(self, value: Any) -> "Span":
        """Record the span's output payload."""
        self.output = value
        return self

    def set_tokens(
        self,
        input: Optional[int] = None,  # noqa: A002 - public, mirrors platform API
        output: Optional[int] = None,
        total: Optional[int] = None,
    ) -> "Span":
        """Record token usage, deriving ``total`` when omitted."""
        if total is None and (input is not None or output is not None):
            total = (input or 0) + (output or 0)
        self.tokens = {"input": input, "output": output, "total": total}
        return self

    def set_cost(self, cost: Optional[float]) -> "Span":
        """Record the estimated cost (USD) of the operation."""
        self.cost = cost
        return self

    # -- Timing / lifecycle -------------------------------------------------

    @property
    def latency_ms(self) -> Optional[float]:
        """Elapsed milliseconds, or ``None`` while the span is still running."""
        if self._perf_end is None:
            return None
        return round((self._perf_end - self._perf_start) * 1000, 3)

    @property
    def is_running(self) -> bool:
        return self.end_time is None

    def _finalize(self, status: Optional[str] = None, error: Optional[str] = None) -> None:
        """Stamp end time/status. Idempotent; called by the tracer."""
        if self.end_time is None:
            self.end_time = time.time()
            self._perf_end = time.perf_counter()
        if error is not None:
            self.error = error
        if status is not None:
            self.status = status
        elif self.status == SpanStatus.RUNNING:
            self.status = SpanStatus.SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "kind": self.kind,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "status": self.status,
            "attributes": self.attributes,
            "input": self.input,
            "output": self.output,
            "tokens": self.tokens,
            "cost": self.cost,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


@dataclass
class Trace:
    """A completed (or in-progress) trace: a root span plus all its descendants."""

    trace_id: str
    root: Span
    spans: List[Span] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def status(self) -> str:
        return self.root.status

    @property
    def latency_ms(self) -> Optional[float]:
        return self.root.latency_ms

    def total_tokens(self) -> int:
        """Sum ``tokens.total`` across every span that recorded usage."""
        return sum((s.tokens or {}).get("total") or 0 for s in self.spans)

    def total_cost(self) -> float:
        """Sum ``cost`` across every span that recorded one."""
        return round(sum(s.cost or 0.0 for s in self.spans), 8)

    def tool_calls(self) -> List[Dict[str, Any]]:
        """Every tool span, projected to ``{name, arguments, result, status}``."""
        return [
            {
                "tool_name": s.name,
                "arguments": s.input,
                "result": s.output,
                "status": s.status,
                "latency_ms": s.latency_ms,
            }
            for s in self.spans
            if s.kind == SpanKind.TOOL
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "name": self.name,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "total_tokens": self.total_tokens(),
            "total_cost": self.total_cost(),
            "spans": [s.to_dict() for s in self.spans],
        }
