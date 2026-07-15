"""Tests for the v0.4 Workflow Engine (app.orchestration.engine)."""
import time

import pytest

from app.models.agent_trace import AgentRun, AgentStatus
from app.models.workflow_trace import (
    AgentNode,
    ConversationRun,
    WorkflowDefinition,
    WorkflowExecution,
)
from app.orchestration import (
    CancellationToken,
    WorkflowEngine,
    WorkflowError,
    WorkflowValidationError,
    validate_workflow,
)


# -- Specs ------------------------------------------------------------------


def _sequential_spec():
    return {
        "name": "sequential-flow",
        "version": "1.0",
        "entry": "planner",
        "nodes": {
            "planner": {"type": "task", "role": "planner", "next": "retriever"},
            "retriever": {"type": "task", "role": "retriever", "next": "llm"},
            "llm": {"type": "task", "role": "llm", "next": "reviewer"},
            "reviewer": {"type": "task", "role": "reviewer", "next": "done"},
            "done": {"type": "end"},
        },
    }


def _parallel_spec():
    return {
        "name": "parallel-flow",
        "entry": "planner",
        "nodes": {
            "planner": {"type": "task", "role": "planner", "next": "fanout"},
            "fanout": {
                "type": "parallel",
                "branches": ["res_a", "res_b", "res_c"],
                "next": "merge",
            },
            "res_a": {"type": "task", "role": "researcher"},
            "res_b": {"type": "task", "role": "researcher"},
            "res_c": {"type": "task", "role": "researcher"},
            "merge": {"type": "task", "role": "merger", "next": "reviewer"},
            "reviewer": {"type": "task", "role": "reviewer", "next": "done"},
            "done": {"type": "end"},
        },
    }


def _conditional_spec():
    return {
        "name": "conditional-flow",
        "entry": "review",
        "nodes": {
            "review": {
                "type": "condition",
                "when": {"var": "confidence", "op": "lt", "value": 0.7},
                "if_true": "critic",
                "if_false": "finish",
            },
            "critic": {"type": "task", "role": "critic", "next": "review", "max_visits": 5},
            "finish": {"type": "end"},
        },
    }


# -- Validation -------------------------------------------------------------


def test_validate_rejects_unknown_entry():
    with pytest.raises(WorkflowValidationError):
        validate_workflow({"entry": "nope", "nodes": {"a": {"type": "end"}}})


def test_validate_rejects_dangling_transition():
    with pytest.raises(WorkflowValidationError):
        validate_workflow(
            {"entry": "a", "nodes": {"a": {"type": "task", "next": "ghost"}}}
        )


def test_validate_parallel_branch_must_be_task():
    spec = {
        "entry": "p",
        "nodes": {
            "p": {"type": "parallel", "branches": ["c"], "next": "e"},
            "c": {"type": "end"},
            "e": {"type": "end"},
        },
    }
    with pytest.raises(WorkflowValidationError):
        validate_workflow(spec)


# -- Sequential -------------------------------------------------------------


def test_sequential_execution_visits_all_nodes_in_order(app_ctx):
    engine = WorkflowEngine()
    order = []
    handlers = {
        role: (lambda r: (lambda ctx: order.append(r)))(role)
        for role in ("planner", "retriever", "llm", "reviewer")
    }

    result = engine.run(_sequential_spec(), handlers=handlers)

    assert result.ok
    assert order == ["planner", "retriever", "llm", "reviewer"]
    assert result.visited == ["planner", "retriever", "llm", "reviewer", "done"]

    # Definition stored + execution + conversation traced with 4 agent runs.
    assert WorkflowDefinition.query.count() == 1
    assert WorkflowExecution.query.one().status == AgentStatus.SUCCESS
    assert ConversationRun.query.one().status == AgentStatus.SUCCESS
    assert AgentRun.query.count() == 4
    assert AgentNode.query.count() == 4


def test_run_by_definition_id_reuses_stored_definition(app_ctx):
    engine = WorkflowEngine()
    definition = engine.register(_sequential_spec(), name="stored")

    result = engine.run(definition.id)

    assert result.ok
    # Only the one pre-registered definition exists; run did not create another.
    assert WorkflowDefinition.query.count() == 1
    assert result.execution.workflow_definition_id == definition.id


# -- Parallel ---------------------------------------------------------------


def test_parallel_execution_runs_branches_and_groups_them(app_ctx):
    engine = WorkflowEngine(default_handler=lambda ctx: "ok")

    result = engine.run(_parallel_spec())

    assert result.ok
    assert {"res_a", "res_b", "res_c"} <= set(result.outputs)
    assert result.outputs["res_a"] == "ok"

    # The three researcher branches share one parallel group.
    branch_nodes = AgentNode.query.filter(
        AgentNode.display_name.in_(["res_a", "res_b", "res_c"])
    ).all()
    groups = {n.parallel_group for n in branch_nodes}
    assert len(groups) == 1 and None not in groups


def test_parallel_branches_run_concurrently(app_ctx):
    engine = WorkflowEngine()
    sleep_s = 0.2

    def slow(ctx):
        time.sleep(sleep_s)
        return "done"

    handlers = {"a": slow, "b": slow, "c": slow}

    parallel_spec = {
        "entry": "fanout",
        "nodes": {
            "fanout": {"type": "parallel", "branches": ["a", "b", "c"], "next": "done"},
            "a": {"type": "task", "role": "a"},
            "b": {"type": "task", "role": "b"},
            "c": {"type": "task", "role": "c"},
            "done": {"type": "end"},
        },
    }
    # Same three tasks, but chained so they must run one after another. Both
    # workflows share the same per-node overhead, so comparing them cancels out
    # runner speed — the only difference is that the parallel version overlaps
    # the sleeps. This is far more robust than an absolute wall-clock threshold
    # (which flakes on slow/loaded CI runners, e.g. Windows).
    serial_spec = {
        "entry": "a",
        "nodes": {
            "a": {"type": "task", "role": "a", "next": "b"},
            "b": {"type": "task", "role": "b", "next": "c"},
            "c": {"type": "task", "role": "c", "next": "done"},
            "done": {"type": "end"},
        },
    }

    # Warm up first: the very first engine.run pays one-time costs (lazy
    # imports, thread-pool spin-up, first trace-record writes). Timing that
    # cold-start run made the parallel case (which happened to run first) look
    # no faster than the warm serial run and flaked on loaded CI runners. A
    # throwaway run pays those costs so both measured runs are on equal footing.
    assert engine.run(parallel_spec, handlers=handlers).ok
    assert engine.run(serial_spec, handlers=handlers).ok

    started = time.perf_counter()
    parallel_result = engine.run(parallel_spec, handlers=handlers)
    parallel_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    serial_result = engine.run(serial_spec, handlers=handlers)
    serial_elapsed = time.perf_counter() - started

    assert parallel_result.ok and serial_result.ok
    # Concurrency must save real time: the parallel run overlaps the sleeps
    # (~1x sleep_s) while the serial run pays for all three (~3x sleep_s). We
    # require the parallel run to beat serial by at least one sleep interval,
    # which the 2x sleep_s of overlap comfortably clears above scheduling noise.
    assert parallel_elapsed < serial_elapsed - sleep_s


# -- Conditional / branching / loops ---------------------------------------


def test_conditional_takes_false_branch(app_ctx):
    engine = WorkflowEngine()
    result = engine.run(_conditional_spec(), context={"confidence": 0.9})

    assert result.ok
    assert result.visited == ["review", "finish"]
    # No task ran (went straight to finish).
    assert AgentRun.query.count() == 0


def test_conditional_loop_until_condition_clears(app_ctx):
    engine = WorkflowEngine()

    def critic(ctx):
        # Improve confidence each pass until the loop exits.
        ctx.set("confidence", ctx.get("confidence", 0) + 0.2)

    result = engine.run(
        _conditional_spec(), context={"confidence": 0.2}, handlers={"critic": critic}
    )

    assert result.ok
    # 0.2 -> 0.4 -> 0.6 -> 0.8 : critic runs 3 times, then finish.
    assert result.visited.count("critic") == 3
    assert result.context["confidence"] == pytest.approx(0.8)
    assert result.visited[-1] == "finish"


def test_loop_guard_trips_on_runaway_condition(app_ctx):
    engine = WorkflowEngine()
    # critic never improves confidence -> infinite loop, bounded by max_visits=5.
    result = engine.run(
        _conditional_spec(), context={"confidence": 0.1}, handlers={"critic": lambda ctx: None}
    )

    assert result.status == AgentStatus.FAILED
    assert "max_visits" in str(result.error)


def test_predicate_condition(app_ctx):
    engine = WorkflowEngine()
    spec = {
        "entry": "gate",
        "nodes": {
            "gate": {
                "type": "condition",
                "predicate": "is_ready",
                "if_true": "go",
                "if_false": "stop",
            },
            "go": {"type": "task", "role": "go"},
            "stop": {"type": "end"},
        },
    }
    result = engine.run(
        spec, context={"ready": True}, handlers={"is_ready": lambda ctx: ctx.get("ready")}
    )
    assert result.ok
    assert "go" in result.visited


# -- Retries ----------------------------------------------------------------


def test_retries_eventually_succeed(app_ctx):
    engine = WorkflowEngine()
    calls = {"n": 0}

    def flaky(ctx):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "recovered"

    spec = {
        "entry": "task",
        "nodes": {
            "task": {"type": "task", "role": "worker", "retries": 3, "next": "done"},
            "done": {"type": "end"},
        },
    }
    result = engine.run(spec, handlers={"task": flaky})

    assert result.ok
    assert calls["n"] == 3
    assert result.outputs["task"] == "recovered"
    # Three attempts => three traced agent runs (2 failed, 1 success).
    runs = AgentRun.query.all()
    assert len(runs) == 3
    assert sum(r.status == AgentStatus.FAILED for r in runs) == 2
    assert sum(r.status == AgentStatus.SUCCESS for r in runs) == 1


def test_retries_exhausted_fails_workflow(app_ctx):
    engine = WorkflowEngine()

    def always_fail(ctx):
        raise RuntimeError("nope")

    spec = {
        "entry": "task",
        "nodes": {
            "task": {"type": "task", "role": "worker", "retries": 1, "next": "done"},
            "done": {"type": "end"},
        },
    }
    result = engine.run(spec, handlers={"task": always_fail})

    assert result.status == AgentStatus.FAILED
    assert AgentRun.query.count() == 2  # initial + 1 retry, both failed


# -- Cancellation -----------------------------------------------------------


def test_cancellation_stops_before_next_node(app_ctx):
    engine = WorkflowEngine()
    token = CancellationToken()

    def cancel_after_planner(ctx):
        token.cancel()

    result = engine.run(
        _sequential_spec(),
        handlers={"planner": cancel_after_planner},
        cancel_token=token,
    )

    assert result.status == AgentStatus.CANCELLED
    assert result.visited == ["planner"]
    assert result.conversation.status == AgentStatus.CANCELLED


# -- Timeout ----------------------------------------------------------------


def test_overall_timeout(app_ctx):
    engine = WorkflowEngine()

    def slow(ctx):
        time.sleep(0.1)

    spec = {
        "entry": "a",
        "nodes": {
            "a": {"type": "task", "role": "a", "next": "b"},
            "b": {"type": "task", "role": "b", "next": "done"},
            "done": {"type": "end"},
        },
    }
    result = engine.run(spec, handlers={"a": slow, "b": slow}, timeout_ms=50)

    assert result.status == AgentStatus.TIMEOUT
    assert result.conversation.status == AgentStatus.TIMEOUT


def test_per_node_timeout_with_retry(app_ctx):
    engine = WorkflowEngine()
    calls = {"n": 0}

    def sometimes_slow(ctx):
        calls["n"] += 1
        if calls["n"] == 1:
            time.sleep(0.2)  # first attempt exceeds node timeout
        return "ok"

    spec = {
        "entry": "task",
        "nodes": {
            "task": {
                "type": "task",
                "role": "worker",
                "timeout_ms": 50,
                "retries": 1,
                "next": "done",
            },
            "done": {"type": "end"},
        },
    }
    result = engine.run(spec, handlers={"task": sometimes_slow})

    assert result.ok
    assert calls["n"] == 2


def test_per_node_timeout_is_advisory_and_runs_to_completion(app_ctx):
    """A node that overruns its advisory timeout runs fully, then fails (no retry).

    Guards C5: the handler is never abandoned on a helper thread, so it always
    completes exactly once and cannot leak a zombie that mutates the context.
    """
    engine = WorkflowEngine()
    calls = {"n": 0}

    def slow(ctx):
        calls["n"] += 1
        time.sleep(0.08)  # exceeds the 20ms advisory budget
        ctx.set("did_run", True)
        return "done"

    spec = {
        "entry": "task",
        "nodes": {
            "task": {"type": "task", "role": "worker", "timeout_ms": 20, "next": "done"},
            "done": {"type": "end"},
        },
    }
    result = engine.run(spec, handlers={"task": slow})

    assert result.status == AgentStatus.FAILED
    assert isinstance(result.error, WorkflowError)
    assert calls["n"] == 1  # ran exactly once, to completion
    assert result.context.get("did_run") is True


def test_handler_can_cooperatively_cancel_via_context(app_ctx):
    """A long-running handler can observe cancellation through the shared context."""
    engine = WorkflowEngine()
    token = CancellationToken()
    observed = {}

    def worker(ctx):
        observed["before"] = ctx.cancelled
        token.cancel()  # simulate an external cancel request mid-work
        observed["after"] = ctx.cancelled
        return "partial"

    result = engine.run(
        _sequential_spec(),
        handlers={"planner": worker},
        cancel_token=token,
    )

    assert observed == {"before": False, "after": True}
    # The cooperative check flips as soon as the token is set; the engine then
    # stops at the next node boundary.
    assert result.status == AgentStatus.CANCELLED
    assert result.visited == ["planner"]


# -- Agent-name sequencing (H4) ---------------------------------------------


def test_agent_name_counter_is_per_instance():
    """Each engine has its own counter; state is not shared via a class attr."""
    a = WorkflowEngine()
    b = WorkflowEngine()

    assert a._agent_name("planner") == "planner#1"
    assert a._agent_name("planner") == "planner#2"
    # A fresh engine starts at 1, unaffected by ``a``'s counter.
    assert b._agent_name("planner") == "planner#1"


def test_agent_name_is_unique_under_concurrency():
    """Concurrent name generation on one engine never collides.

    ``_agent_name`` is called for every node/branch/retry; the counter is
    lock-guarded so parallel callers can't be handed the same number (a
    duplicate name would break AgentRegistry.add).
    """
    import threading

    engine = WorkflowEngine()
    names: list[str] = []
    names_lock = threading.Lock()
    start = threading.Event()

    def worker():
        start.wait()
        local = [engine._agent_name("node") for _ in range(200)]
        with names_lock:
            names.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join()

    # 16 threads x 200 calls, all distinct and contiguous 1..3200.
    assert len(names) == 3200
    assert len(set(names)) == 3200
    seqs = sorted(int(n.split("#")[1]) for n in names)
    assert seqs == list(range(1, 3201))
