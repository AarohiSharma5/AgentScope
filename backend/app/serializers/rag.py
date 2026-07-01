"""Serializers for the RAG / prompt-assembly tracing models (v0.3).

Like :mod:`app.serializers.agent`, these are pure functions (no DB access) that
turn ORM instances into JSON-serializable dictionaries so response shapes stay
consistent across the list, detail, prompt and metrics endpoints.
"""
from typing import Optional

from ..models.agent_trace import RetrieverTrace
from ..models.rag_trace import EmbeddingTrace, PromptAssembly, RetrievedDocument
from .common import iso as _iso


def serialize_embedding(embedding: EmbeddingTrace) -> dict:
    """Serialize the embedding call made for a retrieval."""
    return {
        "id": embedding.id,
        "retriever_trace_id": embedding.retriever_trace_id,
        "embedding_model": embedding.embedding_model,
        "embedding_dimension": embedding.embedding_dimension,
        "input_tokens": embedding.input_tokens,
        "latency_ms": embedding.latency_ms,
        "cost": embedding.cost,
        "metadata": embedding.embedding_metadata,
        "created_at": _iso(embedding.created_at),
    }


def serialize_document(document: RetrievedDocument) -> dict:
    """Serialize a single retrieved document/chunk."""
    return {
        "id": document.id,
        "retriever_trace_id": document.retriever_trace_id,
        "document_id": document.document_id,
        "document_name": document.document_name,
        "document_source": document.document_source,
        "chunk_index": document.chunk_index,
        "chunk_text": document.chunk_text,
        "similarity_score": document.similarity_score,
        "selected": document.selected,
        "metadata": document.doc_metadata,
        "created_at": _iso(document.created_at),
    }


def serialize_prompt_assembly(assembly: PromptAssembly) -> dict:
    """Serialize a prompt assembly into its reconstructed sections + final prompt."""
    return {
        "id": assembly.id,
        "agent_run_id": assembly.agent_run_id,
        "system_prompt": assembly.system_prompt,
        "conversation": assembly.conversation_context,
        "retrieved_context": assembly.retrieved_context,
        "memory_context": assembly.memory_context,
        "user_prompt": assembly.user_prompt,
        "final_prompt": assembly.assembled_prompt,
        "tokens": {
            "system": assembly.system_tokens,
            "conversation": assembly.conversation_tokens,
            "retrieval": assembly.retrieval_tokens,
            "memory": assembly.memory_tokens,
            "user": assembly.user_tokens,
            "total": assembly.total_tokens,
        },
        "created_at": _iso(assembly.created_at),
    }


def _agent_run(retrieval: RetrieverTrace):
    """Return the owning AgentRun for a retrieval, or None (via step)."""
    step = retrieval.step
    return step.agent_run if step else None


def _avg_similarity(documents) -> Optional[float]:
    """Mean similarity across documents that carry a score, or None."""
    scores = [d.similarity_score for d in documents if d.similarity_score is not None]
    return round(sum(scores) / len(scores), 4) if scores else None


def serialize_retrieval_summary(retrieval: RetrieverTrace) -> dict:
    """Lightweight retrieval representation for list endpoints."""
    documents = retrieval.documents
    embedding = retrieval.embedding_trace
    run = _agent_run(retrieval)
    doc_count = retrieval.num_documents if retrieval.num_documents is not None else len(documents)
    return {
        "id": retrieval.id,
        "step_id": retrieval.step_id,
        "agent_run_id": run.id if run else None,
        "query": retrieval.query,
        "num_documents": retrieval.num_documents,
        "selected_count": sum(1 for d in documents if d.selected),
        "avg_similarity": _avg_similarity(documents),
        "embedding_model": embedding.embedding_model if embedding else None,
        "embedding_time_ms": retrieval.embedding_time_ms,
        "retrieval_time_ms": retrieval.retrieval_time_ms,
        # A retrieval "succeeded" if it surfaced at least one document
        # (mirrors the success-rate metric).
        "status": "success" if doc_count and doc_count > 0 else "failed",
    }


def build_retrieval_timeline(retrieval: RetrieverTrace) -> list[dict]:
    """Build an ordered event timeline for a retrieval.

    Order follows the logical RAG flow: embed the query, run the vector search,
    then surface each returned document (by chunk index).
    """
    timeline: list[dict] = []

    embedding = retrieval.embedding_trace
    if embedding is not None:
        timeline.append(
            {
                "type": "embedding",
                "label": embedding.embedding_model or "embedding",
                "latency_ms": embedding.latency_ms,
                "tokens": embedding.input_tokens,
                "cost": embedding.cost,
            }
        )

    timeline.append(
        {
            "type": "search",
            "label": "Vector search",
            "latency_ms": retrieval.retrieval_time_ms,
            "num_documents": retrieval.num_documents,
        }
    )

    for document in retrieval.documents:
        timeline.append(
            {
                "type": "document",
                "label": document.document_name or document.document_id or f"doc {document.id}",
                "chunk_index": document.chunk_index,
                "score": document.similarity_score,
                "selected": document.selected,
            }
        )

    return timeline


def serialize_retrieval_detail(retrieval: RetrieverTrace) -> dict:
    """Full retrieval representation: embedding, docs, scores, selection, prompt, timeline."""
    documents = list(retrieval.documents)
    selected = [d for d in documents if d.selected]
    embedding = retrieval.embedding_trace
    run = _agent_run(retrieval)
    assembly = run.prompt_assembly if run else None

    return {
        "id": retrieval.id,
        "step_id": retrieval.step_id,
        "agent_run_id": run.id if run else None,
        "query": retrieval.query,
        "num_documents": retrieval.num_documents,
        "embedding_time_ms": retrieval.embedding_time_ms,
        "retrieval_time_ms": retrieval.retrieval_time_ms,
        "embedding": serialize_embedding(embedding) if embedding else None,
        "documents": [serialize_document(d) for d in documents],
        "selected_documents": [serialize_document(d) for d in selected],
        "similarity_scores": [
            {
                "document_id": d.document_id,
                "document_name": d.document_name,
                "score": d.similarity_score,
                "selected": d.selected,
            }
            for d in documents
        ],
        "prompt_assembly": serialize_prompt_assembly(assembly) if assembly else None,
        "timeline": build_retrieval_timeline(retrieval),
    }
