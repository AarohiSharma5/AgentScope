"""Reusable tracing SDK for agent executions.

``TraceRecorder`` manages the full lifecycle of an agent execution — runs,
nested runs, steps, tool calls, memory accesses and retriever calls — while
handling timestamps, latency and status automatically.

All persistence is delegated to :mod:`app.services.trace_service`; this class
never touches the SQLAlchemy session directly. It must be used inside a Flask
application context (as routes and services already are).

Example
-------
    trace = TraceRecorder(request_id)

    run = trace.start_agent(name="Planner", type="planner")
    step = trace.add_step(
        run=run,
        step_type="reasoning",
        name="Understand Question",
        input="What is the revenue?",
    )
    trace.record_tool(step, tool_name="search", arguments={"q": "revenue"})
    trace.record_memory(step, memory_type="vector", query="revenue", used=True)
    trace.record_retriever(step, query="revenue", retrieved_documents=[...])
    trace.finish_step(step, output="Found it", status="success")
    trace.finish_agent(run, status="success")

For exception-safe scoping, prefer the context managers::

    with trace.agent(name="Planner", type="planner") as run:
        with trace.step(run, step_type="reasoning", name="Think") as step:
            ...  # a raised exception marks step & run as failed automatically
"""
import json
import logging
from contextlib import contextmanager
from time import perf_counter
from typing import Any, Callable, Optional, Union

from ..models.agent_trace import AgentRun, AgentStep, AgentStatus, RetrieverTrace
from ..models.rag_trace import EmbeddingTrace, PromptAssembly, RetrievedDocument
from ..services import trace_service

logger = logging.getLogger("agentscope")

# A phase's optional unit of work: a zero-arg callable, or a pre-computed value.
Work = Optional[Callable[[], Any]]


class TraceRecorder:
    """Records the lifecycle of an agent execution for a single request."""

    def __init__(self, request_id: int):
        self.request_id = request_id
        # In-memory monotonic start markers keyed by row id, used for accurate
        # latency independent of DB timezone handling.
        self._run_started: dict[int, float] = {}
        self._step_started: dict[int, float] = {}
        # Per-run auto-incrementing step counter.
        self._step_counter: dict[int, int] = {}
        # Per-retriever-trace auto-incrementing chunk counter (v0.3).
        self._chunk_counter: dict[int, int] = {}
        # The run currently driven by the high-level chatbot-flow helpers.
        self._active_run: Optional[AgentRun] = None

    # -- Agent runs ---------------------------------------------------------

    def start_agent(
        self,
        name: str,
        type: Optional[str] = None,  # noqa: A002 - matches public SDK API
        parent: Optional[Union[AgentRun, int]] = None,
        metadata: Optional[dict] = None,
    ) -> AgentRun:
        """Start (and persist) a new agent run, optionally nested under a parent."""
        run = trace_service.create_agent_run(
            request_id=self.request_id,
            agent_name=name,
            agent_type=type,
            parent_run_id=self._as_id(parent),
            status=AgentStatus.RUNNING,
            metadata=metadata,
        )
        self._run_started[run.id] = perf_counter()
        self._step_counter[run.id] = 0
        return run

    def finish_agent(
        self,
        run: AgentRun,
        status: str = AgentStatus.SUCCESS,
        latency_ms: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> AgentRun:
        """Finish an agent run, recording latency and final status.

        Latency is measured from the matching ``start_agent`` call unless an
        explicit ``latency_ms`` is provided (used e.g. for parallel execution,
        where each agent's wall-clock time is measured independently).
        """
        measured = self._elapsed_ms(self._run_started.pop(run.id, None))
        return trace_service.finish_agent_run(
            run,
            status=status,
            latency_ms=latency_ms if latency_ms is not None else measured,
            metadata=metadata,
        )

    # -- Steps --------------------------------------------------------------

    def add_step(
        self,
        run: AgentRun,
        step_type: Optional[str] = None,
        name: Optional[str] = None,
        input: Optional[str] = None,  # noqa: A002 - matches public SDK API
        output: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> AgentStep:
        """Add (and persist) a step to a run, auto-numbering within the run."""
        self._step_counter[run.id] = self._step_counter.get(run.id, 0) + 1
        step = trace_service.create_agent_step(
            agent_run_id=run.id,
            step_number=self._step_counter[run.id],
            step_type=step_type,
            name=name,
            input=input,
            output=output,
            status=AgentStatus.RUNNING,
            metadata=metadata,
        )
        self._step_started[step.id] = perf_counter()
        return step

    def finish_step(
        self,
        step: AgentStep,
        status: str = AgentStatus.SUCCESS,
        output: Optional[str] = None,
        token_usage: Optional[dict] = None,
        cost: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> AgentStep:
        """Finish a step, recording latency, output, tokens, cost and status."""
        return trace_service.finish_agent_step(
            step,
            status=status,
            output=output,
            token_usage=token_usage,
            cost=cost,
            latency_ms=self._elapsed_ms(self._step_started.pop(step.id, None)),
            metadata=metadata,
        )

    # -- Sub-records attached to a step ------------------------------------

    def record_tool(
        self,
        step: AgentStep,
        tool_name: str,
        arguments: Optional[dict] = None,
        result: Optional[str] = None,
        status: str = AgentStatus.SUCCESS,
        latency_ms: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> "ToolExecution":  # noqa: F821 - forward ref for readability
        """Record a tool/function call executed during a step."""
        return trace_service.create_tool_execution(
            step_id=step.id,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            status=status,
            latency_ms=latency_ms,
            error_message=error_message,
        )

    def record_memory(
        self,
        step: AgentStep,
        memory_type: Optional[str] = None,
        query: Optional[str] = None,
        retrieved_text: Optional[str] = None,
        similarity_score: Optional[float] = None,
        used: Optional[bool] = None,
        latency_ms: Optional[float] = None,
    ) -> "MemoryAccess":  # noqa: F821
        """Record a memory read/lookup during a step."""
        return trace_service.create_memory_access(
            step_id=step.id,
            memory_type=memory_type,
            query=query,
            retrieved_text=retrieved_text,
            similarity_score=similarity_score,
            used=used,
            latency_ms=latency_ms,
        )

    def record_retriever(
        self,
        step: AgentStep,
        query: Optional[str] = None,
        retrieved_documents: Optional[list] = None,
        embedding_time_ms: Optional[float] = None,
        retrieval_time_ms: Optional[float] = None,
        num_documents: Optional[int] = None,
    ) -> "RetrieverTrace":  # noqa: F821
        """Record a retrieval (RAG) call during a step."""
        return trace_service.create_retriever_trace(
            step_id=step.id,
            query=query,
            retrieved_documents=retrieved_documents,
            embedding_time_ms=embedding_time_ms,
            retrieval_time_ms=retrieval_time_ms,
            num_documents=num_documents,
        )

    # -- v0.3 RAG / prompt-assembly sub-records ----------------------------
    #
    # These orchestrate only: they time optional ``work`` callables, extract
    # results and delegate all persistence, token counting and cost estimation
    # to the service layer. ``retriever_trace``/``run`` accept an ORM object or
    # a raw id, and ``run`` defaults to the active run for nested use.

    def record_embedding(
        self,
        retriever_trace: Union[RetrieverTrace, int],
        embedding_model: Optional[str] = None,
        input: Optional[str] = None,  # noqa: A002 - text embedded, for token counting
        input_tokens: Optional[int] = None,
        embedding_dimension: Optional[int] = None,
        work: Work = None,
        cost: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> EmbeddingTrace:
        """Record the embedding call backing a retriever trace.

        Latency is measured around ``work`` (the embed call). If ``work`` returns
        the vector (or a dict with ``embedding``/``dimension``/``input_tokens``/
        ``cost``), those values are extracted. Token count and cost are estimated
        by the service when not supplied. On failure the embedding is still
        recorded with error metadata and the exception re-raised.
        """
        rt_id = self._row_id(retriever_trace)
        started = perf_counter()
        result = None
        try:
            if callable(work):
                result = work()
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            trace_service.create_embedding_trace(
                rt_id,
                embedding_model=embedding_model,
                embedding_dimension=embedding_dimension,
                input_tokens=input_tokens,
                input_text=input,
                latency_ms=self._elapsed_ms(started),
                cost=cost,
                metadata=self._error_meta(metadata, exc),
            )
            raise

        latency_ms = self._elapsed_ms(started) if callable(work) else None
        if isinstance(result, dict):
            embedding_dimension = embedding_dimension or result.get("embedding_dimension") or result.get("dimension")
            input_tokens = input_tokens if input_tokens is not None else result.get("input_tokens")
            cost = cost if cost is not None else result.get("cost")
            vector = result.get("embedding") or result.get("vector")
            if vector is not None and embedding_dimension is None:
                embedding_dimension = len(vector)
        elif isinstance(result, (list, tuple)) and embedding_dimension is None:
            embedding_dimension = len(result)

        return trace_service.create_embedding_trace(
            rt_id,
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
            input_tokens=input_tokens,
            input_text=input,
            latency_ms=latency_ms,
            cost=cost,
            metadata=metadata,
        )

    def record_retrieved_document(
        self,
        retriever_trace: Union[RetrieverTrace, int],
        document_id: Optional[str] = None,
        document_name: Optional[str] = None,
        document_source: Optional[str] = None,
        chunk_index: Optional[int] = None,
        chunk_text: Optional[str] = None,
        similarity_score: Optional[float] = None,
        selected: bool = False,
        metadata: Optional[dict] = None,
    ) -> RetrievedDocument:
        """Record a single document/chunk returned by a retriever trace."""
        return trace_service.create_retrieved_document(
            self._row_id(retriever_trace),
            document_id=document_id,
            document_name=document_name,
            document_source=document_source,
            chunk_index=chunk_index,
            chunk_text=chunk_text,
            similarity_score=similarity_score,
            selected=selected,
            metadata=metadata,
        )

    def record_chunk(
        self,
        retriever_trace: Union[RetrieverTrace, int],
        chunk_text: Optional[str] = None,
        chunk_index: Optional[int] = None,
        similarity_score: Optional[float] = None,
        document_id: Optional[str] = None,
        document_name: Optional[str] = None,
        document_source: Optional[str] = None,
        selected: bool = False,
        metadata: Optional[dict] = None,
    ) -> RetrievedDocument:
        """Record a retrieved chunk, auto-numbering ``chunk_index`` per trace."""
        rt_id = self._row_id(retriever_trace)
        if chunk_index is None:
            chunk_index = self._chunk_counter.get(rt_id, 0)
            self._chunk_counter[rt_id] = chunk_index + 1
        return trace_service.create_retrieved_document(
            rt_id,
            document_id=document_id,
            document_name=document_name,
            document_source=document_source,
            chunk_index=chunk_index,
            chunk_text=chunk_text,
            similarity_score=similarity_score,
            selected=selected,
            metadata=metadata,
        )

    def record_similarity(
        self,
        document: Union[RetrievedDocument, int],
        similarity_score: float,
        selected: Optional[bool] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[RetrievedDocument]:
        """Attach/update a similarity score (and selection) on a retrieved document."""
        return trace_service.update_retrieved_document(
            self._row_id(document),
            similarity_score=similarity_score,
            selected=selected,
            metadata=metadata,
        )

    def record_reranking(
        self,
        retriever_trace: Union[RetrieverTrace, int],
        ranking: Optional[list] = None,
        work: Work = None,
        top_k: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> list:
        """Record a reranking pass over a retriever trace's documents.

        ``work`` (the reranker) is timed automatically and may return the
        ``ranking`` list itself. Each ranking entry identifies a document (by
        ``document_id`` or ``chunk_index``) with a new ``score``/``selected``;
        ``top_k`` marks the top-scoring documents as selected. Returns the
        documents in reranked order.
        """
        rt_id = self._row_id(retriever_trace)
        started = perf_counter()
        try:
            if callable(work):
                ranking = work()
        except Exception:  # noqa: BLE001 - nothing persisted yet; propagate
            raise
        documents = trace_service.apply_reranking(rt_id, ranking=ranking, top_k=top_k)
        logger.debug(
            "Reranked %s documents for trace_id=%s in %.2f ms",
            len(documents), rt_id, self._elapsed_ms(started) or 0.0,
        )
        return documents

    def record_prompt_assembly(
        self,
        run: Optional[Union[AgentRun, int]] = None,
        system_prompt: Optional[str] = None,
        conversation_context: Optional[str] = None,
        retrieved_context: Optional[str] = None,
        memory_context: Optional[str] = None,
        user_prompt: Optional[str] = None,
        assembled_prompt: Optional[str] = None,
        system_tokens: Optional[int] = None,
        conversation_tokens: Optional[int] = None,
        retrieval_tokens: Optional[int] = None,
        memory_tokens: Optional[int] = None,
        user_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
    ) -> PromptAssembly:
        """Record how an agent run assembled its final prompt.

        Defaults ``run`` to the active run, and lets the service derive per-source
        token counts, the total and the assembled prompt when not provided.
        """
        run_id = self._row_id(run) if run is not None else self._require_run().id
        return trace_service.create_prompt_assembly(
            run_id,
            system_prompt=system_prompt,
            conversation_context=conversation_context,
            retrieved_context=retrieved_context,
            memory_context=memory_context,
            user_prompt=user_prompt,
            assembled_prompt=assembled_prompt,
            system_tokens=system_tokens,
            conversation_tokens=conversation_tokens,
            retrieval_tokens=retrieval_tokens,
            memory_tokens=memory_tokens,
            user_tokens=user_tokens,
            total_tokens=total_tokens,
        )

    # -- Exception-safe context managers -----------------------------------

    @contextmanager
    def agent(
        self,
        name: str,
        type: Optional[str] = None,  # noqa: A002 - matches public SDK API
        parent: Optional[Union[AgentRun, int]] = None,
        metadata: Optional[dict] = None,
    ):
        """Scope an agent run; marks it failed and re-raises on exception."""
        run = self.start_agent(name, type=type, parent=parent, metadata=metadata)
        try:
            yield run
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            self.finish_agent(run, status=AgentStatus.FAILED, metadata=self._error_meta(metadata, exc))
            raise
        else:
            self.finish_agent(run, status=AgentStatus.SUCCESS)

 

    # -- High-level chatbot-flow helpers ------------------------------------
    #
    # These build on the low-level API above so an integration only needs a
    # ``TraceRecorder(request_id)`` plus one-line phase calls. Run/step
    # lifecycle, timing, status and persistence are handled automatically.
    # Each phase optionally accepts a ``work`` callable; if the work raises,
    # the step is marked failed and the exception re-raised.

    def begin(
        self,
        agent_name: str = "Chatbot",
        agent_type: str = "chatbot",
        metadata: Optional[dict] = None,
    ) -> AgentRun:
        """Start the top-level agent run for a request and make it active."""
        self._active_run = self.start_agent(agent_name, type=agent_type, metadata=metadata)
        logger.info("Chatbot flow started: run=%s request_id=%s", self._active_run.id, self.request_id)
        return self._active_run

    def planner(
        self,
        input: Optional[str] = None,  # noqa: A002 - matches public SDK API
        work: Work = None,
        output: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Any:
        """Trace a planning step."""
        return self._phase("planner", "Planner", input=input, work=work, output=output, metadata=metadata)

    def memory_lookup(
        self,
        query: Optional[str] = None,
        work: Work = None,
        memory_type: str = "vector",
        retrieved_text: Optional[str] = None,
        similarity_score: Optional[float] = None,
        used: Optional[bool] = None,
        metadata: Optional[dict] = None,
    ) -> Any:
        """Trace an (optional) memory lookup, recording a MemoryAccess."""

        def record(step: AgentStep, result: Any) -> None:
            text, score, was_used = retrieved_text, similarity_score, used
            if isinstance(result, dict):
                text = result.get("retrieved_text", text)
                score = result.get("similarity_score", score)
                was_used = result.get("used", was_used)
            elif isinstance(result, str) and text is None:
                text = result
            self.record_memory(
                step,
                memory_type=memory_type,
                query=query,
                retrieved_text=text,
                similarity_score=score,
                used=was_used,
            )

        return self._phase("memory", "Memory Lookup", input=query, work=work, metadata=metadata, record=record)

    def retriever(
        self,
        query: Optional[str] = None,
        work: Work = None,
        documents: Optional[list] = None,
        embedding_time_ms: Optional[float] = None,
        retrieval_time_ms: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> Any:
        """Trace an (optional) retrieval, recording a RetrieverTrace."""

        def record(step: AgentStep, result: Any) -> None:
            docs, emb, ret = documents, embedding_time_ms, retrieval_time_ms
            if isinstance(result, dict):
                docs = result.get("documents", docs)
                emb = result.get("embedding_time_ms", emb)
                ret = result.get("retrieval_time_ms", ret)
            elif isinstance(result, list) and docs is None:
                docs = result
            self.record_retriever(
                step,
                query=query,
                retrieved_documents=docs,
                embedding_time_ms=emb,
                retrieval_time_ms=ret,
            )

        return self._phase("retrieval", "Retriever", input=query, work=work, metadata=metadata, record=record)

    def tool_call(
        self,
        tool_name: str,
        arguments: Optional[dict] = None,
        work: Work = None,
        result: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Any:
        """Trace an (optional) tool call, recording a ToolExecution."""

        def record(step: AgentStep, work_result: Any) -> None:
            value = result if result is not None else work_result
            self.record_tool(
                step,
                tool_name=tool_name,
                arguments=arguments,
                result=self._stringify(value),
                status=AgentStatus.SUCCESS,
            )

        return self._phase(
            "tool",
            f"Tool: {tool_name}",
            input=self._stringify(arguments),
            work=work,
            metadata=metadata,
            record=record,
        )

    def llm_generation(
        self,
        input: Optional[str] = None,  # noqa: A002 - matches public SDK API
        work: Work = None,
        output: Optional[str] = None,
        token_usage: Optional[dict] = None,
        cost: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> Any:
        """Trace the main LLM generation step, capturing tokens and cost.

        If ``work`` returns a dict, ``response``/``text``/``output``,
        ``token_usage`` (or ``input_tokens``/``output_tokens``) and ``cost`` are
        read from it automatically.
        """
        run = self._require_run()
        step = self.add_step(run, step_type="llm", name="LLM Generation", input=input, metadata=metadata)
        try:
            result = work() if callable(work) else work
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            self.finish_step(step, status=AgentStatus.FAILED, metadata=self._error_meta(metadata, exc))
            raise

        resolved_output, resolved_tokens, resolved_cost = output, token_usage, cost
        if isinstance(result, dict):
            resolved_output = resolved_output or result.get("response") or result.get("text") or result.get("output")
            resolved_tokens = resolved_tokens or result.get("token_usage")
            if resolved_tokens is None and ("input_tokens" in result or "output_tokens" in result):
                it, ot = result.get("input_tokens"), result.get("output_tokens")
                resolved_tokens = {"input": it, "output": ot, "total": (it or 0) + (ot or 0)}
            resolved_cost = resolved_cost if resolved_cost is not None else result.get("cost")
        elif isinstance(result, str) and resolved_output is None:
            resolved_output = result

        self.finish_step(step, output=resolved_output, token_usage=resolved_tokens, cost=resolved_cost)
        return result

    def verifier(
        self,
        input: Optional[str] = None,  # noqa: A002 - matches public SDK API
        work: Work = None,
        output: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Any:
        """Trace a verification step."""
        return self._phase(
            "verification", "Verifier", input=input, work=work, output=output, metadata=metadata
        )

    def complete(
        self,
        status: str = AgentStatus.SUCCESS,
        final_response: Optional[str] = None,
        token_usage: Optional[dict] = None,
        cost: Optional[float] = None,
        latency_ms: Optional[float] = None,
        metadata: Optional[dict] = None,
        update_request: bool = True,
    ) -> AgentRun:
        """Finish the active run and (optionally) store the final response on the
        parent request Trace, keeping the v0.1 fields populated."""
        run = self._require_run()
        self.finish_agent(run, status=status, metadata=metadata)

        if update_request:
            fields: dict = {
                "status": "success" if status == AgentStatus.SUCCESS else "failed",
            }
            if final_response is not None:
                fields["final_response"] = final_response
            if cost is not None:
                fields["estimated_cost"] = cost
            if latency_ms is not None:
                fields["latency_ms"] = latency_ms
            if isinstance(token_usage, dict):
                if token_usage.get("input") is not None:
                    fields["input_tokens"] = token_usage["input"]
                if token_usage.get("output") is not None:
                    fields["output_tokens"] = token_usage["output"]
                if token_usage.get("total") is not None:
                    fields["total_tokens"] = token_usage["total"]
            trace_service.update_trace(self.request_id, **fields)

        logger.info("Chatbot flow finished: run=%s status=%s", run.id, status)
        self._active_run = None
        return run

    # -- Internal helpers ---------------------------------------------------

    def ensure_run(
        self,
        agent_name: str = "Chatbot",
        agent_type: str = "chatbot",
        metadata: Optional[dict] = None,
    ) -> AgentRun:
        """Return the active run, starting one with the given identity if needed.

        Public helper for subsystems (e.g. the retrieval service) that need a run
        to attach steps to without caring whether one already exists.
        """
        if self._active_run is None:
            self.begin(agent_name=agent_name, agent_type=agent_type, metadata=metadata)
        return self._active_run

    def _require_run(self) -> AgentRun:
        """Return the active run, auto-starting one if the caller skipped begin()."""
        if self._active_run is None:
            self.begin()
        return self._active_run

    def _phase(
        self,
        step_type: str,
        name: str,
        input: Optional[str] = None,  # noqa: A002 - matches public SDK API
        work: Work = None,
        output: Optional[str] = None,
        metadata: Optional[dict] = None,
        record: Optional[Callable[[AgentStep, Any], None]] = None,
    ) -> Any:
        """Run one traced phase: add step, execute work, record, finish."""
        run = self._require_run()
        step = self.add_step(run, step_type=step_type, name=name, input=input, metadata=metadata)
        try:
            result = work() if callable(work) else work
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            self.finish_step(step, status=AgentStatus.FAILED, metadata=self._error_meta(metadata, exc))
            raise
        if record is not None:
            record(step, result)
        resolved_output = output if output is not None else (result if isinstance(result, str) else None)
        self.finish_step(step, output=resolved_output)
        return result

    @staticmethod
    def _stringify(value: Any) -> Optional[str]:
        """Coerce a value to a string for text columns (JSON for structures)."""
        if value is None or isinstance(value, str):
            return value
        try:
            return json.dumps(value)
        except (TypeError, ValueError):
            return str(value)

    # -- Internal helpers (low-level) ---------------------------------------

    @staticmethod
    def _as_id(ref: Optional[Union[AgentRun, int]]) -> Optional[int]:
        """Accept either an AgentRun or a raw id and return the id."""
        if ref is None:
            return None
        return ref.id if isinstance(ref, AgentRun) else ref

    @staticmethod
    def _row_id(ref: Union[object, int]) -> int:
        """Accept either an ORM row or a raw id and return the id."""
        return ref.id if hasattr(ref, "id") else ref

    @staticmethod
    def _elapsed_ms(started: Optional[float]) -> Optional[float]:
        """Milliseconds elapsed since a ``perf_counter`` marker, if present."""
        if started is None:
            return None
        return round((perf_counter() - started) * 1000, 2)

    @staticmethod
    def _error_meta(metadata: Optional[dict], exc: Exception) -> dict:
        """Merge existing metadata with error details for failed scopes."""
        merged = dict(metadata or {})
        merged["error"] = f"{type(exc).__name__}: {exc}"
        return merged
