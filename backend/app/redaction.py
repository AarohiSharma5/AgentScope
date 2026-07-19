"""Server-side PII / secret redaction applied at ingest (defense-in-depth).

The SDK can scrub sensitive data before it ever leaves your process
(``agentscope.configure(redact=True)``). But a non-SDK client — e.g. a chatbot
written in another language POSTing raw JSON to ``/api/traces`` or
``/api/agent-runs`` — bypasses that. Enabling ``INGEST_REDACT`` scrubs prompt,
response, tool and document text *before it is persisted*, so the store never
holds raw PII regardless of who wrote it.

Off by default (redaction is lossy for debugging). Turn on with
``AGENTSCOPE_INGEST_REDACT=true`` and optionally extend the built-in patterns
via ``AGENTSCOPE_INGEST_REDACT_PATTERNS`` (JSON ``[[regex, replacement], …]``).

The pattern set mirrors the SDK's for consistent behaviour across both layers.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger("agentscope")

# (compiled pattern, replacement). Tuned to over-redact rather than leak.
_BUILTIN_PATTERNS = [
    (re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._-]{8,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[REDACTED_CC]"),
    (re.compile(r"\b(?:\+?\d{1,3}[ -]?)?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}\b"), "[REDACTED_PHONE]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED_IP]"),
]

# Keys whose values are structural/identifiers/enums, never scrubbed — they
# drive segmentation, cost and validation and never carry PII.
_SAFE_KEYS = frozenset(
    {
        "model", "model_name", "project", "status", "agent_type", "step_type",
        "memory_type", "embedding_model", "id", "request_id", "parent_run_id",
        "run_id", "step_number", "num_documents", "tool_name",
    }
)

_UNSET = object()


class Redactor:
    """Recursively scrubs strings in ingest payloads, skipping :data:`_SAFE_KEYS`."""

    def __init__(self, patterns):
        self._patterns = list(patterns)

    def scrub_text(self, text):
        if not isinstance(text, str):
            return text
        for pattern, replacement in self._patterns:
            text = pattern.sub(replacement, text)
        return text

    def scrub_value(self, value):
        if isinstance(value, str):
            return self.scrub_text(value)
        if isinstance(value, dict):
            return {
                key: (val if key in _SAFE_KEYS else self.scrub_value(val))
                for key, val in value.items()
            }
        if isinstance(value, list):
            return [self.scrub_value(v) for v in value]
        if isinstance(value, tuple):
            return tuple(self.scrub_value(v) for v in value)
        return value


def _compile_extra(raw) -> list:
    """Compile config-supplied ``[[regex, replacement], …]`` pairs, skip bad ones."""
    out = []
    if isinstance(raw, list):
        for item in raw:
            try:
                pattern, replacement = item
                out.append((re.compile(pattern), str(replacement)))
            except Exception:  # noqa: BLE001 - a bad pattern must not break ingest
                logger.warning("ignoring malformed INGEST_REDACT_PATTERNS entry: %r", item)
    return out


def build_ingest_redactor(config) -> Optional[Redactor]:
    """Build a :class:`Redactor` from app config, or None when disabled."""
    if not config.get("INGEST_REDACT"):
        return None
    patterns = list(_BUILTIN_PATTERNS) + _compile_extra(config.get("INGEST_REDACT_PATTERNS"))
    return Redactor(patterns)


def ingest_redactor() -> Optional[Redactor]:
    """The active redactor for the current app (cached), or None if disabled/no app."""
    try:
        from flask import current_app

        app = current_app._get_current_object()
    except RuntimeError:
        return None
    cached = app.extensions.get("_ingest_redactor", _UNSET)
    if cached is _UNSET:
        cached = build_ingest_redactor(app.config)
        app.extensions["_ingest_redactor"] = cached
    return cached


def redact_payload(data: dict) -> dict:
    """Scrub an ingest payload if redaction is enabled; otherwise return it as-is."""
    redactor = ingest_redactor()
    if redactor is None or not isinstance(data, dict):
        return data
    return redactor.scrub_value(data)
