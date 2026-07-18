"""Tests for agentscope.instrument_openai (auto-instrumentation of OpenAI)."""
import asyncio

import pytest

import agentscope
from agentscope import SpanKind, SpanStatus, trace


# --- Minimal fakes shaped like the openai>=1.0 client -----------------------


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Usage:
    def __init__(self, prompt, completion):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion


class _Response:
    def __init__(self, content, model, prompt_tokens, completion_tokens):
        self.choices = [_Choice(content)]
        self.usage = _Usage(prompt_tokens, completion_tokens)
        self.model = model


class _Completions:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _Chat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.chat = _Chat(_Completions(response=response, error=error))


def _last():
    traces = trace.finished()
    assert traces, "expected a finished trace"
    return traces[-1]


def test_instrument_records_model_output_tokens_and_cost():
    resp = _Response("Hello there!", "gpt-4o", prompt_tokens=12, completion_tokens=8)
    client = agentscope.instrument_openai(_FakeClient(response=resp))

    out = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Say hi"},
        ],
    )
    assert out is resp  # the original response is returned unchanged

    tr = _last()
    span = tr.root
    assert span.kind == SpanKind.LLM
    assert span.status == SpanStatus.SUCCESS
    assert span.attributes["model"] == "gpt-4o"
    assert span.attributes["system_prompt"] == "You are helpful."
    assert span.input == "Say hi"
    assert span.output == "Hello there!"
    assert span.tokens == {"input": 12, "output": 8, "total": 20}
    # 12/1000*0.0025 + 8/1000*0.01 = 0.00011
    assert span.cost == pytest.approx(0.00011)


def test_instrument_records_failure_and_reraises():
    client = agentscope.instrument_openai(_FakeClient(error=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "x"}])
    span = _last().root
    assert span.status == SpanStatus.FAILED
    assert "RuntimeError" in span.error


def test_instrument_is_idempotent():
    client = _FakeClient(response=_Response("ok", "gpt-4o", 1, 1))
    agentscope.instrument_openai(client)
    wrapped = client.chat.completions.create
    agentscope.instrument_openai(client)  # second call must not double-wrap
    assert client.chat.completions.create is wrapped


def test_streaming_records_minimal_span_without_consuming():
    # A stream=True call returns an iterator; we must not consume it, so no
    # output/tokens are captured — just a span flagged streaming.
    stream_sentinel = iter(["chunk"])
    client = agentscope.instrument_openai(_FakeClient(response=stream_sentinel))
    out = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True
    )
    assert out is stream_sentinel  # untouched
    span = _last().root
    assert span.status == SpanStatus.SUCCESS
    assert span.attributes.get("streaming") is True
    assert span.output is None
    assert span.tokens is None


def test_unknown_model_records_no_cost():
    resp = _Response("hi", "some-local-model", prompt_tokens=5, completion_tokens=5)
    client = agentscope.instrument_openai(_FakeClient(response=resp))
    client.chat.completions.create(model="some-local-model", messages=[{"role": "user", "content": "x"}])
    span = _last().root
    assert span.tokens == {"input": 5, "output": 5, "total": 10}
    assert span.cost is None


def test_instrument_async_client():
    resp = _Response("async hi", "gpt-4o-mini", prompt_tokens=3, completion_tokens=4)

    class _AsyncCompletions:
        async def create(self, **kwargs):
            return resp

    class _AsyncClient:
        def __init__(self):
            self.chat = _Chat(_AsyncCompletions())

    client = agentscope.instrument_openai(_AsyncClient())
    out = asyncio.run(
        client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "x"}])
    )
    assert out is resp
    span = _last().root
    assert span.status == SpanStatus.SUCCESS
    assert span.output == "async hi"
    assert span.tokens == {"input": 3, "output": 4, "total": 7}


def test_non_openai_client_raises_typeerror():
    with pytest.raises(TypeError):
        agentscope.instrument_openai(object())
