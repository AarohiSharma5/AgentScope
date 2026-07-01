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
from contextlib import contextmanager
from time import perf_counter
from typing import Optional, Union

from ..models.agent_trace import AgentRun, AgentStep, AgentStatus
from ..services import trace_service


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
        metadata: Optional[dict] = None,
    ) -> AgentRun:
        """Finish an agent run, recording latency and final status."""
        return trace_service.finish_agent_run(
            run,
            status=status,
            latency_ms=self._elapsed_ms(self._run_started.pop(run.id, None)),
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

    @contextmanager
    def step(
        self,
        run: AgentRun,
        step_type: Optional[str] = None,
        name: Optional[str] = None,
        input: Optional[str] = None,  # noqa: A002 - matches public SDK API
        metadata: Optional[dict] = None,
    ):
        """Scope a step; marks it failed and re-raises on exception."""
        step = self.add_step(run, step_type=step_type, name=name, input=input, metadata=metadata)
        try:
            yield step
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            self.finish_step(step, status=AgentStatus.FAILED, metadata=self._error_meta(metadata, exc))
            raise
        else:
            self.finish_step(step, status=AgentStatus.SUCCESS)

    # -- Internal helpers ---------------------------------------------------

    @staticmethod
    def _as_id(ref: Optional[Union[AgentRun, int]]) -> Optional[int]:
        """Accept either an AgentRun or a raw id and return the id."""
        if ref is None:
            return None
        return ref.id if isinstance(ref, AgentRun) else ref

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
