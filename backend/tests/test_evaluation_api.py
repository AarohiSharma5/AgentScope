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

    # Per-model breakdown groups by the generating model (one conversation here).
    assert "by_model" in data
    assert len(data["by_model"]) == 1
    model_row = data["by_model"][0]
    for key in (
        "model", "evaluations", "failure_rate",
        "average_evaluation_score", "average_cost", "average_latency", "tokens",
    ):
        assert key in model_row
    assert model_row["evaluations"] == 1

    # Latency/cost percentiles (p50/p95/p99) over evaluated conversations.
    assert "percentiles" in data
    for metric in ("latency_ms", "cost"):
        assert set(data["percentiles"][metric]) == {"p50", "p95", "p99"}
    assert data["percentiles"]["cost"]["p50"] == 0.01

    # The generating model is surfaced for the whole-page model filter.
    assert "available_models" in data
    generating_model = model_row["model"]
    assert generating_model in data["available_models"]

    # Filtering to that model keeps the series; filtering to a bogus one empties
    # the time-series/headline while the option list (all models) is unchanged.
    scoped = client.get(
        f"/api/dashboard/evaluation-analytics?model={generating_model}"
    ).get_json()
    assert scoped["model"] == generating_model
    assert len(scoped["daily"]) == 1
    assert scoped["totals"]["total_evaluations"] == 1

    empty = client.get("/api/dashboard/evaluation-analytics?model=nope").get_json()
    assert empty["daily"] == []
    assert empty["totals"]["total_evaluations"] == 0
    assert empty["available_models"] == data["available_models"]


def test_evaluation_analytics_aggregation_and_date_bounds(app_ctx):
    """Daily aggregation is correct and ``days`` bounds the window (H6).

    Verifies the set-based aggregation (no per-run fan-out) reproduces the old
    per-run cost/token/failure bucketing and that the date bound trims old days.
    """
    from datetime import timedelta

    from app.extensions import db
    from app.models.agent_trace import AgentStatus
    from app.services import evaluation_service as es
    from app.utils.timeutils import utcnow

    conv_id = _build_conversation()  # one step: cost 0.01, tokens 150

    # Two evaluations of the SAME conversation, on two different days.
    r_today = es.create_evaluation_run(conv_id, evaluation_type="quality")
    es.finish_evaluation_run(r_today, overall_score=0.8, status=AgentStatus.SUCCESS)

    r_old = es.create_evaluation_run(conv_id, evaluation_type="quality")
    es.finish_evaluation_run(r_old, overall_score=0.6, status=AgentStatus.FAILED)
    r_old.created_at = utcnow() - timedelta(days=10)
    db.session.commit()

    # All history -> two daily buckets, each reflecting the conversation's step
    # cost/tokens (counted per evaluation run, as before).
    everything = es.get_evaluation_analytics(days=None)
    assert len(everything["daily"]) == 2
    for bucket in everything["daily"]:
        assert bucket["cost"] == 0.01
        assert bucket["tokens"] == 150
    oldest = min(everything["daily"], key=lambda b: b["date"])
    assert oldest["failures"] == 1
    assert oldest["failure_rate"] == 1.0

    # Cost is averaged over DISTINCT conversations (both evals share one).
    metrics = es.get_evaluation_metrics()
    assert metrics["total_evaluations"] == 2
    assert metrics["average_cost"] == 0.01

    # Bounded to the last 3 days -> only the recent bucket survives.
    recent = es.get_evaluation_analytics(days=3)
    assert len(recent["daily"]) == 1
    assert recent["daily"][0]["evaluations"] == 1


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
