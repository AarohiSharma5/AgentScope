"""Vendor-neutral retrieval subsystem (v0.3).

Provides reusable interfaces (:mod:`interfaces`), pluggable embedding providers
(:mod:`embeddings`) and vector-store adapters (:mod:`vector_stores`), plus the
:class:`~app.retrieval.service.RetrievalService` that ties them together and
automatically emits tracing records for every embedding, search, retrieved
document and prompt assembly.

Nothing here imports a vendor SDK at module load: adapters wrap an
already-constructed client, so the package is importable without ``chromadb``,
``faiss``, ``pinecone`` or ``qdrant-client`` installed.
"""
from .interfaces import EmbeddingProvider, EmbeddingResult, SearchHit, VectorStore
from .embeddings import CallableEmbeddingProvider, HashingEmbeddingProvider
from .vector_stores import (
    ChromaVectorStore,
    FaissVectorStore,
    InMemoryVectorStore,
    PineconeVectorStore,
    QdrantVectorStore,
)
from .service import RetrievalResult, RetrievalService

__all__ = [
    "EmbeddingProvider",
    "EmbeddingResult",
    "SearchHit",
    "VectorStore",
    "CallableEmbeddingProvider",
    "HashingEmbeddingProvider",
    "ChromaVectorStore",
    "FaissVectorStore",
    "InMemoryVectorStore",
    "PineconeVectorStore",
    "QdrantVectorStore",
    "RetrievalResult",
    "RetrievalService",
]
