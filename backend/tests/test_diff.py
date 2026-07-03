"""Tests for prompt versioning, prompt diff and trace diff (v0.5)."""
import pytest

from app.models.agent_trace import AgentStatus
from app.orchestration import AgentOrchestrator
from app.services import diff_service, prompt_service, trace_service


# -- Fixtures / builders ----------------------------------------------------


def _run_with_prompt(prompt_text: str):
    """Create an agent run and record a prompt assembly (auto-versioned)."""
    trace = trace_service.create_trace(
        {"user_prompt": "q", "system_prompt": "sys", "model_name": "gpt-4o"}
    )
    run = trace_service.create_agent_run(
        request_id=trace.id, agent_name="A", status=AgentStatus.RUNNING
    )
    trace_service.create_prompt_assembly(run.id, assembled_prompt=prompt_text)
    return run


def _build_conversation(answer: str, cost: float = 0.01, tokens: int = 150) -> int:
    trace = trace_service.create_trace(
        {"user_prompt": "What is the capital of France?", "model_name": "gpt-4o"}
    )
    orch = AgentOrchestrator(request_trace_id=trace.id, conversation_name="qa")
    agent = orch.create_agent("Responder", role="responder")

    def work():
        rec, run = orch.recorder, agent.run
        rec.record_prompt_assembly(run, system_prompt="sys", user_prompt="q")
        step = rec.add_step(run, step_type="llm", name="LLM", input="q")
        rec.record_tool(step, tool_name="search", arguments={}, result="ok")
        rec.record_memory(step, memory_type="vector", query="q", used=True)
        rt = rec.record_retriever(step, query="q", num_documents=1)
        rec.record_retrieved_document(rt, document_id="d1", chunk_text="ctx", selected=True)
        rec.finish_step(step, output=answer,
                        token_usage={"input": 100, "output": tokens - 100, "total": tokens},
                        cost=cost)
        return answer

    agent.execute(work=work)
    orch.finish()
    return orch.conversation.id


# -- Prompt versioning ------------------------------------------------------


def test_prompt_version_auto_captured(app_ctx):
    # Assembling a prompt (once per run, given the 1:1 constraint) captures it.
    run = _run_with_prompt("Hello there world")
    versions, total = prompt_service.list_prompt_versions(agent_run_id=run.id)
    assert total == 1
    assert versions[0].version == "v1"
    assert versions[0].hash is not None
    assert versions[0].prompt_text == "Hello there world"


def test_prompt_version_increments_and_deduplicates(app_ctx):
    run = _run_with_prompt("Hello there world")  # -> v1 (auto)

    # A different prompt on the same run creates v2.
    prompt_service.record_prompt_version(run.id, "Hello brave new world")
    _, total = prompt_service.list_prompt_versions(agent_run_id=run.id)
    assert total == 2

    # Recording the latest prompt again (same hash) does not create a version.
    prompt_service.record_prompt_version(run.id, "Hello brave new world")
    _, total = prompt_service.list_prompt_versions(agent_run_id=run.id)
    assert total == 2


# -- Prompt diff ------------------------------------------------------------


def test_prompt_diff_segments():
    segments = diff_service.diff_segments(
        "the quick brown fox", "the slow brown fox jumps"
    )
    ops = [s["op"] for s in segments]
    assert "equal" in ops
    assert "modified" in ops  # quick -> slow
    assert "added" in ops     # trailing "jumps"


def test_prompt_diff_service(app_ctx):
    a = _run_with_prompt("alpha beta gamma")
    b = _run_with_prompt("alpha delta gamma")
    va = prompt_service.list_prompt_versions(agent_run_id=a.id)[0][0]
    vb = prompt_service.list_prompt_versions(agent_run_id=b.id)[0][0]

    result = diff_service.prompt_diff(va.id, vb.id)
    assert result["identical"] is False
    assert result["stats"]["modified"] >= 1
    assert diff_service.prompt_diff(va.id, 999999) is None


def test_prompt_diff_api(client, app_ctx):
    a = _run_with_prompt("first prompt content")
    b = _run_with_prompt("second prompt content")
    va = prompt_service.list_prompt_versions(agent_run_id=a.id)[0][0]
    vb = prompt_service.list_prompt_versions(agent_run_id=b.id)[0][0]

    resp = client.get(f"/api/prompt-diff?a={va.id}&b={vb.id}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["a"]["id"] == va.id and body["b"]["id"] == vb.id
    assert any(s["op"] != "equal" for s in body["segments"])

    assert client.get("/api/prompt-diff?a=1").status_code == 400  # missing b
    assert client.get(f"/api/prompt-diff?a={va.id}&b=999999").status_code == 404


def test_prompt_versions_api(client, app_ctx):
    run = _run_with_prompt("listed prompt")
    listed = client.get(f"/api/prompt-versions?agent_run_id={run.id}")
    assert listed.status_code == 200
    data = listed.get_json()
    assert data["pagination"]["total"] == 1
    version_id = data["data"][0]["id"]

    assert client.get(f"/api/prompt-versions/{version_id}").status_code == 200
    assert client.get("/api/prompt-versions/999999").status_code == 404
    assert client.get("/api/prompt-versions?sort=bogus").status_code == 400


# -- Trace diff -------------------------------------------------------------


def test_trace_diff_service(app_ctx):
    a = _build_conversation("The capital of France is Paris.", cost=0.01, tokens=150)
    b = _build_conversation("Paris is the capital city.", cost=0.02, tokens=200)

    result = diff_service.trace_diff(a, b)
    assert result is not None
    metrics = {row["metric"]: row for row in result["metrics"]}
    assert metrics["cost"]["a"] == pytest.approx(0.01)
    assert metrics["cost"]["delta"] == pytest.approx(-0.01)
    assert metrics["total_tokens"]["delta"] == -50

    counts = {row["metric"]: row for row in result["counts"]}
    assert counts["tools"]["a"] == 1
    assert counts["memory"]["a"] == 1
    assert counts["retrievers"]["a"] == 1

    # The single responder node differs in output -> has an output diff.
    node = result["nodes"][0]
    assert node["changed"] is True
    assert node["output_diff"] is not None


def test_trace_diff_api(client, app_ctx):
    a = _build_conversation("answer one")
    b = _build_conversation("answer two")
    resp = client.get(f"/api/trace-diff?a={a}&b={b}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["a"]["conversation_run_id"] == a
    assert body["b"]["conversation_run_id"] == b
    assert len(body["nodes"]) == 1

    assert client.get("/api/trace-diff?a=1").status_code == 400  # missing b
    assert client.get("/api/trace-diff?a=1&b=999999").status_code == 404
    assert client.get("/api/trace-diff?a=notint&b=2").status_code == 400
