"""Ship finished traces to a running AgentScope server over HTTP.

The exporter maps each trace's root/LLM span onto the platform's request-trace
schema and ``POST``\\s it to ``<endpoint>/api/traces`` — the same public
ingestion endpoint the rest of the platform uses, so no server change is needed.

Only the Python standard library is used (``urllib``), and every failure is
swallowed (logged at debug) so observability never breaks the host app.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

from ..span import SpanKind, Trace
from .base import Exporter

logger = logging.getLogger("agentscope")


class HTTPExporter(Exporter):
    """POST finished traces to an AgentScope server's ``/api/traces`` endpoint."""

    def __init__(
        self,
        endpoint: str,
        api_key: Optional[str] = None,
        timeout: float = 5.0,
        default_model: Optional[str] = None,
        headers: Optional[dict] = None,
    ):
        self._base = endpoint.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._default_model = default_model
        self._headers = dict(headers or {})

    def export(self, trace: Trace) -> None:
        payload = self._to_request_trace(trace)
        try:
            self._post("/api/traces", payload)
        except (urllib.error.URLError, OSError, ValueError) as exc:  # pragma: no cover
            logger.debug("agentscope HTTP export failed: %s", exc)

    # -- mapping ------------------------------------------------------------

    def _to_request_trace(self, trace: Trace) -> dict:
        """Project a trace onto the platform's request-trace payload."""
        root = trace.root
        # Prefer an explicit LLM span for model/token/cost details.
        llm = next((s for s in trace.spans if s.kind == SpanKind.LLM), root)
        attrs = {**root.attributes, **llm.attributes}
        tokens = llm.tokens or root.tokens or {}

        retrieved = [
            {"query": s.input, "documents": s.output}
            for s in trace.spans
            if s.kind == SpanKind.RETRIEVER
        ]

        return {
            "model_name": attrs.get("model") or self._default_model or "unknown",
            "user_prompt": _text(root.input if root.input is not None else llm.input),
            "system_prompt": _text(attrs.get("system_prompt")),
            "final_response": _text(root.output if root.output is not None else llm.output),
            "input_tokens": tokens.get("input"),
            "output_tokens": tokens.get("output"),
            "total_tokens": trace.total_tokens() or tokens.get("total"),
            "estimated_cost": trace.total_cost() or None,
            "latency_ms": trace.latency_ms,
            "status": "success" if trace.status == "success" else "failed",
            "error_message": root.error,
            "tool_calls": trace.tool_calls() or None,
            "retrieved_documents": retrieved or None,
        }

    # -- transport ----------------------------------------------------------

    def _post(self, path: str, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        headers = {"Content-Type": "application/json", **self._headers}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(f"{self._base}{path}", data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # nosec - user-configured URL
            resp.read()


def _text(value):
    """Coerce a value to text for the platform's string columns."""
    if value is None or isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)
