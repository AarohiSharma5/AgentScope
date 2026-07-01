"""The agent handle returned by :meth:`AgentOrchestrator.create_agent`.

An :class:`Agent` is a lightweight façade over a persisted
:class:`~app.models.workflow_trace.AgentNode`. It knows how to:

* send messages to other agents (persisted as ``AgentMessage`` rows), and
* execute its own work, which is traced as a v0.2 ``AgentRun`` (nested under its
  parent agent's run when the agent has a parent).

All persistence is delegated to the service layer; timing, status and latency
are handled automatically.
"""
from time import perf_counter
from typing import TYPE_CHECKING, Any, Optional

from ..models.agent_trace import AgentStatus
from ..services import workflow_service

if TYPE_CHECKING:
    from ..models.agent_trace import AgentRun
    from ..models.workflow_trace import AgentNode
    from .context import AgentContext
    from .orchestrator import AgentOrchestrator


class Agent:
    """A single collaborating agent within a conversation."""

    def __init__(
        self,
        orchestrator: "AgentOrchestrator",
        name: str,
        node: "AgentNode",
        role: Optional[str] = None,
        parent: Optional["Agent"] = None,
        context: Optional["AgentContext"] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.name = name
        self.role = role
        self.node = node
        self.parent = parent
        self.context = context
        self.metadata = metadata
        # The v0.2 AgentRun produced when this agent executes.
        self.run: Optional["AgentRun"] = None
        self._started = False
        self._finished = False

    # -- Messaging ----------------------------------------------------------

    def send(
        self,
        receiver: Optional["Agent"] = None,
        message: Optional[str] = None,
        message_type: str = "message",
        token_usage: Optional[dict] = None,
        latency_ms: Optional[float] = None,
        metadata: Optional[dict] = None,
    ):
        """Send a message to another agent (or broadcast when ``receiver`` is None)."""
        return workflow_service.create_agent_message(
            sender_node_id=self.node.id,
            receiver_node_id=receiver.node.id if receiver is not None else None,
            message_type=message_type,
            content=message,
            token_usage=token_usage,
            latency_ms=latency_ms,
            metadata=metadata,
        )

    # -- Execution ----------------------------------------------------------

    def execute(
        self,
        work=None,
        output: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Any:
        """Execute this agent's work, tracing it as a (possibly nested) agent run.

        ``work`` is an optional zero-arg callable; its return value is passed
        back to the caller. Latency and status are recorded automatically, and a
        raised exception marks the run/node failed and is re-raised.
        """
        self._begin(metadata=metadata)
        try:
            result = work() if callable(work) else work
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            self._end(status=AgentStatus.FAILED, error=exc)
            raise
        self._end(status=AgentStatus.SUCCESS)
        return result if result is not None else output

    # -- Internal lifecycle (shared by sequential + parallel execution) -----

    def _begin(self, parallel_group: Optional[str] = None, metadata: Optional[dict] = None) -> "AgentRun":
        """Start this agent's run (nested under its parent) and mark the node running."""
        if self._started:
            return self.run
        parent_run = self.parent.run if (self.parent and self.parent.run) else None
        self.run = self.orchestrator.recorder.start_agent(
            name=self.name,
            type=self.role,
            parent=parent_run,
            metadata=metadata if metadata is not None else self.metadata,
        )
        self._started = True
        workflow_service.update_agent_node(
            self.node,
            status=AgentStatus.RUNNING,
            agent_run_id=self.run.id,
            parallel_group=parallel_group,
        )
        return self.run

    def _end(
        self,
        status: str = AgentStatus.SUCCESS,
        latency_ms: Optional[float] = None,
        error: Optional[Exception] = None,
    ) -> None:
        """Finish this agent's run and sync the node's terminal status."""
        if not self._started or self._finished:
            return
        metadata = None
        if error is not None:
            metadata = dict(self.metadata or {})
            metadata["error"] = f"{type(error).__name__}: {error}"
        self.orchestrator.recorder.finish_agent(
            self.run, status=status, latency_ms=latency_ms, metadata=metadata
        )
        workflow_service.update_agent_node(self.node, status=status)
        self._finished = True

    def _run_timed(self, work) -> tuple:
        """Run ``work`` (off the DB session), returning (result, error, latency_ms).

        Used by the orchestrator's parallel executor: only the user callable runs
        here (safe to thread); persistence happens on the main thread afterwards.
        """
        started = perf_counter()
        try:
            result = work() if callable(work) else work
            error = None
        except Exception as exc:  # noqa: BLE001 - captured, re-raised by caller
            result, error = None, exc
        return result, error, round((perf_counter() - started) * 1000, 2)

    def __repr__(self) -> str:
        return f"<Agent name={self.name!r} role={self.role!r} node_id={self.node.id}>"
