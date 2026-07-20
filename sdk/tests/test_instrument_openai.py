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


class _Delta:
    def __init__(self, content):
        self.content = content


class _StreamChoice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Chunk:
    """A streamed chunk. A trailing usage-only chunk carries empty choices."""

    def __init__(self, content=None, model="gpt-4o", usage=None):
        self.choices = [_StreamChoice(content)] if content is not None else []
        self.model = model
        self.usage = usage


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


def test_streaming_captures_output_and_passes_chunks_through():
    chunks = [_Chunk("Hel"), _Chunk("lo"), _Chunk("!")]
    client = agentscope.instrument_openai(_FakeClient(response=iter(chunks)))

    out = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True
    )
    # Nothing is finalised until the caller consumes the stream.
    assert trace.finished() == []

    received = list(out)
    assert received == chunks  # every chunk passed through untouched

    span = _last().root
    assert span.status == SpanStatus.SUCCESS
    assert span.attributes.get("streaming") is True
    assert span.output == "Hello!"  # reassembled from the deltas
    # No usage on the stream (caller didn't opt in) -> tokens/cost unknown.
    assert span.tokens is None
    assert span.attributes.get("streaming_usage") == "unavailable"


def test_streaming_with_usage_records_tokens_and_cost():
    chunks = [_Chunk("Hi"), _Chunk(None, usage=_Usage(10, 5))]  # trailing usage chunk
    client = agentscope.instrument_openai(_FakeClient(response=iter(chunks)))

    out = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
        stream_options={"include_usage": True},
    )
    list(out)

    span = _last().root
    assert span.output == "Hi"
    assert span.tokens == {"input": 10, "output": 5, "total": 15}
    assert span.cost == pytest.approx(10 / 1000 * 0.0025 + 5 / 1000 * 0.01)


def test_streaming_span_does_not_capture_later_calls_as_children():
    """A still-open stream span must not become the parent of the next call."""

    class _DualCompletions:
        def create(self, **kwargs):
            return iter([_Chunk("a")]) if kwargs.get("stream") else _Response("done", "gpt-4o", 1, 1)

    class _DualClient:
        def __init__(self):
            self.chat = _Chat(_DualCompletions())

    client = agentscope.instrument_openai(_DualClient())

    stream = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "q"}], stream=True
    )
    # Make an independent (non-stream) call while the stream is still open.
    client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "q2"}])

    standalone = _last()
    assert standalone.root.output == "done"
    assert len(standalone.spans) == 1  # its own trace, NOT nested under the stream

    list(stream)  # now finish the stream -> its own separate trace
    streamed = _last()
    assert streamed.root.attributes.get("streaming") is True
    assert streamed.root.output == "a"


def test_streaming_close_finalizes_span():
    client = agentscope.instrument_openai(_FakeClient(response=iter([_Chunk("a"), _Chunk("b")])))
    stream = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True
    )
    it = iter(stream)
    next(it)  # consume one chunk
    stream.close()

    span = _last().root
    assert span.status == SpanStatus.SUCCESS
    assert span.output == "a"


def test_streaming_error_midway_marks_failed():
    class _BoomStream:
        def __init__(self):
            self._i = 0

        def __iter__(self):
            return self

        def __next__(self):
            self._i += 1
            if self._i == 1:
                return _Chunk("part")
            raise RuntimeError("mid-stream boom")

    client = agentscope.instrument_openai(_FakeClient(response=_BoomStream()))
    stream = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True
    )
    with pytest.raises(RuntimeError):
        list(stream)

    span = _last().root
    assert span.status == SpanStatus.FAILED
    assert "RuntimeError" in span.error


def test_async_streaming_captures_output():
    class _AsyncStream:
        def __init__(self, chunks):
            self._it = iter(chunks)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._it)
            except StopIteration:
                raise StopAsyncIteration

    class _AsyncStreamCompletions:
        async def create(self, **kwargs):
            return _AsyncStream([_Chunk("Hel"), _Chunk("lo")])

    class _AsyncClient:
        def __init__(self):
            self.chat = _Chat(_AsyncStreamCompletions())

    client = agentscope.instrument_openai(_AsyncClient())

    async def run():
        stream = await client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True
        )
        return [chunk async for chunk in stream]

    asyncio.run(run())
    span = _last().root
    assert span.status == SpanStatus.SUCCESS
    assert span.output == "Hello"
    assert span.attributes.get("streaming") is True


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
