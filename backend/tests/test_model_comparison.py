"""Tests for the v0.5 Model Comparison engine and service."""
import pytest

from app.comparison import ComparisonError, ModelComparisonEngine
from app.orchestration import AgentOrchestrator
from app.services import comparison_service, replay_service, trace_service

_QUESTION = "What is the capital of France?"
_ANSWER = "The capital of France is Paris."
_CONTEXT = "Paris is the capital of France."


def _build_conversation() -> int:
    """A base conversation with an answer, context, docs, tools and memory."""
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
        rt = rec.record_retriever(step, query="q", num_documents=2)
        rec.record_retrieved_document(rt, document_id="d1", chunk_text=_CONTEXT,
                                      similarity_score=0.9, selected=True)
        rec.record_retrieved_document(rt, document_id="d2", chunk_text="Berlin.",
                                      similarity_score=0.2, selected=False)
        rec.finish_step(step, output=_ANSWER,
                        token_usage={"input": 100, "output": 50, "total": 150}, cost=0.01)
        return _ANSWER

    agent.execute(work=work)
    orch.finish()
    return orch.conversation.id


@pytest.fixture()
def conversation(app_ctx) -> int:
    return _build_conversation()


_MODELS = ["gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet"]


# -- Profiles ---------------------------------------------------------------


def test_variant_profile_aggregates_dimensions(conversation):
    profile = comparison_service.variant_profile(conversation, model="gpt-4o")
    assert profile["output"] == _ANSWER
    assert profile["tool_calls"] == {"total": 1, "success": 1, "success_rate": 1.0}
    assert profile["memory_usage"]["used_rate"] == 1.0
    assert profile["retriever"]["precision"] == 0.5
    assert profile["retriever"]["avg_similarity"] == pytest.approx(0.55)


# -- Multi-model comparison -------------------------------------------------


def test_compare_runs_every_model(conversation):
    engine = ModelComparisonEngine()
    result = engine.compare(conversation, _MODELS)

    assert [p["model"] for p in result.profiles] == _MODELS
    # Each variant produced its own new conversation.
    conv_ids = {p["conversation_run_id"] for p in result.profiles}
    assert len(conv_ids) == 3 and conversation not in conv_ids
    # gpt-4o-mini is cheapest of the three (re-estimated per model).
    assert result.summary["best_by"]["cost"] == "gpt-4o-mini"


def test_compare_stores_pairwise_records(conversation):
    engine = ModelComparisonEngine()
    result = engine.compare(conversation, _MODELS, baseline_model="gpt-4o")

    # One record per non-baseline model (baseline vs variant).
    assert len(result.comparison_ids) == 2
    for cid in result.comparison_ids:
        rec = replay_service.get_model_comparison(cid)
        assert rec.model_a == "gpt-4o"
        assert rec.model_b in {"gpt-4o-mini", "claude-3-5-sonnet"}
        assert rec.cost_difference is not None


def test_compare_summary_and_side_by_side(conversation):
    engine = ModelComparisonEngine()
    result = engine.compare(conversation, _MODELS)

    assert set(result.summary["ranking"]) == set(_MODELS)
    assert result.summary["overall_winner"] in _MODELS
    sbs = result.side_by_side
    assert sbs["models"] == _MODELS
    metric_names = {row["metric"] for row in sbs["rows"]}
    assert {"output", "latency_ms", "cost", "evaluation_score", "tool_success_rate",
            "memory_used_rate", "retriever_precision"} <= metric_names
    cost_row = next(r for r in sbs["rows"] if r["metric"] == "cost")
    assert set(cost_row["values"]) == set(_MODELS)


def test_compare_with_evaluation(conversation):
    engine = ModelComparisonEngine()
    result = engine.compare(
        conversation, _MODELS, evaluate=True, reference=_ANSWER, cost_budget=1.0
    )
    for profile in result.profiles:
        assert profile["evaluation_score"] is not None
    # Equal scores across models -> winner decided by cost (cheapest).
    assert result.winner == "gpt-4o-mini"


def test_provider_agnostic_unknown_models(conversation):
    """Arbitrary provider names are accepted as opaque strings."""
    engine = ModelComparisonEngine()
    result = engine.compare(conversation, ["GPT-4.1", "Claude 4", "Gemini 2.5"])
    assert [p["model"] for p in result.profiles] == ["GPT-4.1", "Claude 4", "Gemini 2.5"]
    assert len(result.comparison_ids) == 2


def test_compare_requires_models(conversation):
    with pytest.raises(ComparisonError):
        ModelComparisonEngine().compare(conversation, [])


def test_compare_bad_baseline(conversation):
    with pytest.raises(ComparisonError):
        ModelComparisonEngine().compare(conversation, _MODELS, baseline_model="nope")
