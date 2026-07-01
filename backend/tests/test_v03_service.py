"""Service-layer unit tests for the v0.3 RAG / prompt-assembly logic.

These exercise ``trace_service`` directly (persistence, token/cost derivation,
reranking, query/eager-loading), complementing the SDK tests in
``test_v03_sdk.py`` and the HTTP tests in ``test_rag_api.py``.
"""
import pytest
from sqlalchemy import event

from app.extensions import db
from app.models.agent_trace import AgentStatus
from app.serializers.rag import serialize_retrieval_summary
from app.services import trace_service
from app.utils.tokens import estimate_tokens


def _seed_retrieval(query="apple pie", docs=2, model="text-embedding-3-small"):
    """Create a full retrieval (run→step→trace + embedding + docs + prompt)."""
    trace = trace_service.create_trace({"user_prompt": query, "model_name": "gpt-4o"})
    run = trace_service.create_agent_run(
        request_id=trace.id, agent_name="Retriever", agent_type="retriever",
        status=AgentStatus.RUNNING,
    )
    step = trace_service.create_agent_step(
        agent_run_id=run.id, step_number=1, step_type="retrieval", name="Search",
    )
    rt = trace_service.create_retriever_trace(step_id=step.id, query=query)
    trace_service.create_embedding_trace(
        rt.id, embedding_model=model, input_text=query, embedding_dimension=8,
    )
    for i in range(docs):
        trace_service.create_retrieved_document(
            rt.id, document_id=f"d{i}", document_name=f"Doc {i}", chunk_index=i,
            chunk_text=f"chunk {i}", similarity_score=0.9 - i * 0.1, selected=(i == 0),
        )
    trace_service.update_retriever_trace(rt.id, num_documents=docs, retrieval_time_ms=12.0)
    trace_service.create_prompt_assembly(
        run.id, system_prompt="sys", user_prompt=query, retrieved_context="ctx",
    )
    return trace, run, step, rt


# --- Embedding cost estimation ---------------------------------------------


def test_estimate_embedding_cost_known_model(app_ctx):
    cost = trace_service.estimate_embedding_cost("text-embedding-3-small", 1000)
    assert cost == pytest.approx(0.00002)


def test_estimate_embedding_cost_unknown_or_missing(app_ctx):
    assert trace_service.estimate_embedding_cost("mystery-model", 1000) is None
    assert trace_service.estimate_embedding_cost(None, 1000) is None
    assert trace_service.estimate_embedding_cost("text-embedding-3-small", None) is None


def test_create_embedding_trace_derives_tokens_and_cost(app_ctx):
    _, _, _, rt = _seed_retrieval()
    et = rt.embedding_trace
    assert et.input_tokens == estimate_tokens("apple pie")
    assert et.cost == trace_service.estimate_embedding_cost(
        "text-embedding-3-small", et.input_tokens
    )


# --- Prompt assembly -------------------------------------------------------


def test_prompt_assembly_default_composition_order(app_ctx):
    trace = trace_service.create_trace({"user_prompt": "u", "model_name": "gpt-4o"})
    run = trace_service.create_agent_run(
        request_id=trace.id, agent_name="A", status=AgentStatus.RUNNING
    )
    pa = trace_service.create_prompt_assembly(
        run.id, system_prompt="SYS", retrieved_context="CTX", user_prompt="USR",
    )
    # Sources joined in canonical order (system, conversation, retrieved, memory, user).
    assert pa.assembled_prompt == "SYS\n\nCTX\n\nUSR"
    assert pa.total_tokens == pa.system_tokens + pa.retrieval_tokens + pa.user_tokens


def test_prompt_assembly_respects_explicit_values(app_ctx):
    trace = trace_service.create_trace({"user_prompt": "u", "model_name": "gpt-4o"})
    run = trace_service.create_agent_run(
        request_id=trace.id, agent_name="A", status=AgentStatus.RUNNING
    )
    pa = trace_service.create_prompt_assembly(
        run.id, system_prompt="SYS", assembled_prompt="CUSTOM", total_tokens=999,
    )
    assert pa.assembled_prompt == "CUSTOM"
    assert pa.total_tokens == 999


# --- Reranking / updates ---------------------------------------------------


def test_apply_reranking_by_chunk_index(app_ctx):
    _, _, _, rt = _seed_retrieval(docs=3)
    ordered = trace_service.apply_reranking(
        rt.id,
        ranking=[
            {"chunk_index": 2, "score": 0.99},
            {"chunk_index": 0, "score": 0.10},
        ],
        top_k=1,
    )
    assert ordered[0].chunk_index == 2
    assert ordered[0].selected is True
    assert sum(1 for d in ordered if d.selected) == 1


def test_update_retriever_trace_missing_returns_none(app_ctx):
    assert trace_service.update_retriever_trace(999999, num_documents=1) is None


def test_update_retrieved_document_missing_returns_none(app_ctx):
    assert trace_service.update_retrieved_document(999999, similarity_score=0.5) is None


# --- Query layer -----------------------------------------------------------


def test_list_retrievals_filters_and_search(app_ctx):
    _seed_retrieval(query="apple pie", model="text-embedding-3-small")
    _seed_retrieval(query="car engine", model="text-embedding-3-large")

    items, total = trace_service.list_retrievals(q="apple")
    assert total == 1 and items[0].query == "apple pie"

    items, total = trace_service.list_retrievals(embedding_model="text-embedding-3-large")
    assert total == 1 and items[0].query == "car engine"

    _, total = trace_service.list_retrievals(min_documents=5)
    assert total == 0


def test_list_retrievals_is_not_n_plus_1(app_ctx):
    # Seed several full retrievals, then assert serializing a page stays at a
    # small, constant number of queries (eager-loaded), not O(n).
    for _ in range(5):
        _seed_retrieval(docs=2)

    counter = {"n": 0}

    def _count(*_args, **_kwargs):
        counter["n"] += 1

    event.listen(db.engine, "after_cursor_execute", _count)
    try:
        items, total = trace_service.list_retrievals(limit=20)
        _ = [serialize_retrieval_summary(r) for r in items]
    finally:
        event.remove(db.engine, "after_cursor_execute", _count)

    assert total == 5
    # 1 count + 1 main + a handful of batched selectin loads. Far below the
    # ~18 an unbatched (N+1) implementation would issue for 5 rows.
    assert counter["n"] <= 8, f"too many queries: {counter['n']}"
