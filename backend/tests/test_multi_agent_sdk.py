"""Tests for the v0.4 Multi-Agent SDK (app.orchestration)."""
import pytest

from app.models.agent_trace import AgentRun, AgentStatus
from app.models.workflow_trace import AgentMessage, AgentNode, ConversationRun
from app.orchestration import (
    Agent,
    AgentContext,
    AgentOrchestrator,
    AgentRegistry,
)


def test_public_api_flow_persists_conversation(app_ctx):
    """The documented public API runs end-to-end and persists everything."""
    orchestrator = AgentOrchestrator(conversation_name="research task")

    planner = orchestrator.create_agent(name="Planner", role="planner")
    researcher = orchestrator.create_agent(name="Researcher", role="researcher")

    planner.send(researcher, message="Research LangSmith.")
    planner.execute()
    researcher.execute()

    conversation = orchestrator.finish()

    # Conversation persisted and finished with a latency + success status.
    assert conversation.status == AgentStatus.SUCCESS
    assert conversation.latency_ms is not None
    assert conversation.finished_at is not None

    # Two nodes, both finished, each linked to a real agent-run trace.
    nodes = AgentNode.query.order_by(AgentNode.execution_order).all()
    assert [n.display_name for n in nodes] == ["Planner", "Researcher"]
    assert all(n.status == AgentStatus.SUCCESS for n in nodes)
    assert all(n.agent_run_id is not None for n in nodes)
    assert AgentRun.query.count() == 2

    # The message was persisted between the two nodes.
    message = AgentMessage.query.one()
    assert message.content == "Research LangSmith."
    assert message.sender_node_id == planner.node.id
    assert message.receiver_node_id == researcher.node.id


def test_execute_runs_work_and_records_latency(app_ctx):
    orchestrator = AgentOrchestrator()
    agent = orchestrator.create_agent(name="Worker", role="worker")

    result = agent.execute(work=lambda: 21 * 2)

    assert result == 42
    assert agent.run is not None
    assert agent.run.status == AgentStatus.SUCCESS
    assert agent.run.latency_ms is not None
    assert agent.node.status == AgentStatus.SUCCESS
    orchestrator.finish()


def test_execute_failure_marks_failed_and_reraises(app_ctx):
    orchestrator = AgentOrchestrator()
    agent = orchestrator.create_agent(name="Boom", role="worker")

    def boom():
        raise ValueError("kaboom")

    with pytest.raises(ValueError, match="kaboom"):
        agent.execute(work=boom)

    assert agent.run.status == AgentStatus.FAILED
    assert agent.node.status == AgentStatus.FAILED
    assert "kaboom" in (agent.run.run_metadata or {}).get("error", "")
    orchestrator.finish(status=AgentStatus.FAILED)


def test_nested_parent_child_agents(app_ctx):
    orchestrator = AgentOrchestrator()
    parent = orchestrator.create_agent(name="Lead", role="planner")
    child = orchestrator.create_agent(name="Sub", role="worker", parent=parent)

    parent.execute()
    child.execute()

    # Node tree.
    assert child.node.parent_node_id == parent.node.id
    assert child.node in parent.node.children

    # Trace nesting: child run's parent is the parent's run.
    assert child.run.parent_run_id == parent.run.id
    orchestrator.finish()


def test_parallel_execution_shared_group_and_results(app_ctx):
    orchestrator = AgentOrchestrator()
    a = orchestrator.create_agent(name="A", role="worker")
    b = orchestrator.create_agent(name="B", role="worker")

    results = orchestrator.run_parallel(
        [(a, lambda: "ra"), (b, lambda: "rb")]
    )

    assert results == {"A": "ra", "B": "rb"}
    assert a.node.parallel_group == b.node.parallel_group
    assert a.node.parallel_group is not None
    assert a.node.status == AgentStatus.SUCCESS
    assert b.run.latency_ms is not None
    orchestrator.finish()


def test_parallel_execution_propagates_first_error(app_ctx):
    orchestrator = AgentOrchestrator()
    ok = orchestrator.create_agent(name="Ok", role="worker")
    bad = orchestrator.create_agent(name="Bad", role="worker")

    def boom():
        raise RuntimeError("parallel fail")

    with pytest.raises(RuntimeError, match="parallel fail"):
        orchestrator.run_parallel([(ok, lambda: 1), (bad, boom)])

    # Both runs are still recorded; the failing one is marked failed.
    assert ok.node.status == AgentStatus.SUCCESS
    assert bad.node.status == AgentStatus.FAILED
    orchestrator.finish(status=AgentStatus.FAILED)


def test_parallel_execution_caps_concurrency(app_ctx):
    """A wide fan-out never runs more branches at once than the config cap (H5).

    Guards against the unbounded ``max_workers=len(branches)`` that could spawn a
    thread + DB connection per branch and exhaust the pool. Extra branches queue
    and run as slots free up, so all still complete.
    """
    import threading
    import time

    from flask import current_app

    current_app.config["WORKFLOW_MAX_PARALLELISM"] = 3

    orchestrator = AgentOrchestrator()
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def make_work():
        def work():
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.02)  # hold the slot so overlap is observable
            with lock:
                state["active"] -= 1
            return "ok"

        return work

    tasks = [
        (orchestrator.create_agent(name=f"W{i}", role="worker"), make_work())
        for i in range(12)
    ]

    results = orchestrator.run_parallel(tasks)

    # All 12 branches ran and produced their result...
    assert len(results) == 12
    assert all(v == "ok" for v in results.values())
    # ...but never more than the cap of 3 were in flight simultaneously.
    assert 1 <= state["peak"] <= 3
    orchestrator.finish()


def test_shared_context_is_the_same_across_agents(app_ctx):
    orchestrator = AgentOrchestrator(context={"topic": "LangSmith"})
    a = orchestrator.create_agent(name="A")
    b = orchestrator.create_agent(name="B")

    a.context.set("findings", ["fact-1"])
    assert b.context.get("findings") == ["fact-1"]
    assert b.context.get("topic") == "LangSmith"
    assert a.context is b.context is orchestrator.context
    orchestrator.finish()


def test_registry_lookup_and_uniqueness(app_ctx):
    orchestrator = AgentOrchestrator()
    planner = orchestrator.create_agent(name="Planner")

    assert orchestrator.get_agent("Planner") is planner
    assert "Planner" in orchestrator.registry
    assert len(orchestrator.registry) == 1

    with pytest.raises(ValueError):
        orchestrator.create_agent(name="Planner")
    orchestrator.finish()


def test_optional_workflow_definition_and_execution(app_ctx):
    orchestrator = AgentOrchestrator(
        workflow_name="research-flow",
        workflow_version="1.0",
        workflow_json={"nodes": ["planner", "researcher"]},
    )
    orchestrator.create_agent(name="Planner")
    orchestrator.finish()

    assert orchestrator.definition is not None
    assert orchestrator.execution is not None
    assert orchestrator.execution.status == AgentStatus.SUCCESS
    assert orchestrator.execution.latency_ms is not None
    # One-to-one link back to the conversation.
    assert orchestrator.execution.conversation_run_id == orchestrator.conversation.id


def test_finish_is_idempotent(app_ctx):
    orchestrator = AgentOrchestrator()
    first = orchestrator.finish()
    second = orchestrator.finish()
    assert first is second


def test_context_and_registry_units():
    ctx = AgentContext({"a": 1})
    ctx.set("b", 2)
    ctx.update({"c": 3}, d=4)
    assert ctx.all() == {"a": 1, "b": 2, "c": 3, "d": 4}
    assert ctx["a"] == 1
    assert "b" in ctx and len(ctx) == 4

    registry = AgentRegistry()
    assert registry.get("nope") is None
    assert len(registry) == 0
