"""Auto-instrumentation for third-party LLM clients.

Wrap a provider client **once** and every call becomes a captured LLM span — no
per-call decorators or context managers. This closes the "capture is opt-in for
every call site" gap for the most common case.

Dependency-free by design: we never ``import openai``. We wrap the client
*instance* you pass in (duck-typed), so the SDK stays lightweight and works with
whatever version of the provider library you happen to have installed.

Currently supports the OpenAI Python client (``openai>=1.0``), both sync
(``OpenAI``) and async (``AsyncOpenAI``). Streaming responses (``stream=True``)
are recorded as a minimal span (model + input) *without* output/token capture,
so we never consume your stream; full streaming capture is a planned follow-up.

Example
-------
    import agentscope
    from openai import OpenAI

    agentscope.configure(endpoint="http://localhost:8000", api_key="sk-...")
    client = agentscope.instrument_openai(OpenAI())

    client.chat.completions.create(            # automatically traced
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
    )
"""
from __future__ import annotations

import inspect
from typing import Any, Optional

from .api import trace
from .span import SpanStatus

# OpenAI chat model prices (USD per 1K tokens): (input, output). Versioned names
# like ``gpt-4o-2024-05-13`` match their base entry. Cost estimation is
# best-effort; unknown models simply record no cost. (Made configurable in the
# cost-accuracy work — see the platform price table.)
_OPENAI_PRICES = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0005, 0.0015),
}


def _estimate_cost(
    model: Optional[str],
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    table: Optional[dict] = None,
) -> Optional[float]:
    """Estimate cost in USD from the price table, or None if the model is unknown.

    ``table`` (default :data:`_OPENAI_PRICES`) maps a base model name to
    ``(input_per_1k, output_per_1k)``; versioned names match by prefix.
    """
    if not model:
        return None
    table = table if table is not None else _OPENAI_PRICES
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
    """Read ``name`` from a dict or an object (OpenAI returns pydantic models)."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _split_messages(messages: Any) -> tuple[Optional[str], Optional[str]]:
    """Return ``(system_prompt, user_prompt)`` text from a chat ``messages`` list."""
    if not isinstance(messages, (list, tuple)):
        return None, None
    system = None
    user = None
    for message in messages:
        role = _get(message, "role")
        content = _get(message, "content")
        if role == "system" and system is None:
            system = content
        elif role == "user":
            user = content  # keep the most recent user turn as the prompt
    return system, user


def _extract_response(resp: Any) -> tuple[Optional[str], Optional[int], Optional[int], Optional[str]]:
    """Best-effort ``(output_text, input_tokens, output_tokens, model)`` from a response."""
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


def _start_span(kwargs: dict):
    """Open an LLM span from the create() kwargs; return (span, model, streaming)."""
    model = kwargs.get("model")
    system_prompt, user_prompt = _split_messages(kwargs.get("messages"))
    attributes = {"model": model}
    if system_prompt is not None:
        attributes["system_prompt"] = system_prompt
    span = trace.start("openai.chat.completions", kind="llm", input=user_prompt, **attributes)
    return span, model, bool(kwargs.get("stream"))


def _finish_span(span, model, resp, streaming: bool, prices: Optional[dict] = None) -> None:
    """Populate output/tokens/cost on success and end the span."""
    if streaming:
        span.set_attribute("streaming", True)
        trace.end(span, status=SpanStatus.SUCCESS)
        return
    output_text, input_tokens, output_tokens, resp_model = _extract_response(resp)
    if output_text is not None:
        span.set_output(output_text)
    if input_tokens is not None or output_tokens is not None:
        span.set_tokens(input=input_tokens, output=output_tokens)
        span.set_cost(_estimate_cost(model or resp_model, input_tokens, output_tokens, prices))
    trace.end(span, status=SpanStatus.SUCCESS)


def _traced_create(original, prices: Optional[dict] = None):
    """Return a traced replacement for a ``chat.completions.create`` callable."""
    if inspect.iscoroutinefunction(original):

        async def async_create(*args, **kwargs):
            span, model, streaming = _start_span(kwargs)
            try:
                resp = await original(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - record then re-raise
                trace.end(span, status=SpanStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
                raise
            _finish_span(span, model, resp, streaming, prices)
            return resp

        async_create.__agentscope_instrumented__ = True
        return async_create

    def create(*args, **kwargs):
        span, model, streaming = _start_span(kwargs)
        try:
            resp = original(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            trace.end(span, status=SpanStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
            raise
        _finish_span(span, model, resp, streaming, prices)
        return resp

    create.__agentscope_instrumented__ = True
    return create


def instrument_openai(client, prices: Optional[dict] = None):
    """Wrap an OpenAI client so ``chat.completions.create`` is auto-traced.

    Returns the same client (mutated in place) for convenience. Idempotent:
    wrapping an already-instrumented client is a no-op. Works with the sync
    ``OpenAI`` and async ``AsyncOpenAI`` clients (``openai>=1.0``).

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

    original = completions.create
    if getattr(original, "__agentscope_instrumented__", False):
        return client
    merged = {**_OPENAI_PRICES, **prices} if prices else None
    completions.create = _traced_create(original, merged)
    return client
