"""Vector-store adapters.

Each adapter wraps an already-constructed vendor client/handle and normalizes
its results into :class:`~app.retrieval.interfaces.SearchHit`. Vendor SDKs are
never imported at module load — only lazily inside the methods that need them
(e.g. numpy for FAISS) — so importing this module never requires the SDKs to be
installed.

:class:`InMemoryVectorStore` is a dependency-free reference implementation used
for local development and tests.
"""
import math
from typing import Any

from .interfaces import SearchHit, VectorStore


def _attr(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a dict-like or attribute-style object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class InMemoryVectorStore(VectorStore):
    """Brute-force cosine search over in-memory documents (no dependencies).

    ``documents`` is a list of dicts with at least ``vector`` and optionally
    ``id``, ``name``, ``source``, ``text``, ``chunk_index`` and ``metadata``.
    """

    source = "memory"

    def __init__(self, documents: list[dict]) -> None:
        self._documents = documents

    def search(self, vector: list[float], top_k: int = 5, **kwargs) -> list[SearchHit]:
        scored = [(_cosine(vector, doc["vector"]), doc) for doc in self._documents]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        hits: list[SearchHit] = []
        for rank, (score, doc) in enumerate(scored[:top_k]):
            hits.append(
                SearchHit(
                    document_id=str(doc.get("id", rank)),
                    document_name=doc.get("name"),
                    document_source=doc.get("source", self.source),
                    chunk_index=doc.get("chunk_index", rank),
                    chunk_text=doc.get("text"),
                    score=score,
                    metadata=doc.get("metadata"),
                )
            )
        return hits


class ChromaVectorStore(VectorStore):
    """Adapter for a Chroma ``Collection`` (``collection.query(...)``)."""

    source = "chroma"

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    def search(self, vector: list[float], top_k: int = 5, **kwargs) -> list[SearchHit]:
        result = self._collection.query(
            query_embeddings=[vector],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        def _first(key: str) -> list:
            value = result.get(key) if isinstance(result, dict) else None
            return (value or [[]])[0]

        ids = _first("ids")
        documents = _first("documents")
        metadatas = _first("metadatas")
        distances = _first("distances")

        hits: list[SearchHit] = []
        for i in range(len(documents)):
            meta = metadatas[i] if i < len(metadatas) else {}
            dist = distances[i] if i < len(distances) else None
            hits.append(
                SearchHit(
                    document_id=ids[i] if i < len(ids) else None,
                    document_name=(meta or {}).get("name"),
                    document_source=(meta or {}).get("source", self.source),
                    chunk_index=i,
                    chunk_text=documents[i],
                    # Chroma returns a distance (lower = closer); convert to a
                    # similarity in (0, 1].
                    score=(1.0 / (1.0 + dist)) if dist is not None else None,
                    metadata=meta,
                )
            )
        return hits


class FaissVectorStore(VectorStore):
    """Adapter for a FAISS index plus an aligned ``documents`` list.

    ``documents[i]`` describes the vector at FAISS id ``i`` and may contain
    ``id``/``name``/``source``/``text``/``chunk_index``/``metadata``.
    """

    source = "faiss"

    def __init__(self, index: Any, documents: list[dict]) -> None:
        self._index = index
        self._documents = documents

    def search(self, vector: list[float], top_k: int = 5, **kwargs) -> list[SearchHit]:
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError("FaissVectorStore requires numpy to be installed") from exc

        query = np.array([vector], dtype="float32")
        distances, indices = self._index.search(query, top_k)

        hits: list[SearchHit] = []
        for rank, (idx, dist) in enumerate(zip(indices[0], distances[0])):
            if idx < 0:
                continue
            doc = self._documents[idx] if idx < len(self._documents) else {}
            hits.append(
                SearchHit(
                    document_id=str(doc.get("id", int(idx))),
                    document_name=doc.get("name"),
                    document_source=doc.get("source", self.source),
                    chunk_index=doc.get("chunk_index", rank),
                    chunk_text=doc.get("text"),
                    # FAISS L2 distance -> similarity in (0, 1].
                    score=1.0 / (1.0 + float(dist)),
                    metadata=doc.get("metadata"),
                )
            )
        return hits


class PineconeVectorStore(VectorStore):
    """Adapter for a Pinecone index (``index.query(vector=..., top_k=...)``)."""

    source = "pinecone"

    def __init__(self, index: Any) -> None:
        self._index = index

    def search(self, vector: list[float], top_k: int = 5, **kwargs) -> list[SearchHit]:
        result = self._index.query(vector=vector, top_k=top_k, include_metadata=True)
        matches = _attr(result, "matches", []) or []

        hits: list[SearchHit] = []
        for match in matches:
            meta = _attr(match, "metadata", {}) or {}
            hits.append(
                SearchHit(
                    document_id=_attr(match, "id"),
                    document_name=meta.get("name"),
                    document_source=meta.get("source", self.source),
                    chunk_index=meta.get("chunk_index"),
                    chunk_text=meta.get("text"),
                    score=_attr(match, "score"),
                    metadata=meta,
                )
            )
        return hits


class QdrantVectorStore(VectorStore):
    """Adapter for a Qdrant client (``client.search(collection, query_vector=...)``)."""

    source = "qdrant"

    def __init__(self, client: Any, collection_name: str) -> None:
        self._client = client
        self._collection_name = collection_name

    def search(self, vector: list[float], top_k: int = 5, **kwargs) -> list[SearchHit]:
        results = self._client.search(
            collection_name=self._collection_name,
            query_vector=vector,
            limit=top_k,
            with_payload=True,
        )

        hits: list[SearchHit] = []
        for point in results:
            payload = _attr(point, "payload", {}) or {}
            hits.append(
                SearchHit(
                    document_id=str(_attr(point, "id")),
                    document_name=payload.get("name"),
                    document_source=payload.get("source", self.source),
                    chunk_index=payload.get("chunk_index"),
                    chunk_text=payload.get("text"),
                    score=_attr(point, "score"),
                    metadata=payload,
                )
            )
        return hits
