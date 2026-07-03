import asyncio

import pytest

import agentscope
from agentscope import SpanKind, SpanStatus, trace


def last_trace():
    traces = trace.finished()
    assert traces, "expected at least one finished trace"
    return traces[-1]


def test_decorator_records_success_and_output():
    @trace
    def add(a, b):
        return a + b

    assert add(2, 3) == 5
    tr = last_trace()
    assert tr.root.name == "add"
    assert tr.root.status == SpanStatus.SUCCESS
    assert tr.root.output == 5
    assert tr.root.input == [2, 3]  # positional arguments captured


def test_decorator_records_failure_and_reraises():
    @trace
    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        boom()
    tr = last_trace()
    assert tr.root.status == SpanStatus.FAILED
    assert "ValueError" in tr.root.error


def test_named_decorator_with_attributes():
    @trace("generate", kind="llm", model="gpt-4o")
    def gen(prompt):
        return "hi"

    gen("hello")
    tr = last_trace()
    assert tr.root.name == "generate"
    assert tr.root.kind == SpanKind.LLM
    assert tr.root.attributes["model"] == "gpt-4o"


def test_context_manager_and_nesting():
    with trace("root") as root:
        assert trace.current() is root
        with trace("child", kind="tool") as child:
            child.set_output("done")
            assert child.parent_id == root.span_id
    tr = last_trace()
    assert len(tr.spans) == 2
    kinds = {s.kind for s in tr.spans}
    assert SpanKind.TOOL in kinds


def test_manual_tracing():
    span = trace.start("generation", kind="llm", model="gpt-4o")
    span.set_output("text").set_tokens(input=10, output=5).set_cost(0.001)
    trace.end(span)
    tr = last_trace()
    assert tr.total_tokens() == 15
    assert tr.total_cost() == pytest.approx(0.001)
    assert tr.root.output == "text"


def test_disabled_produces_no_traces():
    agentscope.configure(enabled=False)

    @trace
    def f():
        return 1

    f()
    assert trace.finished() == []


def test_async_decorator():
    @trace
    async def fetch(x):
        await asyncio.sleep(0)
        return x * 2

    assert asyncio.run(fetch(21)) == 42
    tr = last_trace()
    assert tr.root.output == 42
    assert tr.root.status == SpanStatus.SUCCESS
