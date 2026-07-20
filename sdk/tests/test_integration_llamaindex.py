"""Tests for the LlamaIndex integration (agentscope.integrations.llamaindex).

LlamaIndex is optional; if absent we register a tiny fake
``llama_index.core.callbacks.base_handler`` so the handler (which only
*subclasses* BaseCallbackHandler) imports. Event payloads are hand-built to
mimic LlamaIndex's shapes — no real LlamaIndex needed.
"""
import sys
import types

import pytest

try:  # use the real base class if installed, else a stand-in
    import llama_index.core.callbacks.base_handler  # noqa: F401
except Exception:  # noqa: BLE001
    _base = types.ModuleType("llama_index.core.callbacks.base_handler")

    class _BaseCallbackHandler:
        def __init__(self, event_starts_to_ignore=None, event_ends_to_ignore=None):
            self.event_starts_to_ignore = event_starts_to_ignore or []
            self.event_ends_to_ignore = event_ends_to_ignore or []

    _base.BaseCallbackHandler = _BaseCallbackHandler
    for name in (
        "llama_index",
        "llama_index.core",
        "llama_index.core.callbacks",
    ):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["llama_index.core.callbacks.base_handler"] = _base

import agentscope
from agentscope import SpanKind, SpanStatus, trace
from agentscope.integrations.llamaindex import AgentScopeCallbackHandler


# --- fakes shaped like LlamaIndex payloads ----------------------------------


class _Msg:
    def __init__(self, content, role="user"):
        self.content = content
        self.role = role


class _ChatMessage:
    def __init__(self, content):
        self.content = content


class _ChatResponse:
    def __init__(self, content, raw=None, additional_kwargs=None):
        self.message = _ChatMessage(content)
        self.raw = raw
        self.additional_kwargs = additional_kwargs or {}


class _CompletionResponse:
    def __init__(self, text, raw=None):
        self.text = text
        self.raw = raw


class _Node:
    def __init__(self, text):
        self._text = text

    def get_content(self):
        return self._text


class _NodeWithScore:
    def __init__(self, text, score=None):
        self.node = _Node(text)
        self.score = score


def _emitted():
    traces = trace.finished()
    assert traces, "expected a finished trace"
    return traces[-1]


# --- tests ------------------------------------------------------------------


def test_query_with_retrieve_and_llm_builds_tree():
    h = AgentScopeCallbackHandler()
    h.start_trace("query")
    h.on_event_start("retrieve", {"query_str": "what is x"}, event_id="e1", parent_id="root")
    h.on_event_end(
        "retrieve",
        {"nodes": [_NodeWithScore("doc-a", 0.9), _NodeWithScore("doc-b", 0.5)]},
        event_id="e1",
    )
    h.on_event_start("llm", {"messages": [_Msg("hi")]}, event_id="e2", parent_id="root")
    h.on_event_end(
        "llm",
        {
            "response": _ChatResponse(
                "hello",
                raw={"usage": {"prompt_tokens": 12, "completion_tokens": 4}, "model": "gpt-4o"},
            )
        },
        event_id="e2",
    )
    assert trace.finished() == []  # not emitted until end_trace
    h.end_trace("query")

    t = _emitted()
    assert t.root.kind == SpanKind.STEP  # "query" is not an agent
    assert len(t.spans) == 3
    ret = next(s for s in t.spans if s.kind == SpanKind.RETRIEVER)
    assert ret.input == "what is x"
    assert ret.attributes["num_documents"] == 2
    assert ret.output[0] == {"content": "doc-a", "score": 0.9}
    llm = next(s for s in t.spans if s.kind == SpanKind.LLM)
    assert llm.parent_id == t.root.span_id
    assert llm.input == "user: hi"
    assert llm.output == "hello"
    assert llm.attributes["model"] == "gpt-4o"
    assert llm.tokens == {"input": 12, "output": 4, "total": 16}
    assert llm.cost == pytest.approx(12 / 1000 * 0.0025 + 4 / 1000 * 0.01)


def test_agent_trace_root_is_agent_and_nesting_by_parent_id():
    h = AgentScopeCallbackHandler()
    h.start_trace("agent_step")
    h.on_event_start("query", {"query_str": "q"}, event_id="q1", parent_id="root")
    h.on_event_start("llm", {}, event_id="l1", parent_id="q1")
    h.on_event_end("llm", {"response": _CompletionResponse("done", raw={"model": "x"})}, event_id="l1")
    h.on_event_end("query", {}, event_id="q1")
    h.end_trace("agent_step")

    t = _emitted()
    assert t.root.kind == SpanKind.AGENT
    q = next(s for s in t.spans if s.name == "query")
    llm = next(s for s in t.spans if s.kind == SpanKind.LLM)
    assert q.parent_id == t.root.span_id
    assert llm.parent_id == q.span_id
    assert llm.output == "done"


def test_function_call_maps_to_tool():
    h = AgentScopeCallbackHandler()
    h.start_trace("agent")
    h.on_event_start("function_call", {"tool": "search"}, event_id="f1", parent_id="root")
    h.on_event_end("function_call", {"function_output": "result"}, event_id="f1")
    h.end_trace("agent")

    tool = next(s for s in _emitted().spans if s.kind == SpanKind.TOOL)
    assert tool.input == "search"
    assert tool.output == "result"


def test_exception_payload_marks_failed():
    h = AgentScopeCallbackHandler()
    h.start_trace("query")
    h.on_event_start("llm", {}, event_id="e1", parent_id="root")
    h.on_event_end("llm", {"exception": ValueError("bad")}, event_id="e1")
    h.end_trace("query")

    llm = next(s for s in _emitted().spans if s.kind == SpanKind.LLM)
    assert llm.status == SpanStatus.FAILED
    assert "ValueError" in llm.error


def test_noisy_events_are_ignored():
    h = AgentScopeCallbackHandler()
    h.start_trace("query")
    eid = h.on_event_start("templating", {"template": "..."}, event_id="t1", parent_id="root")
    h.on_event_end("templating", {}, event_id="t1")
    h.end_trace("query")

    assert eid == "t1"  # id still echoed back for LlamaIndex
    t = _emitted()
    assert len(t.spans) == 1  # only the root; templating skipped


def test_unknown_model_records_tokens_but_no_cost():
    h = AgentScopeCallbackHandler()
    h.start_trace("query")
    h.on_event_start("llm", {}, event_id="e1", parent_id="root")
    h.on_event_end(
        "llm",
        {"response": _ChatResponse("ok", raw={"usage": {"prompt_tokens": 3, "completion_tokens": 3}, "model": "mystery"})},
        event_id="e1",
    )
    h.end_trace("query")
    llm = next(s for s in _emitted().spans if s.kind == SpanKind.LLM)
    assert llm.tokens == {"input": 3, "output": 3, "total": 6}
    assert llm.cost is None


def test_events_outside_trace_are_dropped():
    h = AgentScopeCallbackHandler()
    eid = h.on_event_start("llm", {}, event_id="e1")  # no start_trace
    h.on_event_end("llm", {}, event_id="e1")
    assert eid == "e1"
    assert trace.finished() == []


def test_nested_start_trace_emits_once():
    h = AgentScopeCallbackHandler()
    h.start_trace("query")
    h.start_trace("query")  # nested; should not open a second trace
    h.on_event_start("llm", {}, event_id="e1", parent_id="root")
    h.on_event_end("llm", {"response": _CompletionResponse("x")}, event_id="e1")
    h.end_trace("query")  # inner
    assert trace.finished() == []  # outer still open
    h.end_trace("query")  # outer -> emit
    assert len(trace.finished()) == 1


def test_disabled_tracer_emits_nothing():
    agentscope.configure(enabled=False)
    h = AgentScopeCallbackHandler()
    h.start_trace("query")
    h.on_event_start("llm", {}, event_id="e1", parent_id="root")
    h.on_event_end("llm", {"response": _CompletionResponse("x")}, event_id="e1")
    h.end_trace("query")
    assert trace.finished() == []


def test_generated_event_id_when_missing():
    h = AgentScopeCallbackHandler()
    h.start_trace("query")
    eid = h.on_event_start("llm", {}, parent_id="root")  # no event_id given
    assert eid  # a fresh id is returned
    h.on_event_end("llm", {"response": _CompletionResponse("done")}, event_id=eid)
    h.end_trace("query")
    llm = next(s for s in _emitted().spans if s.kind == SpanKind.LLM)
    assert llm.output == "done"
