"""Optional PII / secret redaction for trace payloads.

**Off by default.** Enable with ``agentscope.configure(redact=True)`` to scrub
common secrets and PII from span input, output, error and string attributes
*before they leave your process* — redaction runs at dispatch time, so nothing
sensitive is sent to the server or even kept in the local in-memory buffer.

Redaction is intentionally lossy (you trade debugging fidelity for privacy),
which is why it is opt-in. Extend or fully override it::

    # add your own patterns on top of the built-ins
    agentscope.configure(redact=True, redact_patterns=[(r"ACME-\\d+", "[ACCOUNT]")])

    # or take full control with a callable
    agentscope.configure(redact=True, redactor=my_scrub_fn)  # Callable[[str], str]
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

# (compiled pattern, replacement). Ordered specific-before-generic. Best-effort:
# tuned to over-redact rather than leak (appropriate for an opt-in privacy knob).
_BUILTIN_PATTERNS = [
    (re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._-]{8,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[REDACTED_CC]"),
    (re.compile(r"\b(?:\+?\d{1,3}[ -]?)?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}\b"), "[REDACTED_PHONE]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED_IP]"),
]

# Attribute keys that are never PII and must survive redaction (they drive
# dashboards/cost/segmentation). Every *other* string attribute is scrubbed.
_SAFE_ATTRIBUTE_KEYS = frozenset({"model", "streaming", "temperature", "kind"})


class Redactor:
    """Scrubs strings (and strings nested in dicts/lists) using patterns or a callable."""

    def __init__(self, patterns=None, custom: Optional[Callable[[str], str]] = None):
        self._patterns = list(patterns) if patterns is not None else list(_BUILTIN_PATTERNS)
        self._custom = custom

    def scrub_text(self, text: Any) -> Any:
        if not isinstance(text, str):
            return text
        if self._custom is not None:
            return self._custom(text)
        for pattern, replacement in self._patterns:
            text = pattern.sub(replacement, text)
        return text

    def scrub_value(self, value: Any) -> Any:
        """Recursively scrub strings inside dicts/lists/tuples; leave others as-is."""
        if isinstance(value, str):
            return self.scrub_text(value)
        if isinstance(value, dict):
            return {k: self.scrub_value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return type(value)(self.scrub_value(v) for v in value)
        return value

    def scrub_span(self, span) -> None:
        """Scrub a span in place (input, output, error, non-safe string attributes)."""
        span.input = self.scrub_value(span.input)
        span.output = self.scrub_value(span.output)
        if isinstance(span.error, str):
            span.error = self.scrub_text(span.error)
        if span.attributes:
            span.attributes = {
                key: (value if key in _SAFE_ATTRIBUTE_KEYS else self.scrub_value(value))
                for key, value in span.attributes.items()
            }


def build_redactor(config) -> Optional[Redactor]:
    """Build a :class:`Redactor` from config, or None when redaction is disabled."""
    if not getattr(config, "redact", False):
        return None
    custom = getattr(config, "redactor", None)
    extra = getattr(config, "redact_patterns", ()) or ()
    patterns = list(_BUILTIN_PATTERNS) + [(re.compile(p), r) for p, r in extra]
    return Redactor(patterns=patterns, custom=custom)
