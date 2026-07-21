"""API tests for budgets / SLOs (cost caps + metric thresholds)."""
import pytest

from app.orchestration import AgentOrchestrator
from app.services import trace_service

_QUESTION = "What is the capital of France?"
_ANSWER = "The capital of France is Paris."


def _build_conversation() -> int:
    trace = trace_service.create_trace(
        {"user_prompt": _QUESTION, "system_prompt": "You are helpful.", "model_name": "gpt-4o"}
    )
    orch = AgentOrchestrator(request_trace_id=trace.id, conversation_name="qa")
    agent = orch.create_agent("Responder", role="responder")

    def work():
        step = orch.recorder.add_step(agent.run, step_type="llm", name="LLM", input=_QUESTION)
        orch.recorder.finish_step(
            step, output=_ANSWER,
            token_usage={"input": 100, "output": 50, "total": 150}, cost=0.01,
        )
        return _ANSWER

    agent.execute(work=work)
    orch.finish()
    return orch.conversation.id


@pytest.fixture()
def conversation(app_ctx) -> int:
    return _build_conversation()


def test_create_list_and_delete_budget(client):
    resp = client.post("/api/budgets", json={
        "name": "Monthly cost cap",
        "metric": "cost",
        "threshold_value": 50,
    })
    assert resp.status_code == 201
    created = resp.get_json()
    assert created["name"] == "Monthly cost cap"
    assert created["metric"] == "cost"
    # comparison defaults to the metric's natural direction (cost = stay under).
    assert created["comparison"] == "lte"
    assert created["window_days"] == 30
    # No spend yet -> actual 0.0, comfortably within the cap.
    assert created["actual"] == 0.0
    assert created["status"] == "ok"
    assert "ratio" in created
    budget_id = created["id"]

    listed = client.get("/api/budgets").get_json()["data"]
    assert any(b["id"] == budget_id for b in listed)

    assert client.delete(f"/api/budgets/{budget_id}").status_code == 204
    assert client.delete(f"/api/budgets/{budget_id}").status_code == 404
    remaining = client.get("/api/budgets").get_json()["data"]
    assert all(b["id"] != budget_id for b in remaining)


def test_quality_slo_defaults_to_gte_and_unknown_without_data(client):
    created = client.post("/api/budgets", json={
        "name": "Quality floor",
        "metric": "avg_score",
        "threshold_value": 0.85,
    }).get_json()
    assert created["comparison"] == "gte"
    # No evaluations -> no score to check yet.
    assert created["actual"] is None
    assert created["status"] == "unknown"


def test_budget_status_reflects_real_data(client, conversation):
    client.post("/api/evaluations", json={
        "conversation_run_id": conversation, "reference": _ANSWER, "cost_budget": 1.0})

    # One conversation spent $0.01. A generous cap is on track...
    ok = client.post("/api/budgets", json={
        "name": "Loose cap", "metric": "cost", "threshold_value": 1.0}).get_json()
    assert ok["actual"] == 0.01
    assert ok["status"] == "ok"

    # ...a tight cap is breached.
    breach = client.post("/api/budgets", json={
        "name": "Tight cap", "metric": "cost", "threshold_value": 0.005}).get_json()
    assert breach["actual"] == 0.01
    assert breach["status"] == "breach"

    # A per-model cap scoped to a model with no data reads as unknown/zero spend.
    other = client.post("/api/budgets", json={
        "name": "Other model", "metric": "cost", "threshold_value": 1.0,
        "model": "does-not-exist"}).get_json()
    assert other["actual"] == 0.0
    assert other["status"] == "ok"


def test_create_budget_validation(client):
    # Missing name.
    assert client.post("/api/budgets", json={
        "metric": "cost", "threshold_value": 5}).status_code == 400
    # Unknown metric.
    assert client.post("/api/budgets", json={
        "name": "x", "metric": "bogus", "threshold_value": 5}).status_code == 400
    # Non-positive threshold.
    assert client.post("/api/budgets", json={
        "name": "x", "metric": "cost", "threshold_value": 0}).status_code == 400
    # Bad window.
    assert client.post("/api/budgets", json={
        "name": "x", "metric": "cost", "threshold_value": 5,
        "window_days": -1}).status_code == 400
