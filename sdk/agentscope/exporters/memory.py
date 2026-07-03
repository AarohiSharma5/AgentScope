"""An in-memory exporter, useful for tests and local introspection."""
from __future__ import annotations

from collections import deque
from typing import Deque, List

from ..span import Trace
from .base import Exporter


class MemoryExporter(Exporter):
    """Retain the most recent finished traces in a bounded ring buffer."""

    def __init__(self, maxlen: int = 200):
        self._traces: Deque[Trace] = deque(maxlen=maxlen)

    def export(self, trace: Trace) -> None:
        self._traces.append(trace)

    @property
    def traces(self) -> List[Trace]:
        """All retained traces, oldest first."""
        return list(self._traces)

    def clear(self) -> None:
        self._traces.clear()
