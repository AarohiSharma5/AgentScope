"""API tests for the v0.3 RAG / retrieval / prompt endpoints."""
import pytest

from app.extensions import db
from app.retrieval import HashingEmbeddingProvider, InMemoryVectorStore, RetrievalService
from app.services import trace_service
from app.utils.trace_recorder import TraceRecorder


def _seed_retrieval(embedding_model="hash-embed"):
    """Run one traced retrieval + prompt assembly and return relevant ids."""
    provider = HashingEmbeddingProvider(dimension=32, model=embedding_model)
    corpus = ["apple banana fruit", "apple pie recipe", "car engine motor"]
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
    trace = trace_service.create_trace({"user_prompt": "apple", "model_name": "gpt-4o"})
    recorder = TraceRecorder(trace.id)
    svc = RetrievalService(recorder, provider, InMemoryVectorStore(documents))
    result = svc.retrieve("apple", top_k=3, select_top_k=1)
    assembly = svc.assemble_prompt(
        run=result.retriever_trace.step.agent_run,
        documents=result.documents,
        system_prompt="You are a chef.",
        user_prompt="How do I make apple pie?",
    )
    db.session.commit()
    return {
        "retrieval_id": result.retriever_trace.id,
        "prompt_id": assembly.id,
        "embedding_model": embedding_model,
    }


@pytest.fixture()
def seeded(app):
    with app.app_context():
        return _seed_retrieval()


def test_list_retrievals_returns_envelope(client, seeded):
    resp = client.get("/api/retrievals")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body) == {"data", "pagination"}
    assert body["pagination"]["total"] == 1
    row = body["data"][0]
    assert row["id"] == seeded["retrieval_id"]
    assert row["num_documents"] == 3
    assert row["selected_count"] == 1
    assert row["embedding_model"] == seeded["embedding_model"]


def test_list_retrievals_validation(client, seeded):
    assert client.get("/api/retrievals?limit=0").status_code == 400
    assert client.get("/api/retrievals?page=0").status_code == 400
    assert client.get("/api/retrievals?sort=bogus").status_code == 400
    assert client.get("/api/retrievals?min_documents=x").status_code == 400


def test_list_retrievals_search_and_filter(client, seeded):
    assert client.get("/api/retrievals?q=apple").get_json()["pagination"]["total"] == 1
    assert client.get("/api/retrievals?q=zzz").get_json()["pagination"]["total"] == 0
    assert (
        client.get(f"/api/retrievals?embedding_model={seeded['embedding_model']}")
        .get_json()["pagination"]["total"]
        == 1
    )
    assert (
        client.get("/api/retrievals?embedding_model=nope").get_json()["pagination"]["total"] == 0
    )
    assert client.get("/api/retrievals?min_documents=5").get_json()["pagination"]["total"] == 0


def test_get_retrieval_detail(client, seeded):
    resp = client.get(f"/api/retrievals/{seeded['retrieval_id']}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == seeded["retrieval_id"]
    assert body["embedding"]["embedding_model"] == seeded["embedding_model"]
    assert len(body["documents"]) == 3
    assert len(body["selected_documents"]) == 1
    assert len(body["similarity_scores"]) == 3
    assert body["prompt_assembly"]["id"] == seeded["prompt_id"]
    # Timeline: embedding + search + one entry per document.
    types = [e["type"] for e in body["timeline"]]
    assert types[0] == "embedding"
    assert "search" in types
    assert types.count("document") == 3


def test_get_retrieval_404(client, app_ctx):
    assert client.get("/api/retrievals/999999").status_code == 404


def test_get_prompt_reconstruction(client, seeded):
    resp = client.get(f"/api/prompts/{seeded['prompt_id']}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == seeded["prompt_id"]
    assert body["system_prompt"] == "You are a chef."
    assert body["user_prompt"] == "How do I make apple pie?"
    for key in ("conversation", "retrieved_context", "memory_context", "final_prompt"):
        assert key in body
    assert set(body["tokens"]) == {
        "system",
        "conversation",
        "retrieval",
        "memory",
        "user",
        "total",
    }


def test_get_prompt_404(client, app_ctx):
    assert client.get("/api/prompts/999999").status_code == 404


def test_rag_metrics(client, seeded):
    resp = client.get("/api/dashboard/rag-metrics")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_retrievals"] == 1
    assert body["average_documents_retrieved"] == 3
    assert body["average_documents_used"] == 1
    assert body["success_rate"] == 100.0
    for key in (
        "average_similarity",
        "average_embedding_latency",
        "average_retrieval_latency",
        "average_prompt_size",
        "total_embedding_cost",
    ):
        assert key in body


def test_rag_metrics_empty(client, app_ctx):
    body = client.get("/api/dashboard/rag-metrics").get_json()
    assert body["total_retrievals"] == 0
    assert body["success_rate"] == 0


def test_list_retrievals_pagination_and_sort(client, app):
    with app.app_context():
        for _ in range(3):
            _seed_retrieval()

    page1 = client.get("/api/retrievals?limit=2&page=1").get_json()
    assert page1["pagination"]["total"] == 3
    assert page1["pagination"]["pages"] == 2
    assert len(page1["data"]) == 2

    page2 = client.get("/api/retrievals?limit=2&page=2").get_json()
    assert len(page2["data"]) == 1

    # Default sort is -id (newest first).
    ids = [row["id"] for row in client.get("/api/retrievals?limit=10").get_json()["data"]]
    assert ids == sorted(ids, reverse=True)
