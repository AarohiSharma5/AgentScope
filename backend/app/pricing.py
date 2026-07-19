"""Central, overridable model price table + cost estimation.

One source of truth for "USD per 1K tokens" so every code path that estimates
cost from tokens (trace ingest, chat, replay, seeds) prices a call the same way
— and, crucially, so operators can supply accurate prices for their **own** or
self-hosted models without editing source code.

Price resolution for a model (first match wins):

1. Runtime overrides registered via :func:`register_prices`.
2. ``MODEL_PRICES`` from Flask config (loaded from ``AGENTSCOPE_MODEL_PRICES`` —
   a JSON object *or* a path to a JSON file; see ``config.py``).
3. The built-in :data:`DEFAULT_MODEL_PRICES` below.

Within the merged table the **exact** model name is tried first, then the
longest matching ``<base>-...`` prefix, so versioned names like
``gpt-4o-2024-05-13`` inherit their base model's price automatically (the old
exact-match table silently returned no cost for these).

An unknown model returns ``None`` — callers MUST treat that as *"cost unknown"*,
never as ``$0``. :func:`is_priced` lets callers/UI distinguish the two.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger("agentscope")

# model name -> (input_per_1k, output_per_1k) in USD. A bare float is shorthand
# for an input-only price (embeddings). Keep base names here; versioned aliases
# resolve via prefix matching.
DEFAULT_MODEL_PRICES: Dict[str, Tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-opus": (0.015, 0.075),
    "claude-3-sonnet": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
    "gemini-1.5-pro": (0.00125, 0.005),
    "gemini-1.5-flash": (0.000075, 0.0003),
}

# Runtime overrides set programmatically (highest priority). Persist for the
# process lifetime; cleared explicitly by tests.
_runtime_overrides: Dict[str, Tuple[float, float]] = {}


def _normalize_entry(entry) -> Optional[Tuple[float, float]]:
    """Coerce a price entry to ``(input, output)`` floats, or None if malformed."""
    if entry is None:
        return None
    if isinstance(entry, (int, float)):
        return (float(entry), 0.0)
    if isinstance(entry, (list, tuple)) and len(entry) == 2:
        try:
            return (float(entry[0]), float(entry[1]))
        except (TypeError, ValueError):
            return None
    return None


def _normalize_table(raw) -> Dict[str, Tuple[float, float]]:
    """Normalize a ``{model: entry}`` mapping, dropping malformed rows."""
    table: Dict[str, Tuple[float, float]] = {}
    if not isinstance(raw, dict):
        return table
    for model, entry in raw.items():
        normalized = _normalize_entry(entry)
        if normalized is None:
            logger.warning("ignoring malformed price for model %r: %r", model, entry)
            continue
        table[str(model)] = normalized
    return table


def register_prices(mapping: dict) -> None:
    """Register/override model prices at runtime (highest precedence).

    Accepts the same shapes as the table (``(in, out)`` or a bare float). Useful
    for tests and for programmatic configuration in an app factory.
    """
    _runtime_overrides.update(_normalize_table(mapping))


def clear_runtime_prices() -> None:
    """Drop all runtime overrides (primarily for tests)."""
    _runtime_overrides.clear()


def _config_prices() -> Dict[str, Tuple[float, float]]:
    """``MODEL_PRICES`` from the active Flask app config, if any."""
    try:
        from flask import current_app

        return _normalize_table(current_app.config.get("MODEL_PRICES"))
    except RuntimeError:
        # No application context (e.g. a bare SDK/script call) — skip config layer.
        return {}


def _effective_table() -> Dict[str, Tuple[float, float]]:
    """Merged table: defaults < config < runtime overrides (later wins)."""
    table = dict(DEFAULT_MODEL_PRICES)
    table.update(_config_prices())
    table.update(_runtime_overrides)
    return table


def resolve_price(model: Optional[str]) -> Optional[Tuple[float, float]]:
    """Return ``(input_per_1k, output_per_1k)`` for a model, or None if unpriced.

    Tries the exact name first, then the longest matching ``<base>-...`` prefix.
    """
    if not model:
        return None
    table = _effective_table()
    entry = table.get(model)
    if entry is not None:
        return entry
    # Longest-prefix match so ``gpt-4o-mini-2024-...`` prefers ``gpt-4o-mini``
    # over ``gpt-4o``.
    best: Optional[str] = None
    for base in table:
        if model.startswith(base + "-") and (best is None or len(base) > len(best)):
            best = base
    return table[best] if best is not None else None


def is_priced(model: Optional[str]) -> bool:
    """Whether a cost can be computed for ``model`` (i.e. it resolves to a price)."""
    return resolve_price(model) is not None


def estimate_cost(
    model: Optional[str],
    input_tokens: Optional[int],
    output_tokens: Optional[int],
) -> Optional[float]:
    """Estimate USD cost for a call, or ``None`` when the model is unpriced.

    ``None`` means "unknown", not free — callers/UI must render it distinctly.
    """
    prices = resolve_price(model)
    if prices is None:
        return None
    in_price, out_price = prices
    cost = (input_tokens or 0) / 1000 * in_price + (output_tokens or 0) / 1000 * out_price
    return round(cost, 8)
