"""Shared helpers for framework integrations (LangChain, LlamaIndex, …).

These are framework-agnostic: turning payloads into JSON-safe values, building
token dicts, formatting errors, and pricing LLM steps with the same tables used
by the auto-instrumentation. Nothing here imports a third-party framework.
"""
from __future__ import annotations

import json
import logging
from functools import wraps
from typing import Any, Optional

from ..instrument import (
    _ANTHROPIC_PRICES,
    _GEMINI_PRICES,
    _OPENAI_PRICES,
    _estimate_cost,
    _get,
)

logger = logging.getLogger("agentscope")

# Reuse the auto-instrumentation price tables so framework LLM steps are costed
# with the same numbers as direct SDK calls (unknown models stay uncosted).
_PRICES = {**_OPENAI_PRICES, **_ANTHROPIC_PRICES, **_GEMINI_PRICES}


def estimate_cost(model: Optional[str], input_tokens, output_tokens) -> Optional[float]:
    """Cost in USD from the merged provider price tables, or None if unknown."""
    return _estimate_cost(model, input_tokens, output_tokens, _PRICES)


def guard(method):
    """Never let a callback exception escape into the framework / user's app."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:  # noqa: BLE001 - observability must not crash the app
            logger.debug("AgentScope integration error in %s", method.__name__, exc_info=True)
        return None

    return wrapper


def err(error: Any) -> str:
    return f"{type(error).__name__}: {error}"


def coerce(value: Any) -> Any:
    """Keep JSON-friendly payloads as-is; stringify anything the exporter can't
    serialize (framework inputs/outputs are often rich objects)."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def tokens(input_tokens: Optional[int], output_tokens: Optional[int]) -> Optional[dict]:
    if input_tokens is None and output_tokens is None:
        return None
    return {
        "input": input_tokens,
        "output": output_tokens,
        "total": (input_tokens or 0) + (output_tokens or 0),
    }


def messages_text(messages: Any) -> Optional[str]:
    """Flatten a list of chat messages (each with ``content`` + role/type)."""
    parts = []
    for msg in messages or []:
        content = getattr(msg, "content", None)
        role = getattr(msg, "type", None) or getattr(msg, "role", None)
        if isinstance(content, str) and content:
            parts.append(f"{role}: {content}" if role else content)
    return "\n".join(parts) if parts else None


__all__ = ["guard", "err", "coerce", "tokens", "messages_text", "estimate_cost", "_get", "logger"]
