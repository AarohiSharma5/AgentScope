"""Auto-instrumentation for third-party LLM clients.

Wrap a provider client **once** and every call becomes a captured LLM span — no
per-call decorators or context managers. This closes the "capture is opt-in for
every call site" gap so an agent's model calls are observed no matter which
provider a given step uses.

Dependency-free by design: we never ``import openai`` / ``import anthropic``. We
wrap the client *instance* you pass in (duck-typed), so the SDK stays lightweight
and works with whatever version of the provider library you happen to have.

Supported today:

* **OpenAI** (``openai>=1.0``) — ``instrument_openai`` — sync ``OpenAI`` and async
  ``AsyncOpenAI`` (``chat.completions.create``). This also covers OpenAI-compatible
  / local servers (Ollama, vLLM, Together, Groq, OpenRouter) since they use the
  same client with a different ``base_url``.
* **Anthropic** (``anthropic>=0.20``) — ``instrument_anthropic`` — sync ``Anthropic``
  and async ``AsyncAnthropic`` (``messages.create``).

Streaming (``stream=True``) is fully captured for both: the returned stream is
wrapped so chunks pass straight through to you while we accumulate the output
text, and the span is finalised when the stream is exhausted, closed, or its
``with`` block exits — we never consume or alter your stream. Token usage/cost on
a stream depends on the provider emitting usage (OpenAI needs
``stream_options={"include_usage": True}``; Anthropic sends it in stream events);
the full output text is captured either way.

Example
-------
    import agentscope
    from openai import OpenAI
    from anthropic import Anthropic

    agentscope.configure(endpoint="http://localhost:8000", api_key="sk-...")
    oai = agentscope.instrument_openai(OpenAI())
    claude = agentscope.instrument_anthropic(Anthropic())

    oai.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    claude.messages.create(model="claude-3-5-sonnet-latest", max_tokens=64,
                           messages=[{"role": "user", "content": "hi"}])
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .api import trace
from .span import SpanStatus
from .tracer import get_tracer

# Per-provider price tables (USD per 1K tokens): (input, output). Versioned names
# like ``gpt-4o-2024-05-13`` / ``claude-3-5-sonnet-20241022`` match by prefix.
# Best-effort; unknown models record no cost (never a wrong one).
_OPENAI_PRICES = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0005, 0.0015),
}

_ANTHROPIC_PRICES = {
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-5-haiku": (0.0008, 0.004),
    "claude-3-opus": (0.015, 0.075),
    "claude-3-sonnet": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
}


def _estimate_cost(
    model: Optional[str],
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    table: Optional[dict] = None,
) -> Optional[float]:
    """Estimate cost in USD from a price table, or None if the model is unknown.

    ``table`` maps a base model name to ``(input_per_1k, output_per_1k)``;
    versioned names match by prefix.
    """
    if not model or not table:
        return None
    prices = None
    for base, table_prices in table.items():
        if model == base or model.startswith(base + "-"):
            prices = table_prices
            break
    if prices is None:
        return None
    in_price, out_price = prices
    return round(
        (input_tokens or 0) / 1000 * in_price + (output_tokens or 0) / 1000 * out_price, 8
    )


def _get(obj: Any, name: str) -> Any:
    """Read ``name`` from a dict or an object (SDKs return pydantic models)."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _text_from_content(content: Any) -> Optional[str]:
    """Flatten a message ``content`` (str, or a list of ``{type,text}`` blocks)."""
    if content is None or isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = [_get(block, "text") for block in content]
        parts = [p for p in parts if isinstance(p, str)]
        return "".join(parts) if parts else None
    return None


# ---------------------------------------------------------------------------
# Provider adapters — the only provider-specific logic. Each supplies:
#   prompts(kwargs)  -> (system_prompt, user_prompt)
#   extract(resp)    -> (output_text, input_tokens, output_tokens, model)
#   accumulate(chunk, state) -> fold a streamed chunk into normalised `state`
# `state` keys: text (list), input_tokens, output_tokens, resp_model.
# ---------------------------------------------------------------------------


@dataclass
class _Adapter:
    name: str
    prices: dict
    prompts: Callable[[dict], tuple]
    extract: Callable[[Any], tuple]
    accumulate: Callable[[Any, dict], None]


# -- OpenAI -----------------------------------------------------------------


def _openai_prompts(kwargs: dict):
    messages = kwargs.get("messages")
    system = user = None
    if isinstance(messages, (list, tuple)):
        for message in messages:
            role = _get(message, "role")
            content = _get(message, "content")
            if role == "system" and system is None:
                system = _text_from_content(content)
            elif role == "user":
                user = _text_from_content(content)  # keep most recent user turn
    return system, user


def _openai_extract(resp: Any):
    output_text = None
    choices = _get(resp, "choices")
    if choices:
        first = choices[0]
        message = _get(first, "message")
        output_text = _get(message, "content") if message is not None else None
        if output_text is None:
            output_text = _get(first, "text")
    usage = _get(resp, "usage") or {}
    return (
        output_text,
        _get(usage, "prompt_tokens"),
        _get(usage, "completion_tokens"),
        _get(resp, "model"),
    )


def _openai_accumulate(chunk, state: dict) -> None:
    model = _get(chunk, "model")
    if model:
        state["resp_model"] = model
    usage = _get(chunk, "usage")
    if usage is not None:
        if _get(usage, "prompt_tokens") is not None:
            state["input_tokens"] = _get(usage, "prompt_tokens")
        if _get(usage, "completion_tokens") is not None:
            state["output_tokens"] = _get(usage, "completion_tokens")
    choices = _get(chunk, "choices")
    if choices:
        delta = _get(choices[0], "delta")
        content = _get(delta, "content") if delta is not None else None
        if content:
            state["text"].append(content)


_OPENAI_ADAPTER = _Adapter(
    name="openai.chat.completions",
    prices=_OPENAI_PRICES,
    prompts=_openai_prompts,
    extract=_openai_extract,
    accumulate=_openai_accumulate,
)


# -- Anthropic --------------------------------------------------------------


def _anthropic_prompts(kwargs: dict):
    system = _text_from_content(kwargs.get("system"))
    user = None
    messages = kwargs.get("messages")
    if isinstance(messages, (list, tuple)):
        for message in messages:
            if _get(message, "role") == "user":
                user = _text_from_content(_get(message, "content"))
    return system, user


def _anthropic_extract(resp: Any):
    # ``content`` is a list of blocks; concatenate the text ones.
    text = _text_from_content(_get(resp, "content"))
    usage = _get(resp, "usage") or {}
    return (
        text,
        _get(usage, "input_tokens"),
        _get(usage, "output_tokens"),
        _get(resp, "model"),
    )


def _anthropic_accumulate(event, state: dict) -> None:
    """Fold an Anthropic Messages stream event into ``state``.

    Text arrives in ``content_block_delta`` events; input tokens in
    ``message_start`` and output tokens in ``message_delta``.
    """
    etype = _get(event, "type")
    if etype == "message_start":
        message = _get(event, "message")
        if message is not None:
            model = _get(message, "model")
            if model:
                state["resp_model"] = model
            usage = _get(message, "usage")
            if usage is not None and _get(usage, "input_tokens") is not None:
                state["input_tokens"] = _get(usage, "input_tokens")
    elif etype == "content_block_delta":
        delta = _get(event, "delta")
        text = _get(delta, "text") if delta is not None else None
        if text:
            state["text"].append(text)
    elif etype == "message_delta":
        usage = _get(event, "usage")
        if usage is not None and _get(usage, "output_tokens") is not None:
            state["output_tokens"] = _get(usage, "output_tokens")


_ANTHROPIC_ADAPTER = _Adapter(
    name="anthropic.messages",
    prices=_ANTHROPIC_PRICES,
    prompts=_anthropic_prompts,
    extract=_anthropic_extract,
    accumulate=_anthropic_accumulate,
)


# ---------------------------------------------------------------------------
# Provider-agnostic span machinery
# ---------------------------------------------------------------------------


def _start_span(adapter: _Adapter, kwargs: dict):
    """Open an LLM span from create() kwargs; return (span, model, streaming).

    Streaming spans are opened *detached* from the active nesting context: the
    caller iterates the returned stream after ``create()`` returns, so the span
    outlives the call and must not become the parent of whatever runs next.
    """
    model = kwargs.get("model")
    system_prompt, user_prompt = adapter.prompts(kwargs)
    attributes = {"model": model}
    if system_prompt is not None:
        attributes["system_prompt"] = system_prompt
    streaming = bool(kwargs.get("stream"))
    tracer = get_tracer()
    start = tracer.start_span_detached if streaming else tracer.start_span
    span = start(adapter.name, kind="llm", attributes=attributes, input=user_prompt)
    return span, model, streaming


def _finish_span(adapter: _Adapter, span, model, resp, prices: dict) -> None:
    """Populate output/tokens/cost from a non-streaming response and end the span."""
    output_text, input_tokens, output_tokens, resp_model = adapter.extract(resp)
    if output_text is not None:
        span.set_output(output_text)
    if input_tokens is not None or output_tokens is not None:
        span.set_tokens(input=input_tokens, output=output_tokens)
        span.set_cost(_estimate_cost(model or resp_model, input_tokens, output_tokens, prices))
    trace.end(span, status=SpanStatus.SUCCESS)


def _finalize_stream(span, model, state: dict, prices, error: Optional[str]) -> None:
    """End a streaming span, recording accumulated output/tokens/cost (or an error)."""
    span.set_attribute("streaming", True)
    if error is not None:
        trace.end(span, status=SpanStatus.FAILED, error=error)
        return
    text = "".join(state["text"])
    if text:
        span.set_output(text)
    input_tokens = state.get("input_tokens")
    output_tokens = state.get("output_tokens")
    if input_tokens is not None or output_tokens is not None:
        span.set_tokens(input=input_tokens, output=output_tokens)
        span.set_cost(_estimate_cost(model or state.get("resp_model"), input_tokens, output_tokens, prices))
    else:
        # Provider didn't emit usage on the stream (e.g. OpenAI without
        # stream_options include_usage). Output text is still captured.
        span.set_attribute("streaming_usage", "unavailable")
    trace.end(span, status=SpanStatus.SUCCESS)


def _new_state() -> dict:
    return {"text": [], "input_tokens": None, "output_tokens": None, "resp_model": None}


class _TracedStream:
    """Wraps a sync provider stream: passes chunks through, captures the response.

    Finalises the span exactly once — when the stream is exhausted, closed, or
    its ``with`` block exits — so we never consume or alter your stream.
    """

    def __init__(self, stream, span, model, prices, accumulate):
        self._stream = stream
        self._span = span
        self._model = model
        self._prices = prices
        self._accumulate = accumulate
        self._state = _new_state()
        self._finalized = False

    def _finalize(self, error: Optional[str] = None) -> None:
        if self._finalized:
            return
        self._finalized = True
        _finalize_stream(self._span, self._model, self._state, self._prices, error)

    def __iter__(self):
        return self

    def __next__(self):
        try:
            chunk = next(self._stream)
        except StopIteration:
            self._finalize()
            raise
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            self._finalize(error=f"{type(exc).__name__}: {exc}")
            raise
        self._accumulate(chunk, self._state)
        return chunk

    def __enter__(self):
        if hasattr(self._stream, "__enter__"):
            self._stream.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._finalize(error=f"{exc_type.__name__}: {exc}" if exc is not None else None)
        if hasattr(self._stream, "__exit__"):
            return self._stream.__exit__(exc_type, exc, tb)
        return False

    def close(self):
        self._finalize()
        if hasattr(self._stream, "close"):
            self._stream.close()

    def __getattr__(self, name):
        # Delegate anything we don't define (e.g. .response, .text_stream).
        return getattr(self._stream, name)


class _TracedAsyncStream:
    """Async counterpart of :class:`_TracedStream`."""

    def __init__(self, stream, span, model, prices, accumulate):
        self._stream = stream
        self._span = span
        self._model = model
        self._prices = prices
        self._accumulate = accumulate
        self._state = _new_state()
        self._finalized = False

    def _finalize(self, error: Optional[str] = None) -> None:
        if self._finalized:
            return
        self._finalized = True
        _finalize_stream(self._span, self._model, self._state, self._prices, error)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            chunk = await self._stream.__anext__()
        except StopAsyncIteration:
            self._finalize()
            raise
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            self._finalize(error=f"{type(exc).__name__}: {exc}")
            raise
        self._accumulate(chunk, self._state)
        return chunk

    async def __aenter__(self):
        if hasattr(self._stream, "__aenter__"):
            await self._stream.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._finalize(error=f"{exc_type.__name__}: {exc}" if exc is not None else None)
        if hasattr(self._stream, "__aexit__"):
            return await self._stream.__aexit__(exc_type, exc, tb)
        return False

    async def aclose(self):
        self._finalize()
        if hasattr(self._stream, "aclose"):
            await self._stream.aclose()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _traced_create(original, adapter: _Adapter, prices: dict):
    """Return a traced replacement for a provider's ``create`` callable."""
    if inspect.iscoroutinefunction(original):

        async def async_create(*args, **kwargs):
            span, model, streaming = _start_span(adapter, kwargs)
            try:
                resp = await original(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - record then re-raise
                trace.end(span, status=SpanStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
                raise
            if streaming:
                return _TracedAsyncStream(resp, span, model, prices, adapter.accumulate)
            _finish_span(adapter, span, model, resp, prices)
            return resp

        async_create.__agentscope_instrumented__ = True
        return async_create

    def create(*args, **kwargs):
        span, model, streaming = _start_span(adapter, kwargs)
        try:
            resp = original(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            trace.end(span, status=SpanStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
            raise
        if streaming:
            return _TracedStream(resp, span, model, prices, adapter.accumulate)
        _finish_span(adapter, span, model, resp, prices)
        return resp

    create.__agentscope_instrumented__ = True
    return create


def _instrument(container, adapter: _Adapter, prices_override: Optional[dict]):
    """Wrap ``container.create`` for one provider (idempotent)."""
    original = container.create
    if getattr(original, "__agentscope_instrumented__", False):
        return
    prices = {**adapter.prices, **(prices_override or {})}
    container.create = _traced_create(original, adapter, prices)


def instrument_openai(client, prices: Optional[dict] = None):
    """Wrap an OpenAI client so ``chat.completions.create`` is auto-traced.

    Returns the same client (mutated in place) for convenience. Idempotent:
    wrapping an already-instrumented client is a no-op. Works with the sync
    ``OpenAI`` and async ``AsyncOpenAI`` clients (``openai>=1.0``), and with
    OpenAI-compatible/local servers using the same client.

    Pass ``prices`` (``{model: (input_per_1k, output_per_1k)}``) to price your
    own/fine-tuned models; it's merged over the built-in table so unknown models
    still record no cost rather than a wrong one.
    """
    try:
        completions = client.chat.completions
    except AttributeError as exc:
        raise TypeError(
            "instrument_openai expects an OpenAI client exposing "
            ".chat.completions.create (openai>=1.0)."
        ) from exc
    _instrument(completions, _OPENAI_ADAPTER, prices)
    return client


def instrument_anthropic(client, prices: Optional[dict] = None):
    """Wrap an Anthropic client so ``messages.create`` is auto-traced.

    Returns the same client (mutated in place) for convenience. Idempotent.
    Works with the sync ``Anthropic`` and async ``AsyncAnthropic`` clients
    (``anthropic>=0.20``). Captures the system prompt (top-level ``system=``),
    the latest user turn, the response text, token usage and estimated cost;
    streaming (``stream=True``) is captured too.

    Pass ``prices`` to price models missing from the built-in Claude table.
    """
    try:
        messages = client.messages
    except AttributeError as exc:
        raise TypeError(
            "instrument_anthropic expects an Anthropic client exposing "
            ".messages.create (anthropic>=0.20)."
        ) from exc
    _instrument(messages, _ANTHROPIC_ADAPTER, prices)
    return client
