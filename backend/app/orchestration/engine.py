"""Workflow engine (v0.4).

Executes AI workflows described by a declarative JSON graph and stored in the
database (:class:`~app.models.workflow_trace.WorkflowDefinition`). The engine is
a control-flow layer on top of the Multi-Agent SDK
(:class:`~app.orchestration.orchestrator.AgentOrchestrator`); it never touches
the ORM session directly (that lives in
:mod:`app.services.workflow_service`), and every execution is traced
automatically as a :class:`~app.models.workflow_trace.ConversationRun` /
:class:`~app.models.workflow_trace.WorkflowExecution` with one agent run per
task.

Workflow JSON format
--------------------
::

    {
      "name": "research-flow",
      "version": "1.0",
      "entry": "planner",
      "nodes": {
        "planner":   {"type": "task", "role": "planner", "next": "fanout"},
        "fanout":    {"type": "parallel",
                      "branches": ["research_a", "research_b", "research_c"],
                      "next": "merge"},
        "research_a": {"type": "task", "role": "researcher", "retries": 2},
        "research_b": {"type": "task", "role": "researcher"},
        "research_c": {"type": "task", "role": "researcher"},
        "merge":     {"type": "task", "role": "merger", "next": "review"},
        "review":    {"type": "condition",
                      "when": {"var": "confidence", "op": "lt", "value": 0.7},
                      "if_true": "critic", "if_false": "finish"},
        "critic":    {"type": "task", "role": "critic", "next": "review",
                      "max_visits": 3},
        "finish":    {"type": "end"}
      }
    }

Node types
----------
* ``task``      -- run a handler, traced as one agent. Supports ``retries`` and
                   an *advisory* per-node ``timeout_ms`` (see Handlers below).
                   ``next`` names the following node.
* ``parallel``  -- run ``branches`` (each a task node) concurrently, then
                   continue at ``next``.
* ``condition`` -- branch to ``if_true`` / ``if_false`` based on ``when`` (a
                   structured comparison against the shared context) or a
                   ``predicate`` handler. Branch targets may point *backwards*
                   to earlier nodes to form loops (bounded by ``max_visits``).
* ``end``       -- terminal node.

Handlers
--------
User business logic is supplied as ``handlers``: a mapping of node id (or role)
to a callable ``handler(context) -> result``. ``context`` is the shared
:class:`~app.orchestration.context.AgentContext`; handlers read/write it to pass
data between nodes (e.g. a task sets ``context["confidence"]`` that a downstream
condition reads). Missing handlers fall back to ``default_handler`` (a no-op),
so a workflow's control flow and tracing can be exercised without real models.

Timeouts & cancellation are cooperative. Handlers run inline (never on a helper
thread that could be abandoned), so ``timeout_ms`` is advisory: a node that
overruns is reported as a :class:`NodeTimeout` *after* the handler returns, and
the overall ``timeout_ms`` / ``cancel_token`` are enforced between nodes. A
long-running handler that must stop early should check ``context.cancelled``
(the run's cancel token is bound to the context) and return promptly.

Must be used inside a Flask application context.
"""
import logging
import operator
import threading
from collections import defaultdict
from time import perf_counter
from typing import Any, Callable, Optional, Union

from ..models.agent_trace import AgentStatus
from ..models.workflow_trace import WorkflowDefinition
from ..services import workflow_service
from .orchestrator import AgentOrchestrator

logger = logging.getLogger("agentscope")

DEFAULT_MAX_VISITS = 50
DEFAULT_MAX_STEPS = 1000
NODE_TYPES = {"task", "parallel", "condition", "end"}

Handler = Callable[[Any], Any]

_OPS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
    "in": lambda a, b: a in b,
    "contains": lambda a, b: b in a,
}


# -- Errors -----------------------------------------------------------------


class WorkflowError(Exception):
    """Base class for workflow-engine errors."""


class WorkflowValidationError(WorkflowError):
    """Raised when a workflow specification is structurally invalid."""


class WorkflowCancelled(WorkflowError):
    """Raised internally when a run is cancelled via its cancellation token."""


class WorkflowTimeout(WorkflowError):
    """Raised internally when the overall workflow deadline is exceeded."""


class NodeTimeout(WorkflowError):
    """Raised when a single node exceeds its ``timeout_ms`` (retryable)."""


# -- Cancellation -----------------------------------------------------------


class CancellationToken:
    """A cooperative cancellation signal, safe to share across threads."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._event.is_set()


# -- Result -----------------------------------------------------------------


class WorkflowResult:
    """The outcome of a workflow run."""

    def __init__(
        self,
        status: str,
        execution,
        conversation,
        context: dict,
        outputs: dict,
        visited: list[str],
        error: Optional[Exception] = None,
    ) -> None:
        self.status = status
        self.execution = execution
        self.conversation = conversation
        self.context = context
        self.outputs = outputs
        self.visited = visited
        self.error = error

    @property
    def ok(self) -> bool:
        """True when the workflow completed successfully."""
        return self.status == AgentStatus.SUCCESS

    def __repr__(self) -> str:
        return (
            f"<WorkflowResult status={self.status} "
            f"visited={self.visited} ok={self.ok}>"
        )


# -- Validation -------------------------------------------------------------


def validate_workflow(spec: dict) -> dict:
    """Validate a workflow spec, raising :class:`WorkflowValidationError`.

    Returns the spec unchanged so it can be used inline.
    """
    if not isinstance(spec, dict):
        raise WorkflowValidationError("workflow spec must be an object")
    nodes = spec.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        raise WorkflowValidationError("workflow must define a non-empty 'nodes' object")
    entry = spec.get("entry")
    if entry not in nodes:
        raise WorkflowValidationError(f"'entry' node {entry!r} is not defined")

    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            raise WorkflowValidationError(f"node {node_id!r} must be an object")
        node_type = node.get("type")
        if node_type not in NODE_TYPES:
            raise WorkflowValidationError(
                f"node {node_id!r} has invalid type {node_type!r}"
            )

        # All named transitions must reference existing nodes.
        for key in ("next", "if_true", "if_false"):
            target = node.get(key)
            if target is not None and target not in nodes:
                raise WorkflowValidationError(
                    f"node {node_id!r}.{key} points to unknown node {target!r}"
                )

        if node_type == "parallel":
            branches = node.get("branches")
            if not isinstance(branches, list) or not branches:
                raise WorkflowValidationError(
                    f"parallel node {node_id!r} needs a non-empty 'branches' list"
                )
            for branch in branches:
                if branch not in nodes:
                    raise WorkflowValidationError(
                        f"parallel node {node_id!r} references unknown branch {branch!r}"
                    )
                if nodes[branch].get("type") != "task":
                    raise WorkflowValidationError(
                        f"parallel branch {branch!r} must be a 'task' node"
                    )

        if node_type == "condition":
            if node.get("when") is None and node.get("predicate") is None:
                raise WorkflowValidationError(
                    f"condition node {node_id!r} needs 'when' or 'predicate'"
                )
            if node.get("if_true") is None and node.get("if_false") is None:
                raise WorkflowValidationError(
                    f"condition node {node_id!r} needs 'if_true' and/or 'if_false'"
                )
    return spec


# -- Engine -----------------------------------------------------------------


class WorkflowEngine:
    """Executes stored/inline workflow definitions with automatic tracing."""

    def __init__(
        self,
        handlers: Optional[dict[str, Handler]] = None,
        default_handler: Optional[Handler] = None,
        max_visits: int = DEFAULT_MAX_VISITS,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> None:
        self.handlers: dict[str, Handler] = dict(handlers or {})
        self.default_handler = default_handler
        self.max_visits = max_visits
        self.max_steps = max_steps

    # -- Definition persistence --------------------------------------------

    def register(
        self,
        spec: dict,
        name: Optional[str] = None,
        version: Optional[str] = None,
        description: Optional[str] = None,
    ) -> WorkflowDefinition:
        """Validate and persist a workflow spec as a reusable definition."""
        validate_workflow(spec)
        return workflow_service.create_workflow_definition(
            workflow_name=name or spec.get("name", "workflow"),
            description=description or spec.get("description"),
            version=version or spec.get("version"),
            workflow_json=spec,
        )

    # -- Execution ----------------------------------------------------------

    def run(
        self,
        workflow: Union[int, WorkflowDefinition, dict],
        context: Optional[dict] = None,
        handlers: Optional[dict[str, Handler]] = None,
        cancel_token: Optional[CancellationToken] = None,
        timeout_ms: Optional[float] = None,
        conversation_name: Optional[str] = None,
    ) -> WorkflowResult:
        """Execute a workflow, returning a :class:`WorkflowResult`.

        ``workflow`` may be a stored definition id, a
        :class:`WorkflowDefinition`, or an inline spec dict (which is persisted
        before running, since definitions are stored in the database). The
        engine is resilient: control-flow / handler failures are captured on the
        result (``result.error``) rather than raised, while the traced execution
        is always finished with the appropriate status.
        """
        spec, definition = self._resolve(workflow)
        merged_handlers = {**self.handlers, **(handlers or {})}
        token = cancel_token or CancellationToken()

        orchestrator = AgentOrchestrator(
            conversation_name=conversation_name or spec.get("name"),
            context=context,
            workflow_definition_id=definition.id,
        )
        ctx = orchestrator.context
        # Expose the cancel token so long-running handlers can cooperate
        # (``if ctx.cancelled: return``) — the only way to actually stop
        # in-flight work, since threads can't be preempted.
        ctx.bind_cancel_token(token)
        nodes = spec["nodes"]

        started = perf_counter()
        visits: dict[str, int] = defaultdict(int)
        outputs: dict[str, Any] = {}
        visited: list[str] = []
        steps = 0
        status = AgentStatus.SUCCESS
        error: Optional[Exception] = None
        current: Optional[str] = spec["entry"]

        try:
            while current is not None:
                node = nodes[current]
                if node.get("type") == "end":
                    visited.append(current)
                    break

                self._check_cancel(token)
                self._check_timeout(started, timeout_ms)

                steps += 1
                if steps > self.max_steps:
                    raise WorkflowError(f"workflow exceeded max_steps ({self.max_steps})")
                visits[current] += 1
                node_max_visits = node.get("max_visits", self.max_visits)
                if visits[current] > node_max_visits:
                    raise WorkflowError(
                        f"node {current!r} exceeded max_visits ({node_max_visits})"
                    )
                visited.append(current)

                current = self._step(
                    orchestrator, current, node, nodes, merged_handlers,
                    ctx, token, started, timeout_ms, outputs,
                )
        except WorkflowCancelled:
            status = AgentStatus.CANCELLED
            logger.info("workflow cancelled after nodes=%s", visited)
        except WorkflowTimeout:
            status = AgentStatus.TIMEOUT
            logger.warning("workflow timed out after nodes=%s", visited)
        except Exception as exc:  # noqa: BLE001 - capture, finish trace, report
            status = AgentStatus.FAILED
            error = exc
            logger.exception("workflow failed at node=%s", current)

        orchestrator.finish(status=status)
        return WorkflowResult(
            status=status,
            execution=orchestrator.execution,
            conversation=orchestrator.conversation,
            context=ctx.all(),
            outputs=outputs,
            visited=visited,
            error=error,
        )

    # -- Node dispatch ------------------------------------------------------

    def _step(
        self, orchestrator, node_id, node, nodes, handlers, ctx, token, started, timeout_ms, outputs
    ) -> Optional[str]:
        """Execute a single node and return the id of the next node (or None)."""
        node_type = node["type"]
        if node_type == "task":
            outputs[node_id] = self._run_task(
                orchestrator, node_id, node, handlers, ctx, token, started, timeout_ms
            )
            return node.get("next")
        if node_type == "parallel":
            outputs.update(
                self._run_parallel(
                    orchestrator, node_id, node, nodes, handlers, ctx, token, started, timeout_ms
                )
            )
            return node.get("next")
        if node_type == "condition":
            branch = self._eval_condition(node, ctx, handlers, node_id)
            logger.debug("condition %s -> %s", node_id, branch)
            return node.get("if_true") if branch else node.get("if_false")
        raise WorkflowValidationError(f"cannot execute node type {node_type!r}")

    def _run_task(
        self, orchestrator, node_id, node, handlers, ctx, token, started, timeout_ms
    ) -> Any:
        """Run a task node with retry + per-node timeout support (traced)."""
        role = node.get("role") or node_id
        handler = handlers.get(node_id) or handlers.get(role) or self.default_handler
        node_timeout = node.get("timeout_ms")
        retries = int(node.get("retries", 0))

        last_error: Optional[Exception] = None
        for attempt in range(retries + 1):
            self._check_cancel(token)
            self._check_timeout(started, timeout_ms)
            agent = orchestrator.create_agent(
                name=self._agent_name(node_id),
                role=role,
                display_name=node_id,
                metadata={"node": node_id, "attempt": attempt},
            )
            try:
                result = agent.execute(work=self._wrap(handler, ctx, node_timeout))
                ctx.set(f"{node_id}.result", result)
                return result
            except NodeTimeout as exc:
                last_error = exc
                logger.warning("node %s attempt %s timed out", node_id, attempt)
            except Exception as exc:  # noqa: BLE001 - retryable
                last_error = exc
                logger.warning("node %s attempt %s failed: %s", node_id, attempt, exc)

        raise WorkflowError(
            f"node {node_id!r} failed after {retries} retries"
        ) from last_error

    def _run_parallel(
        self, orchestrator, node_id, node, nodes, handlers, ctx, token, started, timeout_ms
    ) -> dict:
        """Run a parallel node's branches concurrently (traced as one group)."""
        self._check_cancel(token)
        self._check_timeout(started, timeout_ms)

        tasks = []
        agent_to_branch = {}
        for branch in node["branches"]:
            branch_node = nodes[branch]
            role = branch_node.get("role") or branch
            handler = handlers.get(branch) or handlers.get(role) or self.default_handler
            agent = orchestrator.create_agent(
                name=self._agent_name(branch),
                role=role,
                display_name=branch,
                metadata={"node": branch, "parallel_of": node_id},
            )
            agent_to_branch[agent.name] = branch
            tasks.append((agent, self._wrap(handler, ctx, branch_node.get("timeout_ms"))))

        results_by_agent = orchestrator.run_parallel(tasks)
        results = {}
        for agent_name, result in results_by_agent.items():
            branch = agent_to_branch[agent_name]
            results[branch] = result
            ctx.set(f"{branch}.result", result)
        return results

    # -- Helpers ------------------------------------------------------------

    def _wrap(self, handler: Optional[Handler], ctx, node_timeout: Optional[float]):
        """Wrap a handler into a zero-arg callable with an *advisory* timeout.

        Handlers run **inline** on the calling thread. We deliberately do not
        run them on a helper thread with ``future.result(timeout=...)``: a
        running Python thread cannot be preempted, so abandoning it on timeout
        would leak a "zombie" that keeps mutating the shared ``AgentContext``
        (corrupting state the workflow has moved past) and would allocate a new
        thread pool per node / retry / parallel branch — unbounded growth under
        load.

        Instead ``timeout_ms`` is advisory: the handler runs to completion and,
        if it overran its budget, :class:`NodeTimeout` is raised afterwards (the
        caller may retry). Handlers that need to stop early should cooperate by
        checking ``ctx.cancelled`` (the workflow's cancel token is bound to the
        context) or enforce their own I/O timeouts.
        """

        def work():
            if handler is None:
                return None
            started = perf_counter()
            result = handler(ctx)
            if node_timeout and (perf_counter() - started) * 1000 > node_timeout:
                raise NodeTimeout(
                    f"node exceeded its advisory timeout of {node_timeout}ms"
                )
            return result

        return work

    def _eval_condition(self, node, ctx, handlers, node_id) -> bool:
        """Evaluate a condition node against the shared context."""
        predicate = node.get("predicate")
        if predicate is not None:
            fn = handlers.get(predicate) or handlers.get(node_id)
            if fn is None:
                raise WorkflowValidationError(
                    f"condition {node_id!r} predicate {predicate!r} not provided"
                )
            return bool(fn(ctx))

        when = node["when"]
        var = when.get("var")
        op = when.get("op", "truthy")
        actual = ctx.get(var)
        if op == "truthy":
            return bool(actual)
        fn = _OPS.get(op)
        if fn is None:
            raise WorkflowValidationError(f"condition {node_id!r} has invalid op {op!r}")
        try:
            return bool(fn(actual, when.get("value")))
        except TypeError:
            # e.g. comparing None to a number: treat as a non-match rather than crash.
            return False

    def _resolve(self, workflow) -> tuple[dict, WorkflowDefinition]:
        """Resolve the input into a (spec, persisted definition) pair."""
        if isinstance(workflow, WorkflowDefinition):
            return validate_workflow(workflow.workflow_json), workflow
        if isinstance(workflow, int):
            definition = workflow_service.get_workflow_definition(workflow)
            if definition is None:
                raise WorkflowError(f"workflow definition {workflow} not found")
            return validate_workflow(definition.workflow_json), definition
        if isinstance(workflow, dict):
            definition = self.register(workflow)
            return workflow, definition
        raise WorkflowValidationError(
            "workflow must be a definition id, WorkflowDefinition, or spec dict"
        )

    @staticmethod
    def _check_cancel(token: CancellationToken) -> None:
        if token.cancelled:
            raise WorkflowCancelled()

    @staticmethod
    def _check_timeout(started: float, timeout_ms: Optional[float]) -> None:
        if timeout_ms and (perf_counter() - started) * 1000 > timeout_ms:
            raise WorkflowTimeout()

    _seq = 0

    def _agent_name(self, node_id: str) -> str:
        """Produce a registry-unique agent name (loops/retries reuse node ids)."""
        self._seq += 1
        return f"{node_id}#{self._seq}"
