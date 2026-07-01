"""Reusable interfaces for the retrieval subsystem.

These abstractions decouple :class:`~app.retrieval.service.RetrievalService`
from any specific embedding provider or vector database, so new backends can be
added by implementing an adapter rather than changing the service (no vendor
lock-in).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class EmbeddingResult:
    """The outcome of a single embedding call.

    ``dimension`` defaults to ``len(vector)`` when not provided.
    """

    vector: list[float]
    model: Optional[str] = None
    dimension: Optional[int] = None
    input_tokens: Optional[int] = None
    cost: Optional[float] = None

    def __post_init__(self) -> None:
        if self.dimension is None and self.vector is not None:
            self.dimension = len(self.vector)


@dataclass
class SearchHit:
    """A normalized vector-search result, independent of the backend."""

    document_id: Optional[str] = None
    document_name: Optional[str] = None
    document_source: Optional[str] = None
    chunk_index: Optional[int] = None
    chunk_text: Optional[str] = None
    score: Optional[float] = None
    metadata: Optional[dict] = None


class EmbeddingProvider(ABC):
    """Turns text into a vector. Implementations set :attr:`model`."""

    model: Optional[str] = None

    @abstractmethod
    def embed(self, text: str) -> EmbeddingResult:
        """Return the embedding for ``text``."""
        raise NotImplementedError


class VectorStore(ABC):
    """A vector database backend. Implementations set :attr:`source` (vendor tag)."""

    source: Optional[str] = None

    @abstractmethod
    def search(self, vector: list[float], top_k: int = 5, **kwargs) -> list[SearchHit]:
        """Return up to ``top_k`` nearest hits for ``vector``, as :class:`SearchHit`."""
        raise NotImplementedError
