"""LlamaIndex integration — auto-capture queries/agents as AgentScope traces.

Register :class:`AgentScopeCallbackHandler` on LlamaIndex's ``Settings`` (or a
``CallbackManager``) and each query / chat / agent run — with its LLM calls,
retrievals, embeddings and tool (function) calls — is recorded as one nested
trace::

    from llama_index.core import Settings
    from llama_index.core.callbacks import CallbackManager
    from agentscope.integrations.llamaindex import AgentScopeCallbackHandler

    Settings.callback_manager = CallbackManager([AgentScopeCallbackHandler()])

LlamaIndex is an **optional** dependency (install ``agentscope-lite[llamaindex]``);
it's imported lazily here so ``import agentscope`` never requires it. The handler
builds the span tree from LlamaIndex's ``event_id``/``parent_id`` and the
``start_trace``/``end_trace`` bookends, then hands the finished trace to the
tracer (so it ships wherever AgentScope is configured).
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

try:  # LlamaIndex is optional; fail loudly only when this module is imported.
    from llama_index.core.callbacks.base_handler import BaseCallbackHandler
except ImportError as exc:  # pragma: no cover - exercised only without llama-index
    raise ImportError(
        "The LlamaIndex integration requires llama-index-core. Install it with: "
        'pip install "agentscope-lite[llamaindex]"'
    ) from exc

from ..span import Span, SpanKind, SpanStatus, Trace, _new_id
from ..tracer import get_tracer
from ._common import _get
from ._common import coerce as _coerce
from ._common import err as _err
from ._common import estimate_cost as _estimate_cost
from ._common import guard as _guard
from ._common import messages_text as _messages_text
from ._common import tokens as _tokens

# LlamaIndex uses "root" as the parent id of top-level events within a trace.
_ROOT = "root"

# Map LlamaIndex CBEventType (str values) to AgentScope span kinds. Anything not
# listed becomes a generic step; a few noisy low-value events are skipped.
_KIND_BY_EVENT = {
    "llm": SpanKind.LLM,
    "retrieve": SpanKind.RETRIEVER,
    "embedding": SpanKind.RETRIEVER,
    "function_call": SpanKind.TOOL,
    "agent_step": SpanKind.STEP,
    "query": SpanKind.STEP,
    "synthesize": SpanKind.STEP,
    "sub_question": SpanKind.STEP,
}
_IGNORE_EVENTS = {"chunking", "node_parsing", "templating", "tree"}


def _event_name(event_type: Any) -> str:
    """CBEventType is a str-enum; normalise to a plain lowercase string."""
    value = getattr(event_type, "value", event_type)
    return str(value).lower()


def _nodes(nodes: Any) -> List[dict]:
    docs = []
    for item in nodes or []:
        node = getattr(item, "node", item)
        content = None
        getter = getattr(node, "get_content", None)
        if callable(getter):
            try:
                content = getter()
            except Exception:  # noqa: BLE001 - best-effort text extraction
                content = None
        if content is None:
            content = getattr(node, "text", None)
        docs.append({"content": content, "score": getattr(item, "score", None)})
    return docs


def _parse_llm_end(payload: dict):
    """Extract (text, input_tokens, output_tokens, model) from an LLM end payload."""
    resp = payload.get("response") if payload else None
    if resp is None and payload:
        resp = payload.get("completion")

    text = getattr(resp, "text", None)
    if not text:
        message = getattr(resp, "message", None)
        text = getattr(message, "content", None) if message is not None else None
    if text is None and isinstance(resp, str):
        text = resp

    raw = getattr(resp, "raw", None)
    usage = _get(raw, "usage") if raw is not None else None
    input_tokens = output_tokens = model = None
    if usage is not None:
        input_tokens = _get(usage, "prompt_tokens") or _get(usage, "input_tokens")
        output_tokens = _get(usage, "completion_tokens") or _get(usage, "output_tokens")
    if raw is not None:
        model = _get(raw, "model")
    if not model and resp is not None:
        meta = getattr(resp, "additional_kwargs", None) or {}
        model = meta.get("model") if isinstance(meta, dict) else None
    return text, input_tokens, output_tokens, model


class AgentScopeCallbackHandler(BaseCallbackHandler):
    """A LlamaIndex callback handler that records runs as AgentScope traces.

    Thread-safe: the ``event_id → span`` map is lock-guarded and the tree is
    built from LlamaIndex's event ids, not the tracer's contextvar stack.
    """

    def __init__(self) -> None:
        super().__init__(event_starts_to_ignore=[], event_ends_to_ignore=[])
        self._lock = threading.Lock()
        self._spans: Dict[str, Span] = {}
        self._trace: Optional[Trace] = None
        self._depth = 0  # nested start_trace/end_trace calls; only outermost emits

    # -- trace bookends -----------------------------------------------------

    @_guard
    def start_trace(self, trace_id: Optional[str] = None) -> None:
        with self._lock:
            self._depth += 1
            if self._trace is not None:
                return  # already inside a trace; ignore nested bookends
            if not get_tracer().config.enabled:
                return
            name = trace_id or "llamaindex"
            kind = SpanKind.AGENT if any(k in name for k in ("agent", "chat")) else SpanKind.STEP
            root = Span(name=name, kind=kind, trace_id=_new_id())
            self._trace = Trace(trace_id=root.trace_id, root=root)
            self._trace.spans.append(root)
            self._spans = {_ROOT: root}

    @_guard
    def end_trace(self, trace_id: Optional[str] = None, trace_map: Optional[dict] = None) -> None:
        with self._lock:
            self._depth = max(0, self._depth - 1)
            if self._depth > 0 or self._trace is None:
                return
            trace = self._trace
            root = trace.root
            # Close any spans still open (defensive) then the root.
            for span in trace.spans:
                if span.is_running and span is not root:
                    span._finalize()
            root._finalize()
            self._trace = None
            self._spans = {}
        get_tracer().emit(trace)

    # -- events -------------------------------------------------------------

    @_guard
    def on_event_start(
        self,
        event_type: Any,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        parent_id: str = "",
        **kwargs: Any,
    ) -> str:
        event_id = event_id or _new_id()
        name = _event_name(event_type)
        if name in _IGNORE_EVENTS:
            return event_id
        with self._lock:
            if self._trace is None:
                return event_id  # events outside a trace bookend are dropped
            parent = self._spans.get(parent_id or _ROOT) or self._trace.root
            kind = _KIND_BY_EVENT.get(name, SpanKind.STEP)
            span = Span(
                name=name,
                kind=kind,
                trace_id=parent.trace_id,
                parent_id=parent.span_id,
                input=_coerce(self._event_input(name, payload)),
            )
            self._spans[event_id] = span
            self._trace.spans.append(span)
        return event_id

    @_guard
    def on_event_end(
        self,
        event_type: Any,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> None:
        name = _event_name(event_type)
        with self._lock:
            span = self._spans.get(event_id)
            if span is None:
                return
            self._apply_event_end(span, name, payload or {})
            span._finalize()

    # -- payload mapping ----------------------------------------------------

    @staticmethod
    def _event_input(name: str, payload: Optional[dict]) -> Any:
        if not payload:
            return None
        if name == "llm":
            return payload.get("formatted_prompt") or _messages_text(payload.get("messages"))
        if name in ("retrieve", "query"):
            return payload.get("query_str")
        if name == "function_call":
            return payload.get("function_call") or payload.get("tool")
        return None

    def _apply_event_end(self, span: Span, name: str, payload: dict) -> None:
        if payload.get("exception") is not None:
            span.status = SpanStatus.FAILED
            span.error = _err(payload["exception"])
            return
        if name == "llm":
            text, input_tokens, output_tokens, model = _parse_llm_end(payload)
            if text is not None:
                span.output = _coerce(text)
            span.tokens = _tokens(input_tokens, output_tokens)
            span.cost = _estimate_cost(model, input_tokens, output_tokens)
            if model:
                span.set_attribute("model", model)
        elif name in ("retrieve", "embedding"):
            docs = _nodes(payload.get("nodes"))
            span.output = _coerce(docs)
            span.set_attribute("num_documents", len(docs))
        elif name == "function_call":
            span.output = _coerce(payload.get("function_output"))
        else:
            resp = payload.get("response")
            if resp is not None:
                span.output = _coerce(getattr(resp, "response", None) or str(resp))


__all__ = ["AgentScopeCallbackHandler"]
