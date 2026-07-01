"""RetrievalService: a fully traced, vendor-neutral retrieval pipeline.

Given an :class:`~app.retrieval.interfaces.EmbeddingProvider` and a
:class:`~app.retrieval.interfaces.VectorStore`, the service runs the standard
RAG flow and records every operation through the v0.3 tracing SDK:

* embedding generation -> ``EmbeddingTrace`` (measured latency, tokens, cost)
* vector search -> a ``RetrieverTrace`` (measured latency, document count)
* each hit -> a ``RetrievedDocument`` (similarity score, selected/rejected)
* optional reranking -> updates document scores/selection
* prompt assembly -> a ``PromptAssembly`` (persisted, token-accounted)

All persistence lives in the service layer; the service only orchestrates and
delegates to the :class:`~app.utils.trace_recorder.TraceRecorder`.
"""
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Optional

from ..services import trace_service
from ..utils.trace_recorder import TraceRecorder
from .interfaces import EmbeddingProvider, SearchHit, VectorStore

# A reranker takes the query + current hits and returns a ranking list of dicts
# (``{"document_id"|"chunk_index", "score", "selected"?}``) understood by
# ``trace_service.apply_reranking``.
Reranker = Callable[[str, list[SearchHit]], list[dict]]


@dataclass
class RetrievalResult:
    """Outcome of a :meth:`RetrievalService.retrieve` call."""

    query: str
    retriever_trace: Any
    embedding: Any
    documents: list = field(default_factory=list)
    selected: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    vector: Optional[list[float]] = None
    embedding_time_ms: Optional[float] = None
    retrieval_time_ms: Optional[float] = None


class RetrievalService:
    """Orchestrates and traces embedding + vector search + prompt assembly."""

    def __init__(
        self,
        recorder: TraceRecorder,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        embedding_model: Optional[str] = None,
    ) -> None:
        self.recorder = recorder
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.embedding_model = embedding_model or getattr(embedding_provider, "model", None)

    def retrieve(
        self,
        query: str,
        *,
        run: Optional[Any] = None,
        step: Optional[Any] = None,
        top_k: int = 5,
        select_top_k: Optional[int] = None,
        rerank: Optional[Reranker] = None,
        step_name: str = "Vector Search",
    ) -> RetrievalResult:
        """Embed ``query``, search the store, and record every step.

        A retrieval step is created on the active run when ``step`` isn't given.
        The top ``select_top_k`` documents (defaults to ``top_k``) are marked
        ``selected``; the rest are recorded as rejected. When ``rerank`` is
        provided, it is timed and its scores/selection override the initial
        ranking.
        """
        select_top_k = top_k if select_top_k is None else select_top_k

        # 1. Ensure a step to attach the retriever trace to.
        if step is None:
            target_run = run or self.recorder.ensure_run(
                agent_name="Retriever", agent_type="retriever"
            )
            step = self.recorder.add_step(
                target_run, step_type="retrieval", name=step_name, input=query
            )

        # 2. Retriever trace (parent of embedding + documents).
        retriever_trace = self.recorder.record_retriever(step, query=query)

        # 3. Embedding generation (measured; vector captured via closure).
        captured: dict[str, Any] = {}

        def _embed() -> dict:
            result = self.embedding_provider.embed(query)
            captured["result"] = result
            return {
                "embedding": result.vector,
                "embedding_dimension": result.dimension,
                "input_tokens": result.input_tokens,
                "cost": result.cost,
            }

        embedding = self.recorder.record_embedding(
            retriever_trace,
            embedding_model=self.embedding_model,
            input=query,
            work=_embed,
        )
        vector = captured["result"].vector

        # 4. Vector search (measured).
        search_start = perf_counter()
        hits = self.vector_store.search(vector, top_k=top_k)
        retrieval_time_ms = round((perf_counter() - search_start) * 1000, 2)

        # 5. Record each hit as a retrieved document (selected = initial top-k).
        ordered_hits = sorted(
            hits,
            key=lambda h: (h.score if h.score is not None else float("-inf")),
            reverse=True,
        )
        documents = []
        for rank, hit in enumerate(ordered_hits):
            documents.append(
                self.recorder.record_retrieved_document(
                    retriever_trace,
                    document_id=hit.document_id,
                    document_name=hit.document_name,
                    document_source=hit.document_source or self.vector_store.source,
                    chunk_index=hit.chunk_index if hit.chunk_index is not None else rank,
                    chunk_text=hit.chunk_text,
                    similarity_score=hit.score,
                    selected=(rank < select_top_k),
                    metadata=hit.metadata,
                )
            )

        # 6. Optional reranking (timed inside the SDK; overrides selection).
        if rerank is not None:
            documents = self.recorder.record_reranking(
                retriever_trace,
                work=lambda: rerank(query, ordered_hits),
                top_k=select_top_k,
            )

        # 7. Enrich the retriever trace with timings + counts.
        trace_service.update_retriever_trace(
            retriever_trace.id,
            embedding_time_ms=embedding.latency_ms,
            retrieval_time_ms=retrieval_time_ms,
            num_documents=len(documents),
            retrieved_documents=[
                {
                    "document_id": doc.document_id,
                    "score": doc.similarity_score,
                    "selected": doc.selected,
                }
                for doc in documents
            ],
        )

        selected = [doc for doc in documents if doc.selected]
        rejected = [doc for doc in documents if not doc.selected]
        return RetrievalResult(
            query=query,
            retriever_trace=retriever_trace,
            embedding=embedding,
            documents=documents,
            selected=selected,
            rejected=rejected,
            vector=vector,
            embedding_time_ms=embedding.latency_ms,
            retrieval_time_ms=retrieval_time_ms,
        )

    def assemble_prompt(
        self,
        *,
        run: Optional[Any] = None,
        documents: Optional[list] = None,
        system_prompt: Optional[str] = None,
        conversation_context: Optional[str] = None,
        memory_context: Optional[str] = None,
        user_prompt: Optional[str] = None,
        separator: str = "\n\n",
    ) -> Any:
        """Assemble and persist a prompt, building context from selected documents.

        ``retrieved_context`` is composed from the ``selected`` documents' chunk
        text; the resulting ``PromptAssembly`` (with per-source token counts) is
        always persisted.
        """
        retrieved_context = separator.join(
            doc.chunk_text
            for doc in (documents or [])
            if getattr(doc, "selected", False) and doc.chunk_text
        ) or None

        return self.recorder.record_prompt_assembly(
            run=run,
            system_prompt=system_prompt,
            conversation_context=conversation_context,
            retrieved_context=retrieved_context,
            memory_context=memory_context,
            user_prompt=user_prompt,
        )
