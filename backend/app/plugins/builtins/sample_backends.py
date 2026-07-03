"""Example plugin contributing RETRIEVER, MEMORY and LLM_PROVIDER extensions.

A single plugin can contribute across multiple capabilities. This one reuses the
platform's existing retrieval interfaces (``EmbeddingProvider``/``VectorStore``)
for the retriever, and provides dependency-free callable adapters for memory and
an LLM provider — proving there are no hardcoded providers.
"""

from ...retrieval.embeddings import HashingEmbeddingProvider
from ...retrieval.vector_stores import InMemoryVectorStore
from ..base import Capability, PluginBase, PluginContext, PluginMetadata


class BufferMemory:
    """A trivial in-process memory backend: last-write-wins keyed lookups."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def write(self, key: str, value: str) -> None:
        self._store[key] = value

    def lookup(self, query: str) -> dict:
        """Return a memory hit shaped like the tracer's memory dicts."""
        text = self._store.get(query)
        return {"retrieved_text": text, "similarity_score": 1.0 if text else 0.0, "used": bool(text)}


def _echo_llm(prompt: str, **_kwargs) -> dict:
    """A deterministic, offline 'LLM' that echoes a canned completion."""
    return {
        "response": f"[echo] {prompt}",
        "input_tokens": len((prompt or "").split()),
        "output_tokens": len((prompt or "").split()) + 1,
        "model_name": "echo-llm",
    }


class SampleBackendsPlugin(PluginBase):
    """Contributes an in-memory retriever, a buffer memory and an echo LLM."""

    metadata = PluginMetadata(
        name="sample-backends",
        version="1.0.0",
        author="AgentScope",
        description="Reference retriever, memory and LLM-provider backends.",
        capabilities=[
            Capability.RETRIEVER,
            Capability.MEMORY,
            Capability.LLM_PROVIDER,
        ],
        tags=["example", "retrieval", "memory", "llm"],
        license="MIT",
    )

    def register(self, context: PluginContext) -> None:
        context.register_retriever(
            "in-memory",
            {
                "embedding_provider": HashingEmbeddingProvider(),
                "vector_store_factory": InMemoryVectorStore,
            },
            description="Hashing embeddings + brute-force in-memory cosine search.",
        )
        context.register_memory(
            "buffer", BufferMemory(), description="Keyed last-write-wins buffer memory."
        )
        context.register_llm_provider(
            "echo-llm", _echo_llm, description="Offline echo LLM for demos/tests."
        )
