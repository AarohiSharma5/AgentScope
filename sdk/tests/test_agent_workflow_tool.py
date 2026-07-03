import pytest

from agentscope import Agent, SpanKind, Tool, Workflow, trace


def last_trace():
    traces = trace.finished()
    assert traces
    return traces[-1]


# -- Tool -------------------------------------------------------------------


def test_tool_decorator_traces_invocation():
    @Tool(description="adds one")
    def inc(n):
        return n + 1

    assert inc(4) == 5
    tr = last_trace()
    assert tr.root.kind == SpanKind.TOOL
    assert tr.root.name == "inc"
    assert tr.root.output == 5
    assert tr.root.attributes["description"] == "adds one"


def test_tool_wrapper_form():
    add = Tool(lambda a, b: a + b, name="add")
    assert add.invoke(2, 3) == 5
    assert last_trace().root.name == "add"


def test_tool_without_function_raises():
    with pytest.raises(Exception):
        Tool(name="empty").invoke(1)


# -- Agent ------------------------------------------------------------------


def test_agent_decorator_and_nested_tool():
    lookup = Tool(lambda q: [f"doc:{q}"], name="lookup")
    planner = Agent("Planner", role="planner", model="gpt-4o")

    @planner
    def plan(question):
        return lookup(question)

    plan("revenue")
    tr = last_trace()
    root = tr.root
    assert root.kind == SpanKind.AGENT
    assert root.attributes["role"] == "planner"
    tool_spans = [s for s in tr.spans if s.kind == SpanKind.TOOL]
    assert tool_spans and tool_spans[0].parent_id == root.span_id


def test_agent_run_without_handler_raises():
    with pytest.raises(Exception):
        Agent("Empty").run("x")


def test_agent_session_context_manager():
    a = Agent("Manual", role="worker")
    with a.session(input="q") as span:
        span.set_output("answer")
    tr = last_trace()
    assert tr.root.kind == SpanKind.AGENT
    assert tr.root.output == "answer"


# -- Workflow ---------------------------------------------------------------


def test_workflow_sequential_threads_output():
    wf = Workflow("pipeline")
    wf.add(lambda x: x + 1, name="step1").add(lambda x: x * 10, name="step2")
    assert wf.run(1) == 20

    tr = last_trace()
    assert tr.root.kind == SpanKind.WORKFLOW
    names = [s.name for s in tr.spans if s.kind == SpanKind.STEP]
    assert names == ["step1", "step2"]
    # steps nest under the workflow root
    for step in [s for s in tr.spans if s.kind == SpanKind.STEP]:
        assert step.parent_id == tr.root.span_id


def test_workflow_step_decorator():
    wf = Workflow("decorated")

    @wf.step
    def double(x):
        return x * 2

    assert wf.run(3) == 6


def test_workflow_parallel_fan_out():
    wf = Workflow("fanout")
    wf.parallel(
        Tool(lambda x: x + 1, name="a"),
        Tool(lambda x: x + 2, name="b"),
        Tool(lambda x: x + 3, name="c"),
    )
    result = wf.run(10)
    assert sorted(result) == [11, 12, 13]

    tr = last_trace()
    tool_spans = [s for s in tr.spans if s.kind == SpanKind.TOOL]
    assert len(tool_spans) == 3
    # every parallel tool nests under the workflow root
    for span in tool_spans:
        assert span.parent_id == tr.root.span_id
