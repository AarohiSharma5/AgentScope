"""Tests for the LangChain integration (agentscope.integrations.langchain).

LangChain is an optional dependency; if it isn't installed we register a tiny
fake ``langchain_core.callbacks.base`` so the handler (which only *subclasses*
BaseCallbackHandler) imports. The event payloads below are hand-built to mimic
LangChain's shapes, so no real LangChain is needed to exercise the mapping.
"""
import sys
import types
import uuid

import pytest

try:  # use the real base class if LangChain is installed, else a stand-in
    import langchain_core.callbacks.base  # noqa: F401
except Exception:  # noqa: BLE001
    _base = types.ModuleType("langchain_core.callbacks.base")

    class _BaseCallbackHandler:  # minimal stand-in
        raise_error = False

    _base.BaseCallbackHandler = _BaseCallbackHandler
    sys.modules.setdefault("langchain_core", types.ModuleType("langchain_core"))
    sys.modules.setdefault("langchain_core.callbacks", types.ModuleType("langchain_core.callbacks"))
    sys.modules["langchain_core.callbacks.base"] = _base

import agentscope
from agentscope import SpanKind, SpanStatus, trace
from agentscope.integrations.langchain import AgentScopeCallbackHandler


# --- fakes shaped like LangChain event payloads -----------------------------


class _Message:
    def __init__(self, content, type="ai", usage_metadata=None, response_metadata=None):
        self.content = content
        self.type = type
        self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata or {}


class _Generation:
    def __init__(self, text=None, message=None):
        self.text = text
        self.message = message


class _LLMResult:
    def __init__(self, generations, llm_output=None):
        self.generations = generations
        self.llm_output = llm_output


class _Document:
    def __init__(self, page_content, metadata=None):
        self.page_content = page_content
        self.metadata = metadata or {}


def _uid():
    return uuid.uuid4()


def _emitted():
    traces = trace.finished()
    assert traces, "expected a finished trace"
    return traces[-1]


# --- tests ------------------------------------------------------------------


def test_chain_with_llm_builds_nested_tree_with_tokens_and_cost():
    h = AgentScopeCallbackHandler()
    chain_id, llm_id = _uid(), _uid()

    h.on_chain_start({"name": "AgentExecutor"}, {"input": "hi"}, run_id=chain_id)
    h.on_llm_start({"name": "ChatOpenAI"}, ["hi"], run_id=llm_id, parent_run_id=chain_id)
    h.on_llm_end(
        _LLMResult(
            [[_Generation(text="hello!")]],
            llm_output={"model_name": "gpt-4o", "token_usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        ),
        run_id=llm_id,
    )
    assert trace.finished() == []  # nothing emitted until the root chain ends
    h.on_chain_end({"output": "hello!"}, run_id=chain_id)

    t = _emitted()
    assert t.root.kind == SpanKind.AGENT  # "agent" in the chain name
    assert len(t.spans) == 2
    llm = next(s for s in t.spans if s.kind == SpanKind.LLM)
    assert llm.parent_id == t.root.span_id
    assert llm.trace_id == t.root.trace_id
    assert llm.output == "hello!"
    assert llm.attributes["model"] == "gpt-4o"
    assert llm.tokens == {"input": 10, "output": 5, "total": 15}
    assert llm.cost == pytest.approx(10 / 1000 * 0.0025 + 5 / 1000 * 0.01)


def test_tool_and_retriever_spans_nest_under_chain():
    h = AgentScopeCallbackHandler()
    chain_id, tool_id, ret_id = _uid(), _uid(), _uid()

    h.on_chain_start({"name": "AgentExecutor"}, {"input": "q"}, run_id=chain_id)
    h.on_tool_start({"name": "search"}, "python", run_id=tool_id, parent_run_id=chain_id)
    h.on_tool_end("result-text", run_id=tool_id)
    h.on_retriever_start({"name": "vectorstore"}, "query", run_id=ret_id, parent_run_id=chain_id)
    h.on_retriever_end(
        [_Document("doc-a", {"src": 1}), _Document("doc-b")], run_id=ret_id
    )
    h.on_chain_end({"output": "done"}, run_id=chain_id)

    t = _emitted()
    tool = next(s for s in t.spans if s.kind == SpanKind.TOOL)
    assert tool.input == "python" and tool.output == "result-text"
    assert tool.parent_id == t.root.span_id
    ret = next(s for s in t.spans if s.kind == SpanKind.RETRIEVER)
    assert ret.input == "query"
    assert ret.attributes["num_documents"] == 2
    assert ret.output[0] == {"content": "doc-a", "metadata": {"src": 1}}


def test_chat_model_usage_metadata_fallback():
    h = AgentScopeCallbackHandler()
    chain_id, llm_id = _uid(), _uid()
    h.on_chain_start({"name": "AgentExecutor"}, {}, run_id=chain_id)
    msg = _Message(
        "answer",
        usage_metadata={"input_tokens": 7, "output_tokens": 3},
        response_metadata={"model_name": "claude-3-5-sonnet"},
    )
    h.on_chat_model_start(
        {"name": "ChatAnthropic"},
        [[_Message("hi", type="human")]],
        run_id=llm_id,
        parent_run_id=chain_id,
    )
    h.on_llm_end(_LLMResult([[_Generation(message=msg)]]), run_id=llm_id)
    h.on_chain_end({}, run_id=chain_id)

    llm = next(s for s in _emitted().spans if s.kind == SpanKind.LLM)
    assert llm.input == "human: hi"
    assert llm.output == "answer"
    assert llm.tokens == {"input": 7, "output": 3, "total": 10}
    assert llm.attributes["model"] == "claude-3-5-sonnet"
    assert llm.cost == pytest.approx(7 / 1000 * 0.003 + 3 / 1000 * 0.015)


def test_non_agent_chain_root_is_step():
    h = AgentScopeCallbackHandler()
    cid = _uid()
    h.on_chain_start({"name": "LLMChain"}, {}, run_id=cid)
    h.on_chain_end({}, run_id=cid)
    assert _emitted().root.kind == SpanKind.STEP


def test_llm_error_marks_span_failed():
    h = AgentScopeCallbackHandler()
    chain_id, llm_id = _uid(), _uid()
    h.on_chain_start({"name": "AgentExecutor"}, {}, run_id=chain_id)
    h.on_llm_start({"name": "ChatOpenAI"}, ["hi"], run_id=llm_id, parent_run_id=chain_id)
    h.on_llm_error(ValueError("rate limited"), run_id=llm_id)
    h.on_chain_end({}, run_id=chain_id)

    llm = next(s for s in _emitted().spans if s.kind == SpanKind.LLM)
    assert llm.status == SpanStatus.FAILED
    assert "ValueError" in llm.error


def test_chain_error_marks_root_failed_and_emits():
    h = AgentScopeCallbackHandler()
    cid = _uid()
    h.on_chain_start({"name": "AgentExecutor"}, {}, run_id=cid)
    h.on_chain_error(RuntimeError("boom"), run_id=cid)
    t = _emitted()
    assert t.root.status == SpanStatus.FAILED
    assert "RuntimeError" in t.root.error


def test_unknown_model_records_tokens_but_no_cost():
    h = AgentScopeCallbackHandler()
    chain_id, llm_id = _uid(), _uid()
    h.on_chain_start({"name": "AgentExecutor"}, {}, run_id=chain_id)
    h.on_llm_start({"name": "X"}, ["hi"], run_id=llm_id, parent_run_id=chain_id)
    h.on_llm_end(
        _LLMResult(
            [[_Generation(text="ok")]],
            llm_output={"model_name": "mystery-model", "token_usage": {"prompt_tokens": 4, "completion_tokens": 4}},
        ),
        run_id=llm_id,
    )
    h.on_chain_end({}, run_id=chain_id)
    llm = next(s for s in _emitted().spans if s.kind == SpanKind.LLM)
    assert llm.tokens == {"input": 4, "output": 4, "total": 8}
    assert llm.cost is None


def test_disabled_tracer_emits_nothing():
    agentscope.configure(enabled=False)
    h = AgentScopeCallbackHandler()
    cid = _uid()
    h.on_chain_start({"name": "AgentExecutor"}, {}, run_id=cid)
    h.on_chain_end({}, run_id=cid)
    assert trace.finished() == []


def test_handler_never_raises_on_malformed_payloads():
    h = AgentScopeCallbackHandler()
    cid = _uid()
    # Missing/None serialized and non-iterable documents must not blow up.
    h.on_chain_start(None, None, run_id=cid)
    h.on_retriever_start(None, None, run_id=_uid(), parent_run_id=cid)
    h.on_chain_end(None, run_id=cid)  # should still emit the root
    assert _emitted().root.status == SpanStatus.SUCCESS


def test_end_for_unknown_run_id_is_ignored():
    h = AgentScopeCallbackHandler()
    h.on_chain_end({"x": 1}, run_id=_uid())  # never started
    assert trace.finished() == []
