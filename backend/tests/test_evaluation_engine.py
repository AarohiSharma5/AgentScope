"""Tests for the v0.5 Evaluation Engine, evaluators and service layer."""
import pytest

from app.evaluation import (
    CustomEvaluator,
    EvaluationEngine,
    EvaluationError,
    LLMJudgeEvaluator,
    Metrics,
)
from app.models.agent_trace import AgentStatus
from app.orchestration import AgentOrchestrator
from app.services import evaluation_service, trace_service

_QUESTION = "What is the capital of France?"
_ANSWER = "The capital of France is Paris."
_CONTEXT = "Paris is the capital of France."


def _build_conversation() -> int:
    """Build a conversation with an answer, context, docs, tools and memory."""
    trace = trace_service.create_trace(
        {"user_prompt": _QUESTION, "system_prompt": "You are helpful.", "model_name": "gpt-4o"}
    )
    orch = AgentOrchestrator(request_trace_id=trace.id, conversation_name="qa")
    agent = orch.create_agent("Responder", role="responder")

    def work():
        rec, run = orch.recorder, agent.run
        rec.record_prompt_assembly(
            run, system_prompt="You are helpful.", user_prompt=_QUESTION,
            retrieved_context=_CONTEXT,
        )
        step = rec.add_step(run, step_type="llm", name="LLM", input=_QUESTION)
        rec.record_tool(step, tool_name="search", arguments={}, result="ok")
        rec.record_tool(step, tool_name="calc", arguments={}, result="err",
                        status=AgentStatus.FAILED)
        rec.record_memory(step, memory_type="vector", query="q", used=True)
        rec.record_memory(step, memory_type="vector", query="q2", used=False)
        rt = rec.record_retriever(step, query="q", num_documents=2)
        rec.record_retrieved_document(rt, document_id="d1", chunk_text=_CONTEXT,
                                      similarity_score=0.9, selected=True)
        rec.record_retrieved_document(rt, document_id="d2", chunk_text="Berlin is in Germany.",
                                      similarity_score=0.2, selected=False)
        rec.finish_step(step, output=_ANSWER,
                        token_usage={"input": 50, "output": 10, "total": 60}, cost=0.001)
        return _ANSWER

    agent.execute(work=work)
    orch.finish()
    return orch.conversation.id


@pytest.fixture()
def conversation(app_ctx) -> int:
    return _build_conversation()


# -- Context reconstruction -------------------------------------------------


def test_build_context_flattens_trace(conversation):
    ctx = evaluation_service.build_evaluation_context(conversation)
    assert ctx.user_prompt == _QUESTION
    assert ctx.answer == _ANSWER
    assert ctx.retrieved_context == _CONTEXT
    assert len(ctx.documents) == 2
    assert len(ctx.tools) == 2
    assert len(ctx.memory) == 2
    assert ctx.cost == pytest.approx(0.001)


def test_build_context_missing_is_none(app_ctx):
    assert evaluation_service.build_evaluation_context(999999) is None


# -- Rule-based scoring + persistence ---------------------------------------


def test_rule_based_persists_every_metric(conversation):
    engine = EvaluationEngine()
    result = engine.evaluate(
        conversation,
        reference=_ANSWER,
        expected_facts=["Paris capital France"],
        latency_budget_ms=10000,
        cost_budget=1.0,
    )

    assert result.ok
    stored = evaluation_service.get_evaluation_run(result.evaluation_run_id)
    assert stored is not None
    assert stored.status == AgentStatus.SUCCESS
    assert stored.evaluation_type == "rule_based"
    # All ten built-in metrics are persisted (even not-applicable ones).
    names = {m.metric_name for m in stored.metrics}
    assert names == {
        Metrics.CORRECTNESS, Metrics.GROUNDEDNESS, Metrics.FAITHFULNESS,
        Metrics.CONTEXT_PRECISION, Metrics.CONTEXT_RECALL, Metrics.ANSWER_RELEVANCE,
        Metrics.TOOL_SUCCESS, Metrics.MEMORY_USAGE, Metrics.LATENCY_SCORE,
        Metrics.COST_SCORE,
    }
    assert stored.overall_score is not None


def test_metric_values(conversation):
    engine = EvaluationEngine()
    result = engine.evaluate(
        conversation, reference=_ANSWER, expected_facts=["Paris capital France"],
        latency_budget_ms=10000, cost_budget=1.0,
    )
    assert result.score(Metrics.CONTEXT_PRECISION) == 0.5  # 1 of 2 selected
    assert result.score(Metrics.TOOL_SUCCESS) == 0.5       # 1 of 2 succeeded
    assert result.score(Metrics.MEMORY_USAGE) == 0.5       # 1 of 2 used
    assert result.score(Metrics.GROUNDEDNESS) == 1.0       # answer fully in context
    assert result.score(Metrics.CORRECTNESS) == 1.0        # equals reference
    assert result.score(Metrics.ANSWER_RELEVANCE) == 1.0
    assert result.score(Metrics.CONTEXT_RECALL) == 1.0
    assert result.score(Metrics.COST_SCORE) == pytest.approx(0.999)


def test_correctness_none_without_reference(conversation):
    engine = EvaluationEngine()
    result = engine.evaluate(conversation)
    assert result.score(Metrics.CORRECTNESS) is None
    stored = evaluation_service.get_evaluation_run(result.evaluation_run_id)
    corr = next(m for m in stored.metrics if m.metric_name == Metrics.CORRECTNESS)
    assert corr.metric_value is None
    assert "reference" in (corr.notes or "")


def test_context_recall_partial(conversation):
    engine = EvaluationEngine()
    result = engine.evaluate(
        conversation, expected_facts=["Paris capital France", "Tokyo Japan population"]
    )
    assert result.score(Metrics.CONTEXT_RECALL) == 0.5  # 1 of 2 facts present


# -- LLM-as-a-Judge ---------------------------------------------------------


def test_llm_judge_only(conversation):
    judge = lambda prompt: {"score": 0.8, "notes": "looks good"}  # noqa: E731
    engine = EvaluationEngine(evaluators=[LLMJudgeEvaluator(judge=judge, model="judge-1")])
    result = engine.evaluate(conversation, model_name="judge-1")

    assert result.score("llm_judge") == 0.8
    stored = evaluation_service.get_evaluation_run(result.evaluation_run_id)
    assert stored.evaluation_type == "llm_judge"
    assert stored.model_name == "judge-1"


def test_llm_judge_mixed_with_rule_based(conversation):
    engine = EvaluationEngine(judge=lambda prompt: 0.6, judge_model="judge-x")
    result = engine.evaluate(conversation)
    stored = evaluation_service.get_evaluation_run(result.evaluation_run_id)
    assert stored.evaluation_type == "mixed"
    assert result.score("llm_judge") == 0.6


def test_llm_judge_error_is_captured(conversation):
    def bad_judge(prompt):
        raise RuntimeError("boom")

    engine = EvaluationEngine(evaluators=[LLMJudgeEvaluator(judge=bad_judge)])
    result = engine.evaluate(conversation)
    assert result.score("llm_judge") is None
    stored = evaluation_service.get_evaluation_run(result.evaluation_run_id)
    assert "boom" in (stored.metrics[0].notes or "")


# -- Custom evaluators + weighting ------------------------------------------


def test_custom_evaluator(conversation):
    engine = EvaluationEngine(
        evaluators=[CustomEvaluator("my_metric", lambda ctx: 0.42)]
    )
    result = engine.evaluate(conversation)
    assert result.score("my_metric") == 0.42
    stored = evaluation_service.get_evaluation_run(result.evaluation_run_id)
    assert stored.evaluation_type == "custom"


def test_weighted_overall(conversation):
    engine = EvaluationEngine(
        evaluators=[
            CustomEvaluator("a", lambda ctx: 1.0, weight=3.0),
            CustomEvaluator("b", lambda ctx: 0.0, weight=1.0),
        ]
    )
    result = engine.evaluate(conversation)
    # (1.0*3 + 0.0*1) / 4 = 0.75
    assert result.overall_score == 0.75


def test_weights_override(conversation):
    engine = EvaluationEngine(
        evaluators=[
            CustomEvaluator("a", lambda ctx: 1.0),
            CustomEvaluator("b", lambda ctx: 0.0),
        ]
    )
    result = engine.evaluate(conversation, weights={"a": 3.0, "b": 1.0})
    assert result.overall_score == 0.75


# -- Async execution --------------------------------------------------------


def test_evaluate_async(conversation):
    engine = EvaluationEngine()
    future = engine.evaluate_async(conversation, reference=_ANSWER, cost_budget=1.0)
    result = future.result(timeout=10)

    assert result.ok
    # Persisted by the worker thread; visible from the main thread's session.
    stored = evaluation_service.get_evaluation_run(result.evaluation_run_id)
    assert stored is not None and len(stored.metrics) == 10
    engine.shutdown()


# -- Listing + errors -------------------------------------------------------


def test_list_evaluation_runs(conversation):
    engine = EvaluationEngine()
    engine.evaluate(conversation)
    engine.evaluate(conversation)
    items, total = evaluation_service.list_evaluation_runs(conversation_run_id=conversation)
    assert total == 2 and len(items) == 2


def test_evaluate_nonexistent_raises(app_ctx):
    with pytest.raises(EvaluationError):
        EvaluationEngine().evaluate(999999)
