"""LangChain integration — auto-capture agent runs as AgentScope traces.

Register :class:`AgentScopeCallbackHandler` with any LangChain runnable and its
chains, LLM/chat-model calls, tools and retrievers are recorded as a single
nested trace — no decorators or manual spans in your code::

    from agentscope.integrations.langchain import AgentScopeCallbackHandler

    handler = AgentScopeCallbackHandler()
    agent.invoke({"input": "..."}, config={"callbacks": [handler]})

LangChain is an **optional** dependency (install ``agentscope-lite[langchain]``);
it is imported lazily here so ``import agentscope`` never requires it. The
handler builds the span tree from LangChain's ``run_id``/``parent_run_id`` (which
is why it works across threads and async tasks) and hands the finished trace to
the tracer, so it ships wherever you've pointed AgentScope (HTTP, console, …).
"""
from __future__ import annotations

import json
import logging
import threading
from functools import wraps
from typing import Any, Dict, Optional

try:  # LangChain is optional; fail loudly only when this module is imported.
    from langchain_core.callbacks.base import BaseCallbackHandler
except ImportError as exc:  # pragma: no cover - exercised only without langchain
    raise ImportError(
        "The LangChain integration requires langchain-core. Install it with: "
        'pip install "agentscope-lite[langchain]"'
    ) from exc

from ..instrument import (
    _ANTHROPIC_PRICES,
    _GEMINI_PRICES,
    _OPENAI_PRICES,
    _estimate_cost,
)
from ..span import Span, SpanKind, SpanStatus, Trace, _new_id
from ..tracer import get_tracer

logger = logging.getLogger("agentscope")

# Reuse the auto-instrumentation price tables so LangChain LLM steps are costed
# with the same numbers as direct SDK calls (unknown models stay uncosted).
_PRICES = {**_OPENAI_PRICES, **_ANTHROPIC_PRICES, **_GEMINI_PRICES}


def _guard(method):
    """Never let a callback exception escape into LangChain / the user's app."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:  # noqa: BLE001 - observability must not crash the app
            logger.debug("AgentScope LangChain handler error in %s", method.__name__, exc_info=True)
        return None

    return wrapper


def _name(serialized: Any, kwargs: dict) -> Optional[str]:
    name = kwargs.get("name")
    if name:
        return name
    if isinstance(serialized, dict):
        if serialized.get("name"):
            return serialized["name"]
        ident = serialized.get("id")
        if isinstance(ident, list) and ident:
            return ident[-1]
    return None


def _err(error: Any) -> str:
    return f"{type(error).__name__}: {error}"


def _coerce(value: Any) -> Any:
    """Keep JSON-friendly payloads as-is; stringify anything the exporter can't
    serialize (LangChain inputs/outputs are often rich objects)."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _messages_text(messages: Any) -> Optional[str]:
    """Flatten ``on_chat_model_start`` messages (List[List[BaseMessage]])."""
    if not messages:
        return None
    first = messages[0] if isinstance(messages, (list, tuple)) else messages
    parts = []
    for msg in first or []:
        content = getattr(msg, "content", None)
        role = getattr(msg, "type", None) or getattr(msg, "role", None)
        if isinstance(content, str) and content:
            parts.append(f"{role}: {content}" if role else content)
    return "\n".join(parts) if parts else None


def _tokens(input_tokens: Optional[int], output_tokens: Optional[int]) -> Optional[dict]:
    if input_tokens is None and output_tokens is None:
        return None
    return {
        "input": input_tokens,
        "output": output_tokens,
        "total": (input_tokens or 0) + (output_tokens or 0),
    }


def _parse_llm_result(response: Any):
    """Extract (text, input_tokens, output_tokens, model) from an LLMResult."""
    generations = getattr(response, "generations", None) or []
    first = generations[0][0] if generations and generations[0] else None

    text = getattr(first, "text", None) if first is not None else None
    if not text and first is not None:
        message = getattr(first, "message", None)
        text = getattr(message, "content", None) if message is not None else None

    llm_output = getattr(response, "llm_output", None) or {}
    usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
    output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
    model = llm_output.get("model_name") or llm_output.get("model")

    # Newer chat models carry usage_metadata / response_metadata on the message.
    if (input_tokens is None and output_tokens is None) and first is not None:
        message = getattr(first, "message", None)
        meta = getattr(message, "usage_metadata", None) if message is not None else None
        if isinstance(meta, dict):
            input_tokens = meta.get("input_tokens")
            output_tokens = meta.get("output_tokens")
        if not model and message is not None:
            rmeta = getattr(message, "response_metadata", None) or {}
            model = rmeta.get("model_name") or rmeta.get("model")

    return text, input_tokens, output_tokens, model


def _documents(documents: Any) -> list:
    docs = []
    for doc in documents or []:
        docs.append(
            {
                "content": getattr(doc, "page_content", None),
                "metadata": _coerce(getattr(doc, "metadata", None)),
            }
        )
    return docs


class AgentScopeCallbackHandler(BaseCallbackHandler):
    """A LangChain callback handler that records runs as AgentScope traces.

    Thread-safe: LangChain fires callbacks from worker threads and async tasks,
    so the ``run_id → span`` map is guarded by a lock and the span tree is built
    from ``run_id``/``parent_run_id`` rather than the tracer's contextvar stack.
    """

    #: LangChain reads this; keep False so our (already-guarded) handler never
    #: aborts a chain even if something unexpected slips through.
    raise_error = False

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spans: Dict[str, Span] = {}
        self._traces: Dict[str, Trace] = {}

    # -- span tree bookkeeping ----------------------------------------------

    def _start(
        self,
        kind: str,
        name: Optional[str],
        run_id: Any,
        parent_run_id: Any,
        input: Any = None,  # noqa: A002 - mirrors span API
        attributes: Optional[dict] = None,
    ) -> None:
        tracer = get_tracer()
        if not tracer.config.enabled:
            return
        with self._lock:
            parent = self._spans.get(str(parent_run_id)) if parent_run_id is not None else None
            span = Span(
                name=name or kind,
                kind=kind,
                trace_id=parent.trace_id if parent else _new_id(),
                parent_id=parent.span_id if parent else None,
                attributes=dict(attributes or {}),
                input=_coerce(input),
            )
            self._spans[str(run_id)] = span
            if parent is None:
                self._traces[span.trace_id] = Trace(trace_id=span.trace_id, root=span)
            trace = self._traces.get(span.trace_id)
            if trace is not None:
                trace.spans.append(span)

    def _end(
        self,
        run_id: Any,
        output: Any = None,
        tokens: Optional[dict] = None,
        cost: Optional[float] = None,
        model: Optional[str] = None,
        attributes: Optional[dict] = None,
        status: str = SpanStatus.SUCCESS,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            span = self._spans.pop(str(run_id), None)
            if span is None:
                return
            if output is not None:
                span.output = _coerce(output)
            if tokens is not None:
                span.tokens = tokens
            if cost is not None:
                span.cost = cost
            if model:
                span.set_attribute("model", model)
            if attributes:
                span.attributes.update(attributes)
            span._finalize(status=status, error=error)
            trace = self._traces.pop(span.trace_id, None) if span.parent_id is None else None
        # Dispatch outside the lock — export can be slow and must not block peers.
        if trace is not None:
            get_tracer().emit(trace)

    # -- chains -------------------------------------------------------------

    @_guard
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        name = _name(serialized, kwargs)
        kind = SpanKind.AGENT if (name and "agent" in name.lower()) else SpanKind.STEP
        self._start(kind, name, run_id, parent_run_id, input=inputs)

    @_guard
    def on_chain_end(self, outputs, *, run_id, **kwargs):
        self._end(run_id, output=outputs)

    @_guard
    def on_chain_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status=SpanStatus.FAILED, error=_err(error))

    # -- LLMs / chat models -------------------------------------------------

    @_guard
    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, **kwargs):
        text = prompts[0] if prompts else None
        self._start(SpanKind.LLM, _name(serialized, kwargs) or "llm", run_id, parent_run_id, input=text)

    @_guard
    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        self._start(
            SpanKind.LLM,
            _name(serialized, kwargs) or "chat_model",
            run_id,
            parent_run_id,
            input=_messages_text(messages),
        )

    @_guard
    def on_llm_end(self, response, *, run_id, **kwargs):
        text, input_tokens, output_tokens, model = _parse_llm_result(response)
        self._end(
            run_id,
            output=text,
            tokens=_tokens(input_tokens, output_tokens),
            cost=_estimate_cost(model, input_tokens, output_tokens, _PRICES),
            model=model,
        )

    @_guard
    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status=SpanStatus.FAILED, error=_err(error))

    # -- tools --------------------------------------------------------------

    @_guard
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        self._start(SpanKind.TOOL, _name(serialized, kwargs) or "tool", run_id, parent_run_id, input=input_str)

    @_guard
    def on_tool_end(self, output, *, run_id, **kwargs):
        self._end(run_id, output=output)

    @_guard
    def on_tool_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status=SpanStatus.FAILED, error=_err(error))

    # -- retrievers ---------------------------------------------------------

    @_guard
    def on_retriever_start(self, serialized, query, *, run_id, parent_run_id=None, **kwargs):
        self._start(
            SpanKind.RETRIEVER, _name(serialized, kwargs) or "retriever", run_id, parent_run_id, input=query
        )

    @_guard
    def on_retriever_end(self, documents, *, run_id, **kwargs):
        docs = _documents(documents)
        self._end(run_id, output=docs, attributes={"num_documents": len(docs)})

    @_guard
    def on_retriever_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status=SpanStatus.FAILED, error=_err(error))


__all__ = ["AgentScopeCallbackHandler"]
