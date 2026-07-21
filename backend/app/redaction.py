"""Server-side PII / secret redaction applied at ingest (defense-in-depth).

The SDK can scrub sensitive data before it ever leaves your process
(``agentscope.configure(redact=True)``). But a non-SDK client — e.g. a chatbot
written in another language POSTing raw JSON to ``/api/traces``,
``/api/agent-runs`` or ``/api/otel/v1/traces`` — bypasses that. Enabling
``INGEST_REDACT`` scrubs prompt, response, tool and document text *before it is
persisted*, so the store never holds raw PII regardless of who wrote it.

Off by default (redaction is lossy for debugging). Turn on with
``AGENTSCOPE_INGEST_REDACT=true``. There are three layers, applied in order:

1. **Built-in patterns** — a broad, high-precision set of secret/PII regexes.
2. **Extra patterns** — ``AGENTSCOPE_INGEST_REDACT_PATTERNS`` (JSON
   ``[[regex, replacement], …]``) for site-specific identifiers.
3. **Pluggable detectors** — named ``Callable[[str], str]`` scrubbers registered
   with :func:`register_detector` and enabled via
   ``AGENTSCOPE_INGEST_REDACT_DETECTORS``. This is the seam for entity-based
   engines (spaCy/Presidio, a cloud DLP API, …) with **no hard dependency** —
   AgentScope calls yours if you register it.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("agentscope")

# (compiled pattern, replacement). Ordered specific-before-generic. Tuned to
# over-redact rather than leak. High-precision provider secret formats are safe
# to include by default; the looser numeric ones (phone/CC/IP) come last.
_BUILTIN_PATTERNS = [
    # Structured secrets / tokens (very low false-positive rate).
    (re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z ]+ )?PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "[REDACTED_JWT]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "[REDACTED_GOOGLE_KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._-]{8,}\b"), "[REDACTED_TOKEN]"),
    # Labelled secret assignments: password=…, api_key: …, secret => … (keeps
    # the label + separator, scrubs only the value).
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)"
            r"(\s*[:=]\s*)"
            r"([^\s\"',;]{4,})"
        ),
        r"\1\2[REDACTED_SECRET]",
    ),
    # PII.
    (re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "[REDACTED_IBAN]"),
    (re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b"), "[REDACTED_MAC]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[REDACTED_CC]"),
    (re.compile(r"\b(?:\+?\d{1,3}[ -]?)?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}\b"), "[REDACTED_PHONE]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED_IP]"),
    (re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}\b"), "[REDACTED_IPV6]"),
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

# Registry of named, pluggable detectors: ``name -> Callable[[str], str]``. A
# detector receives text and returns it with sensitive spans replaced. This is
# how callers add entity-based detection (Presidio/spaCy/DLP) without AgentScope
# taking a dependency on any of them.
_DETECTORS: Dict[str, Callable[[str], str]] = {}


def register_detector(name: str, detector: Callable[[str], str]) -> None:
    """Register a named text detector usable via ``INGEST_REDACT_DETECTORS``.

    ``detector`` must be ``Callable[[str], str]``: given text, return it with
    sensitive spans removed/replaced. Registering the same name overwrites it.
    """
    if not callable(detector):
        raise TypeError("detector must be callable: (str) -> str")
    _DETECTORS[name] = detector


def get_detector(name: str) -> Optional[Callable[[str], str]]:
    return _DETECTORS.get(name)


def clear_detectors() -> None:
    """Drop all registered detectors (primarily for tests)."""
    _DETECTORS.clear()


class Redactor:
    """Recursively scrubs strings in ingest payloads, skipping :data:`_SAFE_KEYS`.

    Applies regex ``patterns`` first, then each pluggable ``detector`` callable.
    """

    def __init__(self, patterns, detectors: Optional[List[Callable[[str], str]]] = None):
        self._patterns = list(patterns)
        self._detectors = list(detectors or [])

    def scrub_text(self, text):
        if not isinstance(text, str):
            return text
        for pattern, replacement in self._patterns:
            text = pattern.sub(replacement, text)
        for detector in self._detectors:
            try:
                result = detector(text)
                if isinstance(result, str):
                    text = result
            except Exception:  # noqa: BLE001 - a bad detector must not break ingest
                logger.warning("redaction detector failed; skipping", exc_info=True)
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


def _resolve_detectors(names) -> List[Callable[[str], str]]:
    """Map configured detector names to registered callables, warning on misses."""
    detectors = []
    for name in names or []:
        detector = get_detector(name)
        if detector is None:
            logger.warning("INGEST_REDACT_DETECTORS: no detector registered as %r", name)
            continue
        detectors.append(detector)
    return detectors


def build_ingest_redactor(config) -> Optional[Redactor]:
    """Build a :class:`Redactor` from app config, or None when disabled."""
    if not config.get("INGEST_REDACT"):
        return None
    patterns = list(_BUILTIN_PATTERNS) + _compile_extra(config.get("INGEST_REDACT_PATTERNS"))
    detectors = _resolve_detectors(config.get("INGEST_REDACT_DETECTORS"))
    return Redactor(patterns, detectors=detectors)


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
