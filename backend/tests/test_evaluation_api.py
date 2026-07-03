"""API tests for the v0.5 replay, evaluation and comparison endpoints."""
import pytest

from app.orchestration import AgentOrchestrator
from app.services import trace_service

_QUESTION = "What is the capital of France?"
_ANSWER = "The capital of France is Paris."
_CONTEXT = "Paris is the capital of France."


def _build_conversation() -> int:
    trace = trace_service.create_trace(
        {"user_prompt": _QUESTION, "system_prompt": "You are helpful.", "model_name": "gpt-4o"}
    )
    orch = AgentOrchestrator(request_trace_id=trace.id, conversation_name="qa")
    agent = orch.create_agent("Responder", role="responder")

    def work():
        rec, run = orch.recorder, agent.run
        rec.record_prompt_assembly(run, system_prompt="You are helpful.",
                                   user_prompt=_QUESTION, retrieved_context=_CONTEXT)
        step = rec.add_step(run, step_type="llm", name="LLM", input=_QUESTION)
        rec.record_tool(step, tool_name="search", arguments={}, result="ok")
        rec.record_memory(step, memory_type="vector", query="q", used=True)
        rt = rec.record_retriever(step, query="q", num_documents=1)
        rec.record_retrieved_document(rt, document_id="d1", chunk_text=_CONTEXT,
                                      similarity_score=0.9, selected=True)
        rec.finish_step(step, output=_ANSWER,
                        token_usage={"input": 100, "output": 50, "total": 150}, cost=0.01)
        return _ANSWER

    agent.execute(work=work)
    orch.finish()
    return orch.conversation.id


@pytest.fixture()
def conversation(app_ctx) -> int:
    return _build_conversation()


# -- Replays ----------------------------------------------------------------


def test_create_and_get_replay(client, conversation):
    resp = client.post("/api/replays", json={
        "conversation_run_id": conversation, "model": "gpt-4o-mini", "temperature": 0.2,
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["replayed_model"] == "gpt-4o-mini"
    assert body["status"] == "success"
    assert body["replay_conversation_run_id"] != conversation

    got = client.get(f"/api/replays/{body['id']}")
    assert got.status_code == 200
    assert got.get_json()["id"] == body["id"]


def test_list_replays_filter_and_search(client, conversation):
    client.post("/api/replays", json={"conversation_run_id": conversation, "model": "gpt-4o-mini"})
    client.post("/api/replays", json={"conversation_run_id": conversation, "model": "claude-3-5-sonnet"})

    resp = client.get(f"/api/replays?original_conversation_run_id={conversation}")
    assert resp.status_code == 200
    assert resp.get_json()["pagination"]["total"] == 2

    searched = client.get("/api/replays?q=claude")
    assert [r["replayed_model"] for r in searched.get_json()["data"]] == ["claude-3-5-sonnet"]


def test_create_replay_validation(client, conversation):
    assert client.post("/api/replays", json={}).status_code == 400
    assert client.post("/api/replays", json={"conversation_run_id": "x"}).status_code == 400
    assert client.post("/api/replays", json={
        "conversation_run_id": conversation, "temperature": "hot"}).status_code == 400


def test_replay_missing_conversation(client, app_ctx):
    resp = client.post("/api/replays", json={"conversation_run_id": 999999})
    assert resp.status_code == 404


def test_get_replay_404(client, app_ctx):
    assert client.get("/api/replays/123").status_code == 404


# -- Evaluations ------------------------------------------------------------


def test_create_and_get_evaluation(client, conversation):
    resp = client.post("/api/evaluations", json={
        "conversation_run_id": conversation, "reference": _ANSWER, "cost_budget": 1.0,
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["conversation_run_id"] == conversation
    assert body["overall_score"] is not None
    assert len(body["metrics"]) > 0

    got = client.get(f"/api/evaluations/{body['id']}")
    assert got.status_code == 200
    assert got.get_json()["id"] == body["id"]


def test_list_evaluations_filter(client, conversation):
    client.post("/api/evaluations", json={"conversation_run_id": conversation})
    resp = client.get(f"/api/evaluations?conversation_run_id={conversation}")
    assert resp.status_code == 200
    assert resp.get_json()["pagination"]["total"] == 1


def test_create_evaluation_validation(client, conversation):
    assert client.post("/api/evaluations", json={}).status_code == 400
    assert client.post("/api/evaluations", json={
        "conversation_run_id": conversation, "expected_facts": "nope"}).status_code == 400


def test_evaluation_missing_conversation(client, app_ctx):
    assert client.post("/api/evaluations", json={"conversation_run_id": 999999}).status_code == 404


def test_get_evaluation_404(client, app_ctx):
    assert client.get("/api/evaluations/123").status_code == 404


# -- Comparisons ------------------------------------------------------------


def test_create_and_list_comparisons(client, conversation):
    resp = client.post("/api/comparisons", json={
        "conversation_run_id": conversation,
        "models": ["gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet"],
        "evaluate": True, "reference": _ANSWER, "cost_budget": 1.0,
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["summary"]["best_by"]["cost"] == "gpt-4o-mini"
    assert len(body["comparison_ids"]) == 2
    assert body["side_by_side"]["models"] == ["gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet"]

    listed = client.get(f"/api/comparisons?conversation_run_id={conversation}")
    assert listed.status_code == 200
    assert listed.get_json()["pagination"]["total"] == 2


def test_create_comparison_validation(client, conversation):
    assert client.post("/api/comparisons", json={"models": ["gpt-4o"]}).status_code == 400
    assert client.post("/api/comparisons", json={
        "conversation_run_id": conversation, "models": []}).status_code == 400
    assert client.post("/api/comparisons", json={
        "conversation_run_id": conversation, "models": [1, 2]}).status_code == 400


def test_comparison_missing_conversation(client, app_ctx):
    resp = client.post("/api/comparisons", json={
        "conversation_run_id": 999999, "models": ["gpt-4o"]})
    assert resp.status_code == 404


def test_comparison_bad_baseline(client, conversation):
    resp = client.post("/api/comparisons", json={
        "conversation_run_id": conversation, "models": ["gpt-4o"], "baseline_model": "nope"})
    assert resp.status_code == 400


# -- Dashboard --------------------------------------------------------------


def test_evaluation_metrics_dashboard(client, conversation):
    client.post("/api/evaluations", json={
        "conversation_run_id": conversation, "reference": _ANSWER, "cost_budget": 1.0})
    resp = client.get("/api/dashboard/evaluation-metrics")
    assert resp.status_code == 200
    data = resp.get_json()
    for key in (
        "average_evaluation_score", "average_cost", "average_latency",
        "average_correctness", "average_faithfulness", "average_groundedness",
        "average_tool_accuracy", "average_memory_usage", "success_rate",
        "total_evaluations",
    ):
        assert key in data
    assert data["total_evaluations"] == 1
    assert data["success_rate"] == 1.0
    assert data["average_cost"] is not None


def test_evaluation_analytics_dashboard(client, conversation):
    client.post("/api/evaluations", json={
        "conversation_run_id": conversation, "reference": _ANSWER, "cost_budget": 1.0})
    resp = client.get("/api/dashboard/evaluation-analytics")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "daily" in data and "totals" in data
    assert len(data["daily"]) == 1
    day = data["daily"][0]
    for key in ("date", "cost", "tokens", "latency_ms", "evaluation_score", "failure_rate"):
        assert key in day
    assert data["totals"]["failure_rate"] == 0.0


# -- Cross-cutting ----------------------------------------------------------


def test_pagination_validation_is_consistent(client, conversation):
    for path in ("/api/replays", "/api/evaluations", "/api/comparisons"):
        assert client.get(f"{path}?page=0").status_code == 400
        assert client.get(f"{path}?limit=99999").status_code == 400
        assert client.get(f"{path}?page=notint").status_code == 400
        assert client.get(f"{path}?page=1&limit=5").status_code == 200


def test_invalid_sort_rejected(client, app_ctx):
    for path in ("/api/replays", "/api/evaluations", "/api/comparisons"):
        assert client.get(f"{path}?sort=bogus").status_code == 400
