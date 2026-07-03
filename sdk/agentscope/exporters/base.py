"""The exporter contract.

An exporter receives each finished :class:`~agentscope.span.Trace` and does
something useful with it — print it, buffer it, log it, or ship it to the
AgentScope server. Exporters must never raise into user code; the tracer calls
them defensively, but they should also fail soft on their own.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..span import Trace


class Exporter(ABC):
    """Base class for all trace exporters."""

    @abstractmethod
    def export(self, trace: Trace) -> None:
        """Handle a single finished trace (root span + descendants)."""

    def shutdown(self) -> None:  # pragma: no cover - optional hook
        """Flush/close any resources. Called when exporters are replaced."""
