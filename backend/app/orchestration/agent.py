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
from ..models.workflow_trace import MessageType
from ..services import workflow_service
from ..services.message_service import message_service

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
        message_type: str = MessageType.INSTRUCTION,
        token_usage: Optional[dict] = None,
        latency_ms: Optional[float] = None,
        metadata: Optional[dict] = None,
        reply_to=None,
    ):
        """Send a typed message to another agent, persisted via the comms layer."""
        return message_service.send(
            sender=self.node,
            receiver=receiver.node if receiver is not None else None,
            message_type=message_type,
            content=message,
            token_usage=token_usage,
            latency_ms=latency_ms,
            metadata=metadata,
            reply_to=reply_to,
            conversation_run_id=self.node.conversation_run_id,
        )

    def instruct(self, receiver: "Agent", message: str, **kwargs):
        """Send an ``instruction`` message to another agent."""
        return self.send(receiver, message, message_type=MessageType.INSTRUCTION, **kwargs)

    def ask(self, receiver: "Agent", message: str, **kwargs):
        """Send a ``question`` message to another agent."""
        return self.send(receiver, message, message_type=MessageType.QUESTION, **kwargs)

    def answer(self, receiver: "Agent", message: str, **kwargs):
        """Send an ``answer`` message to another agent."""
        return self.send(receiver, message, message_type=MessageType.ANSWER, **kwargs)

    def observe(self, message: str, receiver: Optional["Agent"] = None, **kwargs):
        """Record an ``observation`` (optionally addressed to an agent)."""
        return self.send(receiver, message, message_type=MessageType.OBSERVATION, **kwargs)

    def critique(self, receiver: "Agent", message: str, **kwargs):
        """Send a ``critique`` message to another agent."""
        return self.send(receiver, message, message_type=MessageType.CRITIQUE, **kwargs)

    def broadcast(
        self,
        message: str,
        message_type: str = MessageType.INSTRUCTION,
        receivers: Optional[list["Agent"]] = None,
        **kwargs,
    ):
        """Broadcast a message to every other agent (or an explicit subset)."""
        return message_service.broadcast(
            sender=self.node,
            message_type=message_type,
            content=message,
            receivers=[a.node for a in receivers] if receivers is not None else None,
            **kwargs,
        )

    def reply(
        self,
        to_message,
        message: str,
        message_type: str = MessageType.ANSWER,
        **kwargs,
    ):
        """Reply to a received message, threading it back to the sender."""
        return message_service.reply(
            to_message=to_message,
            sender=self.node,
            message_type=message_type,
            content=message,
            **kwargs,
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
