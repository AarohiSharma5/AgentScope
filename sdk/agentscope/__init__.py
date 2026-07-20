"""AgentScope SDK (``agentscope-lite``) — tracing for AI agents & workflows.

A lightweight, dependency-free client for the AgentScope observability platform.
Instrument your app with a decorator, a context manager, or manual calls, and
stream traces to a running AgentScope server (or just inspect them locally).

Quick start
-----------
    import agentscope
    from agentscope import trace, Agent, Workflow, Tool

    # Optional: point at a running AgentScope server + API key.
    agentscope.configure(endpoint="http://localhost:8000", api_key="sk-...")

    @trace
    def answer(question: str) -> str:
        return "42"

    answer("meaning of life?")     # automatically traced

Public API
----------
* :data:`trace`  — decorator / context manager / manual tracing entry point.
* :class:`Agent`    — a named, traced unit of work.
* :class:`Workflow` — compose steps into one traced run.
* :class:`Tool`     — a traced, callable tool.
* :func:`configure` — set service name, endpoint, API key and exporters.

Backwards compatibility: the public names above are stable for the 1.x line.
"""
from ._version import __version__
from .agent import Agent
from .api import SpanScope, trace
from .config import Config
from .errors import AgentScopeError, ConfigurationError, ExporterError
from .exporters import (
    ConsoleExporter,
    Exporter,
    HTTPExporter,
    LoggingExporter,
    MemoryExporter,
)
from .instrument import instrument_anthropic, instrument_openai
from .span import Span, SpanKind, SpanStatus, Trace
from .tool import Tool
from .tracer import Tracer, configure, get_config, get_tracer
from .workflow import Workflow

__all__ = [
    "__version__",
    # Primary public API
    "trace",
    "Agent",
    "Workflow",
    "Tool",
    "instrument_openai",
    "instrument_anthropic",
    "configure",
    "get_config",
    # Configuration & runtime
    "Config",
    "Tracer",
    "get_tracer",
    "SpanScope",
    # Data model
    "Span",
    "Trace",
    "SpanKind",
    "SpanStatus",
    # Exporters
    "Exporter",
    "ConsoleExporter",
    "MemoryExporter",
    "LoggingExporter",
    "HTTPExporter",
    # Errors
    "AgentScopeError",
    "ConfigurationError",
    "ExporterError",
]
