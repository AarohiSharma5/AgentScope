"""Tests for agentscope.instrument_gemini (auto-instrumentation of Gemini)."""
import asyncio

import pytest

import agentscope
from agentscope import SpanKind, SpanStatus, trace


# --- Minimal fakes shaped like google-generativeai --------------------------


class _Part:
    def __init__(self, text):
        self.text = text


class _Content:
    def __init__(self, text):
        self.parts = [_Part(text)]


class _Candidate:
    def __init__(self, text):
        self.content = _Content(text)


class _UsageMetadata:
    def __init__(self, prompt, candidates):
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates
        self.total_token_count = prompt + candidates


class _Response:
    def __init__(self, text, prompt_tokens, candidate_tokens, model_version="gemini-1.5-pro-002"):
        self.candidates = [_Candidate(text)]
        self.usage_metadata = _UsageMetadata(prompt_tokens, candidate_tokens)
        self.model_version = model_version


class _GenerativeModel:
    """Mirrors genai.GenerativeModel(generate_content / _async)."""

    def __init__(self, model_name, system_instruction=None, response=None, error=None, stream=None):
        self.model_name = model_name
        self._system_instruction = system_instruction
        self._response = response
        self._error = error
        self._stream = stream
        self.calls = []

    def generate_content(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self._error is not None:
            raise self._error
        if kwargs.get("stream"):
            return self._stream
        return self._response

    async def generate_content_async(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self._error is not None:
            raise self._error
        return self._response


def _last():
    traces = trace.finished()
    assert traces, "expected a finished trace"
    return traces[-1]


# --- tests ------------------------------------------------------------------


def test_instrument_records_model_output_tokens_and_cost():
    resp = _Response("Hi there!", prompt_tokens=20, candidate_tokens=8)
    model = agentscope.instrument_gemini(
        _GenerativeModel("models/gemini-1.5-pro", system_instruction="Be nice.", response=resp)
    )

    out = model.generate_content("Say hi")
    assert out is resp

    span = _last().root
    assert span.kind == SpanKind.LLM
    assert span.status == SpanStatus.SUCCESS
    assert span.attributes["model"] == "gemini-1.5-pro"  # "models/" stripped
    assert span.attributes["system_prompt"] == "Be nice."
    assert span.input == "Say hi"
    assert span.output == "Hi there!"
    assert span.tokens == {"input": 20, "output": 8, "total": 28}
    assert span.cost == pytest.approx(20 / 1000 * 0.00125 + 8 / 1000 * 0.005)


def test_contents_list_is_flattened_for_input():
    resp = _Response("ok", 3, 2)
    model = agentscope.instrument_gemini(_GenerativeModel("gemini-1.5-flash", response=resp))
    model.generate_content([{"role": "user", "parts": [{"text": "part-a"}, {"text": "part-b"}]}])
    assert _last().root.input == "part-apart-b"


def test_instrument_records_failure_and_reraises():
    model = agentscope.instrument_gemini(
        _GenerativeModel("gemini-1.5-pro", error=RuntimeError("boom"))
    )
    with pytest.raises(RuntimeError):
        model.generate_content("x")
    span = _last().root
    assert span.status == SpanStatus.FAILED
    assert "RuntimeError" in span.error


def test_unknown_model_records_no_cost():
    resp = _Response("hi", 5, 5, model_version="gemini-experimental-x")
    model = agentscope.instrument_gemini(_GenerativeModel("gemini-experimental-x", response=resp))
    model.generate_content("x")
    span = _last().root
    assert span.tokens == {"input": 5, "output": 5, "total": 10}
    assert span.cost is None


def test_instrument_is_idempotent():
    model = _GenerativeModel("gemini-1.5-pro", response=_Response("ok", 1, 1))
    agentscope.instrument_gemini(model)
    wrapped = model.generate_content
    agentscope.instrument_gemini(model)
    assert model.generate_content is wrapped


def test_streaming_captures_output_and_usage():
    chunks = [
        _Response("Hel", prompt_tokens=10, candidate_tokens=1),
        _Response("lo", prompt_tokens=10, candidate_tokens=3),  # cumulative usage
    ]
    model = agentscope.instrument_gemini(
        _GenerativeModel("gemini-1.5-flash", stream=iter(chunks))
    )
    out = model.generate_content("hi", stream=True)
    assert trace.finished() == []  # not finalised until consumed
    assert list(out) == chunks

    span = _last().root
    assert span.status == SpanStatus.SUCCESS
    assert span.attributes.get("streaming") is True
    assert span.output == "Hello"
    assert span.tokens == {"input": 10, "output": 3, "total": 13}


def test_async_generate_content():
    resp = _Response("async hi", 3, 4, model_version="gemini-1.5-flash-002")
    model = agentscope.instrument_gemini(_GenerativeModel("gemini-1.5-flash", response=resp))
    out = asyncio.run(model.generate_content_async("x"))
    assert out is resp
    span = _last().root
    assert span.output == "async hi"
    assert span.tokens == {"input": 3, "output": 4, "total": 7}


def test_non_gemini_object_raises_typeerror():
    with pytest.raises(TypeError):
        agentscope.instrument_gemini(object())
