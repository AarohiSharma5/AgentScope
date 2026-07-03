"""An exporter that emits finished traces through the ``logging`` module."""
from __future__ import annotations

import json
import logging

from ..span import Trace
from .base import Exporter


class LoggingExporter(Exporter):
    """Log each finished trace as a single structured record."""

    def __init__(self, logger: "logging.Logger | None" = None, level: int = logging.INFO):
        self._logger = logger or logging.getLogger("agentscope")
        self._level = level

    def export(self, trace: Trace) -> None:
        self._logger.log(
            self._level,
            "agentscope.trace %s",
            json.dumps(trace.to_dict(), default=str),
        )
