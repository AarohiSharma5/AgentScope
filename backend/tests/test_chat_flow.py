"""Tests for the instrumented chatbot flow (chat_service)."""
import pytest

from app.services import chat_service, trace_service


def test_run_chat_traces_full_pipeline_and_stores_response(app_ctx):
    result = chat_service.run_chat({"user_prompt": "hi", "model_name": "gpt-4o"})

    run = trace_service.get_agent_run(result["agent_run_id"])
    assert [s.step_type for s in run.steps] == [
        "planner", "memory", "retrieval", "llm", "verification",
    ]

    trace = trace_service.get_trace(result["request_id"])
    assert trace.final_response == result["response"]
    assert trace.status == "success"
    assert trace.total_tokens == result["usage"]["total"]


def test_run_chat_can_skip_optional_phases(app_ctx):
    result = chat_service.run_chat(
        {"user_prompt": "hi", "model_name": "gpt-4o"}, memory=None, retriever=None
    )
    run = trace_service.get_agent_run(result["agent_run_id"])
    assert [s.step_type for s in run.steps] == ["planner", "llm", "verification"]


def test_run_chat_records_tool_calls(app_ctx):
    result = chat_service.run_chat(
        {"user_prompt": "2+2", "model_name": "gpt-4o"},
        memory=None,
        retriever=None,
        tools=[{"name": "calculator", "arguments": {"expr": "2+2"}, "run": lambda: {"answer": 4}}],
    )
    run = trace_service.get_agent_run(result["agent_run_id"])
    tool_step = next(s for s in run.steps if s.step_type == "tool")
    assert tool_step.tool_executions[0].tool_name == "calculator"


def test_run_chat_failure_marks_run_and_trace_failed(app_ctx):
    def boom(payload, context=None):
        raise RuntimeError("model exploded")

    with pytest.raises(RuntimeError):
        chat_service.run_chat({"user_prompt": "hi", "model_name": "gpt-4o"}, model=boom)

    # The most recent run and its parent trace are both marked failed.
    runs, _ = trace_service.list_agent_runs(page=1, limit=1, sort="-created_at")
    run = runs[0]
    assert run.status == "failed"
    assert trace_service.get_trace(run.request_id).status == "failed"
