"""The entry point of the Multi-Agent SDK.

:class:`AgentOrchestrator` owns a conversation (a
:class:`~app.models.workflow_trace.ConversationRun`), a shared
:class:`~app.orchestration.context.AgentContext`, an
:class:`~app.orchestration.registry.AgentRegistry`, and a
:class:`~app.utils.trace_recorder.TraceRecorder` used to trace each agent's
execution as a (possibly nested) v0.2 ``AgentRun``.

Example
-------
    orchestrator = AgentOrchestrator()

    planner = orchestrator.create_agent(name="Planner", role="planner")
    researcher = orchestrator.create_agent(name="Researcher", role="researcher")

    planner.send(researcher, message="Research LangSmith.")
    planner.execute()
    researcher.execute()

    orchestrator.finish()

Must be used inside a Flask application context (as routes/services already are).
"""
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import Any, Iterable, Optional, Union

from ..models.agent_trace import AgentStatus
from ..services import trace_service, workflow_service
from ..utils.trace_recorder import TraceRecorder
from .agent import Agent
from .context import AgentContext
from .registry import AgentRegistry

# A parallel task is an agent (executed with no work) or an (agent, work) pair.
ParallelTask = Union[Agent, tuple[Agent, Any]]


class AgentOrchestrator:
    """Coordinates multiple collaborating agents within one traced conversation."""

    def __init__(
        self,
        request_trace_id: Optional[int] = None,
        conversation_name: Optional[str] = None,
        context: Optional[dict] = None,
        metadata: Optional[dict] = None,
        workflow_name: Optional[str] = None,
        workflow_version: Optional[str] = None,
        workflow_description: Optional[str] = None,
        workflow_json: Optional[dict] = None,
    ) -> None:
        # Anchor the conversation to a request trace, creating a lightweight one
        # when the caller doesn't supply an existing request id.
        if request_trace_id is None:
            trace = trace_service.create_trace(
                {
                    "user_prompt": conversation_name or "multi-agent conversation",
                    "model_name": "multi-agent",
                }
            )
            request_trace_id = trace.id
        self.request_trace_id = request_trace_id

        self.conversation = workflow_service.create_conversation_run(
            request_trace_id=request_trace_id,
            conversation_name=conversation_name,
            status=AgentStatus.RUNNING,
            metadata=metadata,
        )

        # Optional workflow definition + execution linked to this conversation.
        self.definition = None
        self.execution = None
        if workflow_name is not None:
            self.definition = workflow_service.create_workflow_definition(
                workflow_name=workflow_name,
                description=workflow_description,
                version=workflow_version,
                workflow_json=workflow_json,
            )
            self.execution = workflow_service.create_workflow_execution(
                workflow_definition_id=self.definition.id,
                conversation_run_id=self.conversation.id,
                status=AgentStatus.RUNNING,
            )

        self.recorder = TraceRecorder(request_trace_id)
        self.context = AgentContext(context)
        self.registry = AgentRegistry()

        self._started_at = perf_counter()
        self._order = 0
        self._parallel_seq = 0
        self._finished = False

    # -- Agent creation -----------------------------------------------------

    def create_agent(
        self,
        name: str,
        role: Optional[str] = None,
        parent: Optional[Agent] = None,
        display_name: Optional[str] = None,
        parallel_group: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Agent:
        """Create, persist and register a new agent (optionally nested under ``parent``)."""
        node = workflow_service.create_agent_node(
            conversation_run_id=self.conversation.id,
            agent_role=role,
            display_name=display_name or name,
            parent_node_id=parent.node.id if parent is not None else None,
            execution_order=self._next_order(),
            parallel_group=parallel_group,
            status=AgentStatus.PENDING,
            metadata=metadata,
        )
        agent = Agent(
            orchestrator=self,
            name=name,
            node=node,
            role=role,
            parent=parent,
            context=self.context,
            metadata=metadata,
        )
        return self.registry.add(agent)

    def get_agent(self, name: str) -> Optional[Agent]:
        """Return a registered agent by name, or None."""
        return self.registry.get(name)

    @property
    def agents(self) -> list[Agent]:
        """All agents registered in this conversation."""
        return self.registry.all()

    # -- Parallel execution -------------------------------------------------

    def run_parallel(
        self, tasks: Iterable[ParallelTask], group: Optional[str] = None
    ) -> dict[str, Any]:
        """Execute several agents concurrently, tagging them as one parallel group.

        ``tasks`` is an iterable of agents or ``(agent, work)`` pairs. Each
        agent's user ``work`` runs in its own thread (only the callable is
        threaded — persistence stays on the main thread); each agent's run is
        traced with its measured wall-clock latency. Returns ``{agent_name:
        result}``. If any task raised, the first exception is re-raised after all
        runs are recorded.
        """
        normalized = [t if isinstance(t, tuple) else (t, None) for t in tasks]
        if not normalized:
            return {}
        group = group or f"parallel-{self._next_parallel_group()}"

        # 1. Begin every run (sequential DB writes), tagged with the group.
        for agent, _ in normalized:
            agent._begin(parallel_group=group)

        # 2. Run the user work concurrently (no DB access inside threads).
        with ThreadPoolExecutor(max_workers=len(normalized)) as executor:
            outcomes = list(
                executor.map(lambda pair: pair[0]._run_timed(pair[1]), normalized)
            )

        # 3. Finish every run (sequential DB writes) with its measured latency.
        results: dict[str, Any] = {}
        first_error: Optional[Exception] = None
        for (agent, _), (result, error, latency_ms) in zip(normalized, outcomes):
            agent._end(
                status=AgentStatus.FAILED if error else AgentStatus.SUCCESS,
                latency_ms=latency_ms,
                error=error,
            )
            results[agent.name] = result
            if error is not None and first_error is None:
                first_error = error

        if first_error is not None:
            raise first_error
        return results

    # -- Finish -------------------------------------------------------------

    def finish(self, status: str = AgentStatus.SUCCESS, metadata: Optional[dict] = None):
        """Finish the conversation (and workflow execution), recording latency/status."""
        if self._finished:
            return self.conversation
        latency_ms = round((perf_counter() - self._started_at) * 1000, 2)

        if self.execution is not None:
            workflow_service.finish_workflow_execution(
                self.execution, status=status, latency_ms=latency_ms
            )
        workflow_service.finish_conversation_run(
            self.conversation, status=status, latency_ms=latency_ms, metadata=metadata
        )
        # Keep the parent request trace's terminal status in sync.
        trace_service.update_trace(
            self.request_trace_id,
            status="success" if status == AgentStatus.SUCCESS else "failed",
        )
        self._finished = True
        return self.conversation

    # -- Internal counters --------------------------------------------------

    def _next_order(self) -> int:
        order = self._order
        self._order += 1
        return order

    def _next_parallel_group(self) -> int:
        self._parallel_seq += 1
        return self._parallel_seq

    def __repr__(self) -> str:
        return (
            f"<AgentOrchestrator conversation_id={self.conversation.id} "
            f"agents={len(self.registry)}>"
        )
