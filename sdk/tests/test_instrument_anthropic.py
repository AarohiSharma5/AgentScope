"""Tests for agentscope.instrument_anthropic (auto-instrumentation of Claude)."""
import asyncio

import pytest

import agentscope
from agentscope import SpanKind, SpanStatus, trace


# --- Minimal fakes shaped like the anthropic>=0.20 client -------------------


class _TextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Usage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _Message:
    def __init__(self, text, model, input_tokens, output_tokens):
        self.content = [_TextBlock(text)]
        self.model = model
        self.usage = _Usage(input_tokens, output_tokens)
        self.stop_reason = "end_turn"


class _Messages:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.messages = _Messages(response=response, error=error)


def _last():
    traces = trace.finished()
    assert traces, "expected a finished trace"
    return traces[-1]


# --- streaming event fakes --------------------------------------------------


class _StreamEvent:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _message_start(model, input_tokens):
    return _StreamEvent(
        type="message_start",
        message=_StreamEvent(model=model, usage=_Usage(input_tokens, 0)),
    )


def _text_delta(text):
    return _StreamEvent(type="content_block_delta", delta=_StreamEvent(type="text_delta", text=text))


def _message_delta(output_tokens):
    return _StreamEvent(type="message_delta", usage=_Usage(0, output_tokens))


# --- tests ------------------------------------------------------------------


def test_instrument_records_model_output_tokens_and_cost():
    resp = _Message("Hi there!", "claude-3-5-sonnet-20241022", input_tokens=15, output_tokens=6)
    client = agentscope.instrument_anthropic(_FakeClient(response=resp))

    out = client.messages.create(
        model="claude-3-5-sonnet-latest",
        max_tokens=64,
        system="You are helpful.",
        messages=[{"role": "user", "content": "Say hi"}],
    )
    assert out is resp  # unchanged

    span = _last().root
    assert span.kind == SpanKind.LLM
    assert span.status == SpanStatus.SUCCESS
    assert span.attributes["system_prompt"] == "You are helpful."
    assert span.input == "Say hi"
    assert span.output == "Hi there!"
    assert span.tokens == {"input": 15, "output": 6, "total": 21}
    # prefix match to claude-3-5-sonnet: 15/1000*0.003 + 6/1000*0.015 = 0.000135
    assert span.cost == pytest.approx(15 / 1000 * 0.003 + 6 / 1000 * 0.015)


def test_system_and_user_accept_block_lists():
    resp = _Message("ok", "claude-3-haiku-20240307", 3, 2)
    client = agentscope.instrument_anthropic(_FakeClient(response=resp))
    client.messages.create(
        model="claude-3-haiku",
        max_tokens=16,
        system=[{"type": "text", "text": "sys prompt"}],
        messages=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
    )
    span = _last().root
    assert span.attributes["system_prompt"] == "sys prompt"
    assert span.input == "hello"


def test_instrument_records_failure_and_reraises():
    client = agentscope.instrument_anthropic(_FakeClient(error=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        client.messages.create(
            model="claude-3-5-sonnet", max_tokens=8, messages=[{"role": "user", "content": "x"}]
        )
    span = _last().root
    assert span.status == SpanStatus.FAILED
    assert "RuntimeError" in span.error


def test_instrument_is_idempotent():
    client = _FakeClient(response=_Message("ok", "claude-3-haiku", 1, 1))
    agentscope.instrument_anthropic(client)
    wrapped = client.messages.create
    agentscope.instrument_anthropic(client)
    assert client.messages.create is wrapped


def test_unknown_model_records_no_cost():
    resp = _Message("hi", "claude-next-unknown", input_tokens=5, output_tokens=5)
    client = agentscope.instrument_anthropic(_FakeClient(response=resp))
    client.messages.create(
        model="claude-next-unknown", max_tokens=8, messages=[{"role": "user", "content": "x"}]
    )
    span = _last().root
    assert span.tokens == {"input": 5, "output": 5, "total": 10}
    assert span.cost is None


def test_streaming_captures_output_and_usage():
    events = [
        _message_start("claude-3-5-sonnet-20241022", input_tokens=12),
        _text_delta("Hel"),
        _text_delta("lo"),
        _message_delta(output_tokens=4),
    ]
    client = agentscope.instrument_anthropic(_FakeClient(response=iter(events)))
    out = client.messages.create(
        model="claude-3-5-sonnet",
        max_tokens=64,
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )
    assert trace.finished() == []  # not finalised until consumed
    assert list(out) == events  # pass-through

    span = _last().root
    assert span.status == SpanStatus.SUCCESS
    assert span.attributes.get("streaming") is True
    assert span.output == "Hello"
    assert span.tokens == {"input": 12, "output": 4, "total": 16}
    assert span.cost == pytest.approx(12 / 1000 * 0.003 + 4 / 1000 * 0.015)


def test_instrument_async_client():
    resp = _Message("async hi", "claude-3-haiku-20240307", 3, 4)

    class _AsyncMessages:
        async def create(self, **kwargs):
            return resp

    class _AsyncClient:
        def __init__(self):
            self.messages = _AsyncMessages()

    client = agentscope.instrument_anthropic(_AsyncClient())
    out = asyncio.run(
        client.messages.create(
            model="claude-3-haiku", max_tokens=8, messages=[{"role": "user", "content": "x"}]
        )
    )
    assert out is resp
    span = _last().root
    assert span.output == "async hi"
    assert span.tokens == {"input": 3, "output": 4, "total": 7}


def test_non_anthropic_client_raises_typeerror():
    with pytest.raises(TypeError):
        agentscope.instrument_anthropic(object())
