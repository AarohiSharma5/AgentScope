"""Embedding provider implementations.

* :class:`HashingEmbeddingProvider` is a deterministic, dependency-free provider
  used for local development and tests (no network, no API key).
* :class:`CallableEmbeddingProvider` adapts any user-supplied embedding function
  (OpenAI, Cohere, a local model, ...) to the :class:`EmbeddingProvider`
  interface, avoiding vendor lock-in.
"""
import hashlib
import math
from typing import Any, Callable

from ..utils.tokens import estimate_tokens
from .interfaces import EmbeddingProvider, EmbeddingResult


class HashingEmbeddingProvider(EmbeddingProvider):
    """Deterministic bag-of-tokens hashing embedding (offline-friendly).

    Each token is hashed into a fixed-size vector; the result is L2-normalized so
    cosine similarity is meaningful. Not semantically meaningful like a real
    model, but stable and free — ideal for tests and demos.
    """

    def __init__(self, dimension: int = 64, model: str = "hashing-embedding") -> None:
        self.dimension = dimension
        self.model = model

    def embed(self, text: str) -> EmbeddingResult:
        vector = [0.0] * self.dimension
        for token in (text or "").lower().split():
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        vector = [v / norm for v in vector]
        return EmbeddingResult(
            vector=vector,
            model=self.model,
            dimension=self.dimension,
            input_tokens=estimate_tokens(text),
        )


class CallableEmbeddingProvider(EmbeddingProvider):
    """Adapt an arbitrary embedding callable to :class:`EmbeddingProvider`.

    ``fn(text)`` may return an :class:`EmbeddingResult`, a dict with
    ``vector``/``embedding`` (and optional ``model``/``input_tokens``/``cost``),
    or a raw sequence of floats.
    """

    def __init__(self, fn: Callable[[str], Any], model: str | None = None) -> None:
        self._fn = fn
        self.model = model

    def embed(self, text: str) -> EmbeddingResult:
        out = self._fn(text)
        if isinstance(out, EmbeddingResult):
            return out
        if isinstance(out, dict):
            return EmbeddingResult(
                vector=out.get("vector") or out.get("embedding"),
                model=out.get("model", self.model),
                dimension=out.get("dimension"),
                input_tokens=out.get("input_tokens"),
                cost=out.get("cost"),
            )
        return EmbeddingResult(vector=list(out), model=self.model)
