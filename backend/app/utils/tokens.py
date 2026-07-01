"""Lightweight token estimation.

A real deployment would plug in a model-specific tokenizer (e.g. tiktoken).
To keep the platform dependency-free and offline-friendly, this uses the common
~4-characters-per-token heuristic, which is accurate enough for observability
dashboards and cost estimates. Swap the implementation here to upgrade every
caller at once.
"""
from math import ceil
from typing import Optional

_CHARS_PER_TOKEN = 4


def estimate_tokens(text: Optional[str]) -> int:
    """Estimate the number of tokens in ``text`` (0 for empty/None)."""
    if not text:
        return 0
    return max(1, ceil(len(text) / _CHARS_PER_TOKEN))
