"""API tests for analytics insights (anomaly/trend findings + AI summary)."""
import pytest

from app.orchestration import AgentOrchestrator
from app.providers import Capability, ChatResult, HealthStatus, LLMProvider, provider_registry
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


class _FakeInsightProvider(LLMProvider):
    """An in-process LLM provider that returns a canned summary (no network)."""

    name = "fake-insights"
    capabilities = {Capability.CHAT}
    requires_api_key = False
    default_model = "fake-1"
    last_messages = None

    def chat(self, messages, *, model=None, **kwargs):
        type(self).last_messages = messages
        return ChatResult(
            text="AI summary: cost per eval is stable; no regressions detected.",
            model=model or self.default_model,
            provider=self.name,
        )

    def stream(self, messages, *, model=None, **kwargs):  # pragma: no cover - unused
        yield from ()

    def health_check(self) -> HealthStatus:
        return HealthStatus(healthy=True, configured=True)


def test_insights_empty_window(client):
    resp = client.get("/api/dashboard/evaluation-insights")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["summary_source"] == "heuristic"
    assert data["digest"]["evaluations"] == 0
    assert isinstance(data["findings"], list)
    assert "No evaluations" in data["summary"]


def test_insights_with_data(client, conversation):
    client.post("/api/evaluations", json={
        "conversation_run_id": conversation, "reference": _ANSWER, "cost_budget": 1.0})

    data = client.get("/api/dashboard/evaluation-insights").get_json()
    assert data["summary_source"] == "heuristic"
    assert data["digest"]["evaluations"] == 1
    assert data["digest"]["total_cost"] == 0.01
    # The heuristic summary is a non-empty narrative referencing the window.
    assert data["summary"]
    # A breached budget shows up as a critical finding.
    client.post("/api/budgets", json={
        "name": "Tight cap", "metric": "cost", "threshold_value": 0.001})
    findings = client.get("/api/dashboard/evaluation-insights").get_json()["findings"]
    assert any(f["severity"] == "crit" and "breached" in f["title"].lower() for f in findings)


def test_insights_ai_summary_uses_provider(client, conversation, monkeypatch):
    client.post("/api/evaluations", json={
        "conversation_run_id": conversation, "reference": _ANSWER, "cost_budget": 1.0})
    provider_registry.register(_FakeInsightProvider)
    monkeypatch.setenv("INSIGHTS_PROVIDER", "fake-insights")
    try:
        data = client.get("/api/dashboard/evaluation-insights?ai=1").get_json()
        assert data["summary_source"] == "ai"
        assert data["summary"].startswith("AI summary:")
        # The provider was handed the structured digest + findings to narrate.
        assert _FakeInsightProvider.last_messages is not None
    finally:
        provider_registry.unregister("fake-insights")


def test_insights_ai_unavailable_falls_back(client, monkeypatch):
    # An unknown provider can't be created -> graceful fallback to heuristic.
    monkeypatch.setenv("INSIGHTS_PROVIDER", "does-not-exist-xyz")
    data = client.get("/api/dashboard/evaluation-insights?ai=1").get_json()
    assert data["summary_source"] == "ai_unavailable"
    assert data["summary"]  # heuristic summary still present
