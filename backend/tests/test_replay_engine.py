"""Tests for the v0.5 Replay Engine, service layer and comparison."""
import pytest

from app.models.agent_trace import AgentStatus
from app.orchestration import AgentOrchestrator, ReplayEngine, ReplayError
from app.services import replay_service, workflow_service

_SPEC = {
    "name": "replay-flow",
    "version": "1.0",
    "entry": "planner",
    "nodes": {
        "planner": {"type": "task", "role": "planner", "next": "researcher"},
        "researcher": {"type": "task", "role": "researcher", "next": "done"},
        "done": {"type": "end"},
    },
}


def _build_original() -> int:
    """Create a rich original conversation (prompt, steps, tool/memory/retriever)."""
    orch = AgentOrchestrator(
        conversation_name="orig",
        workflow_name="replay-flow",
        workflow_version="1.0",
        workflow_json=_SPEC,
    )
    planner = orch.create_agent("Planner", role="planner")
    researcher = orch.create_agent("Researcher", role="researcher", parent=planner)

    def planner_work():
        rec, run = orch.recorder, planner.run
        rec.record_prompt_assembly(
            run,
            system_prompt="You are a planner.",
            user_prompt="Plan the research.",
            memory_context="prior facts",
            retrieved_context="ctx",
        )
        step = rec.add_step(run, step_type="llm", name="LLM", input="Plan the research.")
        rec.record_tool(step, tool_name="search", arguments={"q": "x"}, result="found")
        rec.record_memory(step, memory_type="vector", query="x", retrieved_text="m", used=True)
        rt = rec.record_retriever(step, query="x", retrieved_documents=[{"id": "d1"}], num_documents=1)
        rec.record_retrieved_document(
            rt, document_id="d1", chunk_text="hello", similarity_score=0.9, selected=True
        )
        rec.finish_step(
            step, output="planned",
            token_usage={"input": 100, "output": 50, "total": 150}, cost=0.01,
        )
        return "planned"

    def researcher_work():
        rec, run = orch.recorder, researcher.run
        step = rec.add_step(run, step_type="llm", name="LLM", input="research")
        rec.finish_step(
            step, output="researched",
            token_usage={"input": 200, "output": 100, "total": 300}, cost=0.02,
        )
        return "researched"

    planner.execute(work=planner_work)
    researcher.execute(work=researcher_work)
    orch.finish()
    return orch.conversation.id


@pytest.fixture()
def original(app_ctx) -> int:
    return _build_original()


def _nodes(conversation_id: int) -> dict:
    """Return {role: node} for a conversation."""
    conv = workflow_service.get_conversation(conversation_id)
    return {n.agent_role: n for n in conv.nodes}


def _all_tools(conversation_id: int) -> list:
    conv = workflow_service.get_conversation(conversation_id)
    tools = []
    for node in conv.nodes:
        if node.agent_run:
            for step in node.agent_run.steps:
                tools.extend(step.tool_executions)
    return tools


# -- Snapshot reconstruction ------------------------------------------------


def test_snapshot_captures_workflow_prompt_and_subrecords(original):
    snap = replay_service.build_snapshot(original)
    assert snap["workflow_json"]["name"] == "replay-flow"
    assert snap["workflow_definition_id"] is not None
    assert [n["role"] for n in snap["nodes"]] == ["planner", "researcher"]
    planner = snap["nodes"][0]
    assert planner["prompt"]["system_prompt"] == "You are a planner."
    step = planner["steps"][0]
    assert step["tools"][0]["tool_name"] == "search"
    assert step["memory"][0]["used"] is True
    assert step["retrievers"][0]["documents"][0]["document_id"] == "d1"


def test_snapshot_missing_conversation_is_none(app_ctx):
    assert replay_service.build_snapshot(999999) is None


# -- Replay: same model -----------------------------------------------------


def test_replay_same_model_reuses_everything(original):
    engine = ReplayEngine()
    result = engine.replay(original)

    assert result.ok
    assert result.replay_conversation_run_id != original
    # Agent sequence + hierarchy preserved.
    nodes = _nodes(result.replay_conversation_run_id)
    assert set(nodes) == {"planner", "researcher"}
    assert nodes["researcher"].parent_node_id == nodes["planner"].id
    # Sub-records reused.
    planner_run = nodes["planner"].agent_run
    step = planner_run.steps[0]
    assert step.tool_executions[0].result == "found"
    assert step.memory_accesses[0].used is True
    assert step.retriever_traces[0].documents[0].document_id == "d1"
    assert planner_run.prompt_assembly.system_prompt == "You are a planner."


def test_replay_creates_and_stores_replay_run(original):
    engine = ReplayEngine()
    result = engine.replay(original)

    stored = replay_service.get_replay_run(result.replay_run.id)
    assert stored is not None
    assert stored.status == AgentStatus.SUCCESS
    assert stored.original_conversation_run_id == original
    assert stored.replay_metadata["replay_conversation_run_id"] == result.replay_conversation_run_id

    items, total = replay_service.list_replay_runs(original_conversation_run_id=original)
    assert total == 1 and items[0].id == stored.id


# -- Replay: different model / temperature ----------------------------------


def test_replay_different_model_reestimates_cost(original):
    engine = ReplayEngine()
    result = engine.replay(original, model="gpt-4o")

    assert result.replay_run.replayed_model == "gpt-4o"
    # gpt-4o: planner (100 in / 50 out) = 0.00075; researcher (200/100) = 0.0015.
    assert result.totals["cost"] == pytest.approx(0.00225)
    assert result.totals["cost"] != replay_service.conversation_totals(original)["cost"]


def test_replay_different_temperature_and_top_p_recorded(original):
    engine = ReplayEngine()
    result = engine.replay(original, model="gpt-4o", temperature=0.9, top_p=0.5)

    assert result.replay_run.temperature == 0.9
    assert result.replay_run.top_p == 0.5
    step = _nodes(result.replay_conversation_run_id)["planner"].agent_run.steps[0]
    assert step.step_metadata["temperature"] == 0.9
    assert step.step_metadata["top_p"] == 0.5
    assert step.step_metadata["replayed_model"] == "gpt-4o"


# -- Replay: different system prompt / memory / tools -----------------------


def test_replay_different_system_prompt(original):
    engine = ReplayEngine()
    result = engine.replay(original, system_prompt="NEW SYSTEM PROMPT")

    assert result.replay_run.system_prompt_override == "NEW SYSTEM PROMPT"
    planner_run = _nodes(result.replay_conversation_run_id)["planner"].agent_run
    assert planner_run.prompt_assembly.system_prompt == "NEW SYSTEM PROMPT"
    # Original is untouched.
    assert _nodes(original)["planner"].agent_run.prompt_assembly.system_prompt == "You are a planner."


def test_replay_different_memory(original):
    engine = ReplayEngine()
    result = engine.replay(original, memory=["fact one", "fact two"])

    planner_run = _nodes(result.replay_conversation_run_id)["planner"].agent_run
    assert planner_run.prompt_assembly.memory_context == "fact one\nfact two"


def test_replay_different_tools_mock(original):
    engine = ReplayEngine()
    result = engine.replay(original, tools={"search": "OVERRIDDEN RESULT"})

    tools = _all_tools(result.replay_conversation_run_id)
    assert any(t.result == "OVERRIDDEN RESULT" for t in tools)


def test_replay_live_tool_handler(original):
    engine = ReplayEngine()
    result = engine.replay(
        original,
        live=True,
        tool_handlers={"search": lambda args: {"hits": 3}},
    )

    tools = _all_tools(result.replay_conversation_run_id)
    assert any(t.result == '{"hits": 3}' for t in tools)


# -- Comparison -------------------------------------------------------------


def test_compare_generates_model_comparison(original):
    engine = ReplayEngine()
    result = engine.replay(original, model="gpt-4o")

    comparison = engine.compare(
        original, result, model_a="multi-agent", model_b="gpt-4o"
    )

    assert comparison.conversation_run_id == original
    assert comparison.model_a == "multi-agent" and comparison.model_b == "gpt-4o"
    # Original cost 0.03 vs replay 0.00225 -> positive diff -> replay (b) wins.
    assert comparison.cost_difference == pytest.approx(0.03 - 0.00225)
    assert comparison.token_difference == 0  # token usage reused
    assert comparison.winner == "gpt-4o"

    stored = replay_service.list_model_comparisons(conversation_run_id=original)
    assert len(stored) == 1 and stored[0].id == comparison.id


def test_compare_accepts_replay_run_object(original):
    engine = ReplayEngine()
    result = engine.replay(original, model="gpt-4o")
    # Passing the persisted ReplayRun (not the ReplayResult) also works.
    comparison = engine.compare(original, result.replay_run)
    assert comparison.cost_difference is not None


# -- Errors -----------------------------------------------------------------


def test_replay_nonexistent_conversation_raises(app_ctx):
    with pytest.raises(ReplayError):
        ReplayEngine().replay(999999)
