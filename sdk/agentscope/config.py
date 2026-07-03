"""Configuration for the AgentScope SDK.

Configuration can come from three places, in increasing precedence:

1. Built-in defaults.
2. Environment variables (``AGENTSCOPE_*``), read at import time.
3. Explicit :func:`configure` calls at runtime.

Example
-------
    import agentscope

    agentscope.configure(
        service_name="my-rag-app",
        endpoint="http://localhost:5001",   # AgentScope server
        api_key="sk-...",                    # sent as Authorization: Bearer
        console=True,                         # also pretty-print traces
    )
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import List, Optional

from .errors import ConfigurationError


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Immutable SDK settings. Use :func:`configure` to change them."""

    #: Master switch. When ``False`` all tracing becomes a cheap no-op.
    enabled: bool = True
    #: Logical name of the service being traced.
    service_name: str = "agentscope-app"
    #: Base URL of the AgentScope server (enables the HTTP exporter when set).
    endpoint: Optional[str] = None
    #: API key sent to the server as ``Authorization: Bearer <key>``.
    api_key: Optional[str] = None
    #: Pretty-print every finished trace to stdout.
    console: bool = False
    #: Emit finished traces through the standard ``logging`` module.
    log: bool = False
    #: Default model name recorded on LLM spans when none is supplied.
    default_model: Optional[str] = None
    #: HTTP export timeout, in seconds.
    timeout: float = 5.0
    #: Retain at most this many finished traces in memory for introspection.
    max_retained_traces: int = 200
    #: Extra HTTP headers merged into every request to the server.
    headers: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Config":
        """Build a config from ``AGENTSCOPE_*`` environment variables."""
        return cls(
            enabled=_env_bool("AGENTSCOPE_ENABLED", True),
            service_name=os.getenv("AGENTSCOPE_SERVICE_NAME", "agentscope-app"),
            endpoint=os.getenv("AGENTSCOPE_ENDPOINT") or None,
            api_key=os.getenv("AGENTSCOPE_API_KEY") or None,
            console=_env_bool("AGENTSCOPE_CONSOLE", False),
            log=_env_bool("AGENTSCOPE_LOG", False),
            default_model=os.getenv("AGENTSCOPE_DEFAULT_MODEL") or None,
            timeout=float(os.getenv("AGENTSCOPE_TIMEOUT", "5")),
        )


# Known option names, used to reject typos early.
_FIELDS = set(Config.__dataclass_fields__.keys())


def _merge(base: Config, **changes) -> Config:
    unknown = set(changes) - _FIELDS
    if unknown:
        raise ConfigurationError(
            f"Unknown configuration option(s): {', '.join(sorted(unknown))}. "
            f"Valid options: {', '.join(sorted(_FIELDS))}."
        )
    return replace(base, **changes)
