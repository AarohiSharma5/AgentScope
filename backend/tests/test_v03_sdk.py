"""Unit tests for the v0.3 RAG / prompt-assembly SDK methods."""
import pytest

from app.models.rag_trace import EmbeddingTrace, RetrievedDocument
from app.services import trace_service
from app.utils.tokens import estimate_tokens
from app.utils.trace_recorder import TraceRecorder


@pytest.fixture()
def retriever_trace(request_trace):
    """A run + retriever step + retriever trace to hang v0.3 records on."""
    rec = TraceRecorder(request_trace.id)
    run = rec.begin()
    step = rec.add_step(run, step_type="retrieval", name="Retriever")
    rt = rec.record_retriever(step, query="q", retrieved_documents=[{"t": "a"}])
    return rec, rt


def test_record_embedding_auto_tokens_cost_latency(retriever_trace):
    rec, rt = retriever_trace
    et = rec.record_embedding(
        rt,
        embedding_model="text-embedding-3-small",
        input="some text to embed",
        work=lambda: {"embedding": [0.0] * 1536},
    )
    assert isinstance(et, EmbeddingTrace)
    assert et.embedding_dimension == 1536
    assert et.input_tokens == estimate_tokens("some text to embed")
    assert et.cost == trace_service.estimate_embedding_cost(
        "text-embedding-3-small", et.input_tokens
    )
    assert et.latency_ms is not None and et.latency_ms >= 0


def test_record_embedding_failure_is_recorded_and_reraised(retriever_trace):
    rec, rt = retriever_trace

    def boom():
        raise RuntimeError("embed failed")

    with pytest.raises(RuntimeError):
        rec.record_embedding(rt, embedding_model="text-embedding-3-small", input="x", work=boom)

    # The embedding is still persisted with error metadata.
    et = EmbeddingTrace.query.filter_by(retriever_trace_id=rt.id).one()
    assert et.embedding_metadata and "error" in et.embedding_metadata


def test_record_chunk_autonumbers_index(retriever_trace):
    rec, rt = retriever_trace
    c0 = rec.record_chunk(rt, chunk_text="first", similarity_score=0.9, document_id="d1")
    c1 = rec.record_chunk(rt, chunk_text="second", similarity_score=0.5, document_id="d2")
    assert (c0.chunk_index, c1.chunk_index) == (0, 1)


def test_record_retrieved_document_and_similarity_update(retriever_trace):
    rec, rt = retriever_trace
    doc = rec.record_retrieved_document(rt, document_id="d1", document_name="Doc 1")
    assert doc.selected is False

    updated = rec.record_similarity(doc, similarity_score=0.77, selected=True)
    assert updated.similarity_score == 0.77
    assert updated.selected is True


def test_record_reranking_orders_and_selects_top_k(retriever_trace):
    rec, rt = retriever_trace
    rec.record_chunk(rt, chunk_text="a", document_id="d1", similarity_score=0.2)
    rec.record_chunk(rt, chunk_text="b", document_id="d2", similarity_score=0.1)
    rec.record_chunk(rt, chunk_text="c", document_id="d3", similarity_score=0.3)

    ordered = rec.record_reranking(
        rt,
        ranking=[
            {"document_id": "d1", "score": 0.95},
            {"document_id": "d2", "score": 0.10},
            {"document_id": "d3", "score": 0.50},
        ],
        top_k=2,
    )
    assert [d.document_id for d in ordered] == ["d1", "d3", "d2"]
    assert [d.selected for d in ordered] == [True, True, False]


def test_record_prompt_assembly_auto_token_accounting(retriever_trace):
    rec, rt = retriever_trace
    pa = rec.record_prompt_assembly(
        system_prompt="you are helpful",
        user_prompt="hello there",
        retrieved_context="doc context",
    )
    assert pa.system_tokens == estimate_tokens("you are helpful")
    assert pa.user_tokens == estimate_tokens("hello there")
    assert pa.retrieval_tokens == estimate_tokens("doc context")
    assert pa.total_tokens == pa.system_tokens + pa.user_tokens + pa.retrieval_tokens
    # assembled_prompt defaults to the non-empty sources joined.
    assert "you are helpful" in pa.assembled_prompt and "hello there" in pa.assembled_prompt


def test_prompt_assembly_defaults_to_active_run(request_trace):
    rec = TraceRecorder(request_trace.id)
    run = rec.begin()
    pa = rec.record_prompt_assembly(user_prompt="hi")
    assert pa.agent_run_id == run.id
