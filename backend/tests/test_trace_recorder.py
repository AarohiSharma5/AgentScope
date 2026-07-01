"""Unit tests for the TraceRecorder SDK.

These exercise both the low-level lifecycle API (start/finish agent & step,
sub-record helpers, context managers, nesting) and the high-level chatbot-flow
helpers (planner/memory/retriever/tool/llm/verifier/complete).
"""
import pytest

from app.models.agent_trace import AgentStatus
from app.services import trace_service
from app.utils.trace_recorder import TraceRecorder
from app.utils.validation import ValidationError


def test_start_and_finish_agent_records_status_and_latency(request_trace):
    trace = TraceRecorder(request_trace.id)
    run = trace.start_agent("Planner", type="planner")

    assert run.id is not None
    assert run.status == AgentStatus.RUNNING
    assert run.request_id == request_trace.id

    trace.finish_agent(run, status=AgentStatus.SUCCESS)
    assert run.status == AgentStatus.SUCCESS
    assert run.end_time is not None
    assert run.latency_ms is not None and run.latency_ms >= 0


def test_add_step_autonumbers_and_finish_captures_output(request_trace):
    trace = TraceRecorder(request_trace.id)
    run = trace.start_agent("Agent")

    s1 = trace.add_step(run, step_type="reasoning", name="Think")
    s2 = trace.add_step(run, step_type="action", name="Act")
    assert (s1.step_number, s2.step_number) == (1, 2)

    trace.finish_step(s1, output="done", status=AgentStatus.SUCCESS)
    assert s1.output == "done"
    assert s1.status == AgentStatus.SUCCESS
    assert s1.latency_ms is not None


def test_sub_records_attach_to_step(request_trace):
    trace = TraceRecorder(request_trace.id)
    run = trace.start_agent("Agent")
    step = trace.add_step(run, step_type="action")

    trace.record_tool(step, tool_name="search", arguments={"q": "x"}, result="hit")
    trace.record_memory(step, memory_type="vector", query="x", used=True)
    trace.record_retriever(step, query="x", retrieved_documents=[{"t": "a"}, {"t": "b"}])

    assert len(step.tool_executions) == 1
    assert step.tool_executions[0].tool_name == "search"
    assert len(step.memory_accesses) == 1
    assert step.memory_accesses[0].used is True
    # num_documents is derived from the document list.
    assert step.retriever_traces[0].num_documents == 2


def test_nested_runs_link_parent_and_child(request_trace):
    trace = TraceRecorder(request_trace.id)
    parent = trace.start_agent("Planner", type="planner")
    child = trace.start_agent("Worker", type="worker", parent=parent)

    assert child.parent_run_id == parent.id
    # Accept either an AgentRun or a raw id as the parent.
    child2 = trace.start_agent("Worker2", parent=parent.id)
    assert child2.parent_run_id == parent.id


def test_agent_context_manager_marks_failed_on_exception(request_trace):
    trace = TraceRecorder(request_trace.id)

    with pytest.raises(RuntimeError):
        with trace.agent("Planner", type="planner") as run:
            captured = run
            raise RuntimeError("boom")

    assert captured.status == AgentStatus.FAILED
    assert captured.run_metadata and "error" in captured.run_metadata


def test_step_context_manager_marks_failed_on_exception(request_trace):
    trace = TraceRecorder(request_trace.id)
    run = trace.start_agent("Agent")

    with pytest.raises(ValueError):
        with trace.step(run, step_type="action") as step:
            captured = step
            raise ValueError("nope")

    assert captured.status == AgentStatus.FAILED


def test_high_level_flow_builds_full_pipeline(request_trace):
    trace = TraceRecorder(request_trace.id)
    trace.begin(agent_name="Chatbot", agent_type="chatbot")

    trace.planner(input="q", output="plan")
    trace.memory_lookup(query="q", work=lambda: {"retrieved_text": "ctx", "similarity_score": 0.9, "used": True})
    trace.retriever(query="q", work=lambda: {"documents": [{"t": "a"}], "retrieval_time_ms": 5.0})
    trace.tool_call("calculator", arguments={"expr": "1+1"}, work=lambda: {"answer": 2})
    trace.llm_generation(input="q", work=lambda: {"response": "hi", "input_tokens": 3, "output_tokens": 4, "cost": 0.001})
    trace.verifier(input="hi", output="ok")
    run = trace.complete(status=AgentStatus.SUCCESS, final_response="hi",
                         token_usage={"input": 3, "output": 4, "total": 7}, cost=0.001)

    steps = trace_service.get_agent_run(run.id).steps
    assert [s.step_type for s in steps] == ["planner", "memory", "retrieval", "tool", "llm", "verification"]

    # The LLM step carries token usage and cost.
    llm = next(s for s in steps if s.step_type == "llm")
    assert llm.token_usage == {"input": 3, "output": 4, "total": 7}
    assert llm.cost == 0.001


def test_complete_stores_final_response_on_parent_trace(request_trace):
    trace = TraceRecorder(request_trace.id)
    trace.begin()
    trace.llm_generation(work=lambda: {"response": "answer", "input_tokens": 2, "output_tokens": 5, "cost": 0.002})
    trace.complete(final_response="answer", token_usage={"input": 2, "output": 5, "total": 7}, cost=0.002, latency_ms=12.3)

    updated = trace_service.get_trace(request_trace.id)
    assert updated.final_response == "answer"
    assert updated.total_tokens == 7
    assert updated.estimated_cost == 0.002
    assert updated.latency_ms == 12.3
    assert updated.status == "success"


def test_phase_work_exception_marks_step_failed_and_reraises(request_trace):
    trace = TraceRecorder(request_trace.id)
    trace.begin()

    def boom():
        raise RuntimeError("tool exploded")

    with pytest.raises(RuntimeError):
        trace.tool_call("bad_tool", work=boom)

    run = trace.complete(status=AgentStatus.FAILED)
    failed_steps = [s for s in run.steps if s.status == AgentStatus.FAILED]
    assert len(failed_steps) == 1
    assert failed_steps[0].step_type == "tool"


def test_invalid_metadata_raises_validation_error(request_trace):
    trace = TraceRecorder(request_trace.id)
    with pytest.raises(ValidationError):
        trace.start_agent("Agent", metadata=["not", "a", "dict"])
