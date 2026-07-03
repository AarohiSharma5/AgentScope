"""A human-friendly console exporter that prints the span tree."""
from __future__ import annotations

import sys
from typing import Dict, List

from ..span import Span, Trace
from .base import Exporter

_STATUS_MARK = {"success": "✓", "failed": "✗", "running": "•"}


class ConsoleExporter(Exporter):
    """Pretty-print each finished trace as an indented tree to a stream."""

    def __init__(self, stream=None):
        self._stream = stream or sys.stdout

    def export(self, trace: Trace) -> None:
        lines = [
            f"─ trace {trace.trace_id} · {trace.name} "
            f"[{trace.status}] {_fmt_ms(trace.latency_ms)} "
            f"· {trace.total_tokens()} tok · ${trace.total_cost():.4f}"
        ]
        children = _children_by_parent(trace.spans)
        for child in children.get(trace.root.span_id, []):
            _render(child, children, depth=1, out=lines)
        self._stream.write("\n".join(lines) + "\n")
        self._stream.flush()


def _children_by_parent(spans: List[Span]) -> Dict[str, List[Span]]:
    tree: Dict[str, List[Span]] = {}
    for span in spans:
        tree.setdefault(span.parent_id, []).append(span)
    return tree


def _render(span: Span, tree: Dict[str, List[Span]], depth: int, out: List[str]) -> None:
    mark = _STATUS_MARK.get(span.status, "•")
    indent = "  " * depth
    out.append(f"{indent}{mark} {span.kind}:{span.name} {_fmt_ms(span.latency_ms)}")
    for child in tree.get(span.span_id, []):
        _render(child, tree, depth + 1, out)


def _fmt_ms(ms) -> str:
    if ms is None:
        return "—"
    return f"{ms / 1000:.2f}s" if ms >= 1000 else f"{ms:.0f}ms"
