"""Tests for the RetrievalService and vector-store adapters."""
import pytest

from app.models.rag_trace import EmbeddingTrace, PromptAssembly, RetrievedDocument
from app.retrieval import (
    HashingEmbeddingProvider,
    InMemoryVectorStore,
    PineconeVectorStore,
    QdrantVectorStore,
    RetrievalService,
)
from app.utils.trace_recorder import TraceRecorder


@pytest.fixture()
def service(request_trace):
    """A RetrievalService over an offline hashing provider + in-memory store."""
    provider = HashingEmbeddingProvider(dimension=32)
    corpus = [
        "apple banana fruit",
        "car engine motor",
        "apple pie recipe dessert",
        "python programming language",
    ]
    documents = [
        {
            "id": f"d{i}",
            "name": f"Doc {i}",
            "source": "memory",
            "text": text,
            "vector": provider.embed(text).vector,
            "chunk_index": i,
        }
        for i, text in enumerate(corpus)
    ]
    recorder = TraceRecorder(request_trace.id)
    return RetrievalService(recorder, provider, InMemoryVectorStore(documents)), recorder


def test_retrieve_creates_all_tracing_records(service):
    svc, _ = service
    result = svc.retrieve("apple", top_k=3, select_top_k=1)

    rt = result.retriever_trace
    # Documents recorded, split into selected/rejected.
    assert len(result.documents) == 3
    assert len(result.selected) == 1
    assert len(result.rejected) == 2
    assert RetrievedDocument.query.filter_by(retriever_trace_id=rt.id).count() == 3

    # Embedding recorded and measured.
    embedding = EmbeddingTrace.query.filter_by(retriever_trace_id=rt.id).one()
    assert embedding.latency_ms is not None
    assert embedding.input_tokens and embedding.input_tokens > 0
    assert embedding.embedding_dimension == 32

    # Retriever trace enriched with timings + counts.
    assert rt.num_documents == 3
    assert rt.embedding_time_ms is not None
    assert rt.retrieval_time_ms is not None


def test_retrieve_ranks_by_similarity(service):
    svc, _ = service
    result = svc.retrieve("apple", top_k=4, select_top_k=2)
    scores = [d.similarity_score for d in result.documents]
    assert scores == sorted(scores, reverse=True)
    # The apple-related docs should be the selected (top) ones.
    assert all(d.selected for d in result.documents[:2])


def test_reranking_overrides_selection(service):
    svc, _ = service
    result = svc.retrieve("apple", top_k=4, select_top_k=1)
    least_relevant = result.documents[-1].document_id

    def rerank(query, hits):
        # Force the previously-last document to the top.
        return [{"document_id": least_relevant, "score": 99.0}]

    reranked = svc.retrieve("apple", top_k=4, select_top_k=1, rerank=rerank)
    top = reranked.documents[0]
    assert top.document_id == least_relevant
    assert top.selected is True
    assert sum(1 for d in reranked.documents if d.selected) == 1


def test_assemble_prompt_persists_with_selected_context(service):
    svc, recorder = service
    result = svc.retrieve("apple pie", top_k=3, select_top_k=1)
    assembly = svc.assemble_prompt(
        documents=result.documents,
        system_prompt="You are a chef.",
        user_prompt="How do I make apple pie?",
    )

    assert isinstance(assembly, PromptAssembly)
    assert PromptAssembly.query.count() == 1
    selected_text = result.selected[0].chunk_text
    assert selected_text in assembly.retrieved_context
    assert assembly.total_tokens == (
        assembly.system_tokens
        + assembly.retrieval_tokens
        + assembly.user_tokens
        + assembly.conversation_tokens
        + assembly.memory_tokens
    )


# --- Adapter normalization (no vendor SDKs required) -----------------------


def test_pinecone_adapter_normalizes_dict_response():
    class FakeIndex:
        def query(self, vector, top_k, include_metadata):
            return {
                "matches": [
                    {"id": "d1", "score": 0.9, "metadata": {"text": "hello", "name": "Doc 1"}},
                    {"id": "d2", "score": 0.4, "metadata": {"text": "world", "source": "kb"}},
                ]
            }

    hits = PineconeVectorStore(FakeIndex()).search([0.1, 0.2], top_k=2)
    assert [h.document_id for h in hits] == ["d1", "d2"]
    assert hits[0].chunk_text == "hello"
    assert hits[0].score == 0.9
    assert hits[1].document_source == "kb"


def test_qdrant_adapter_normalizes_object_response():
    class Point:
        def __init__(self, id, score, payload):
            self.id = id
            self.score = score
            self.payload = payload

    class FakeClient:
        def search(self, collection_name, query_vector, limit, with_payload):
            return [Point(7, 0.8, {"text": "chunk", "name": "Doc 7"})]

    hits = QdrantVectorStore(FakeClient(), "kb").search([0.1], top_k=1)
    assert hits[0].document_id == "7"
    assert hits[0].score == 0.8
    assert hits[0].chunk_text == "chunk"
    assert hits[0].document_source == "qdrant"
