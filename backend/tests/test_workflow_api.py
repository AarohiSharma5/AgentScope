"""API tests for the v0.4 workflow / conversation / message endpoints."""
import pytest

from app.orchestration import AgentOrchestrator, WorkflowEngine
from app.services import trace_service


_SPEC = {
    "name": "seq-flow",
    "version": "1.0",
    "entry": "planner",
    "nodes": {
        "planner": {"type": "task", "role": "planner", "next": "reviewer"},
        "reviewer": {"type": "task", "role": "reviewer", "next": "done"},
        "done": {"type": "end"},
    },
}


@pytest.fixture()
def seeded(app):
    """Seed a workflow definition + conversation with agents, steps and messages."""
    with app.app_context():
        engine = WorkflowEngine()
        definition = engine.register(_SPEC, name="seq-flow", version="1.0")

        orch = AgentOrchestrator(
            conversation_name="c1", workflow_definition_id=definition.id
        )
        planner = orch.create_agent("Planner", role="planner")
        researcher = orch.create_agent("Researcher", role="researcher", parent=planner)
        planner.execute()
        researcher.execute()

        trace_service.create_agent_step(
            agent_run_id=planner.run.id, step_type="reasoning", name="think", cost=0.01
        )

        question = planner.ask(researcher, "What is LangSmith?")
        researcher.reply(question, "An observability platform.")
        planner.broadcast("kickoff")
        orch.finish()

        return {
            "definition_id": definition.id,
            "conversation_id": orch.conversation.id,
            "planner_node": planner.node.id,
            "researcher_node": researcher.node.id,
        }


# -- /api/workflows ---------------------------------------------------------


def test_list_workflows(client, seeded):
    body = client.get("/api/workflows").get_json()
    assert body["pagination"]["total"] == 1
    row = body["data"][0]
    assert row["workflow_name"] == "seq-flow"
    assert row["execution_count"] == 1


def test_list_workflows_search_and_bad_sort(client, seeded):
    assert client.get("/api/workflows?q=seq").get_json()["pagination"]["total"] == 1
    assert client.get("/api/workflows?q=nomatch").get_json()["pagination"]["total"] == 0
    assert client.get("/api/workflows?sort=bogus").status_code == 400
    assert client.get("/api/workflows?page=0").status_code == 400


def test_pagination_validation_is_consistent(client, seeded):
    """Shared parse_page_limit rejects bad page/limit uniformly across endpoints."""
    for path in ("/api/workflows", "/api/conversations", "/api/messages"):
        assert client.get(f"{path}?page=0").status_code == 400
        assert client.get(f"{path}?limit=0").status_code == 400
        assert client.get(f"{path}?limit=99999").status_code == 400
        assert client.get(f"{path}?page=notint").status_code == 400
        assert client.get(f"{path}?page=1&limit=5").status_code == 200


def test_workflow_detail(client, seeded):
    resp = client.get(f"/api/workflows/{seeded['definition_id']}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["entry"] == "planner"
    node_ids = {n["id"] for n in body["nodes"]}
    assert {"planner", "reviewer", "done"} == node_ids
    assert {"from": "planner", "to": "reviewer", "kind": "next"} in body["edges"]
    assert len(body["execution_history"]) == 1


def test_workflow_detail_404(client, seeded):
    assert client.get("/api/workflows/99999").status_code == 404


# -- /api/conversations -----------------------------------------------------


def test_list_conversations(client, seeded):
    body = client.get("/api/conversations").get_json()
    assert body["pagination"]["total"] == 1
    row = body["data"][0]
    assert row["agent_count"] == 2
    assert row["message_count"] == 3  # question + answer + 1 broadcast receiver
    assert row["status"] == "success"


def test_list_conversations_status_filter(client, seeded):
    assert client.get("/api/conversations?status=success").get_json()["pagination"]["total"] == 1
    assert client.get("/api/conversations?status=failed").get_json()["pagination"]["total"] == 0
    assert client.get("/api/conversations?status=bogus").status_code == 400


def test_conversation_detail(client, seeded):
    resp = client.get(f"/api/conversations/{seeded['conversation_id']}")
    assert resp.status_code == 200
    body = resp.get_json()

    # Agent tree: Planner root with Researcher child.
    assert len(body["agent_tree"]) == 1
    root = body["agent_tree"][0]
    assert root["name"] == "Planner"
    assert [c["name"] for c in root["children"]] == ["Researcher"]

    assert len(body["messages"]) == 3
    assert len(body["timeline"]) == 3
    # One step recorded on the planner run.
    assert len(body["steps"]) == 1
    assert body["steps"][0]["agent"] == "Planner"


def test_conversation_detail_404(client, seeded):
    assert client.get("/api/conversations/99999").status_code == 404


# -- /api/messages ----------------------------------------------------------


def test_list_messages_all(client, seeded):
    body = client.get("/api/messages").get_json()
    assert body["pagination"]["total"] == 3


def test_list_messages_filters(client, seeded):
    planner = seeded["planner_node"]
    researcher = seeded["researcher_node"]

    by_sender = client.get(f"/api/messages?sender={researcher}").get_json()
    assert by_sender["pagination"]["total"] == 1  # the reply
    assert by_sender["data"][0]["message_type"] == "answer"

    by_receiver = client.get(f"/api/messages?receiver={researcher}").get_json()
    assert by_receiver["pagination"]["total"] == 2  # question + broadcast

    by_type = client.get("/api/messages?message_type=question").get_json()
    assert by_type["pagination"]["total"] == 1

    by_text = client.get("/api/messages?q=langsmith").get_json()
    assert by_text["pagination"]["total"] == 1

    conv = seeded["conversation_id"]
    assert client.get(f"/api/messages?conversation={conv}").get_json()["pagination"]["total"] == 3


def test_list_messages_bad_input(client, seeded):
    assert client.get("/api/messages?message_type=gossip").status_code == 400
    assert client.get("/api/messages?sender=abc").status_code == 400


# -- /api/dashboard/workflow-metrics ---------------------------------------


def test_workflow_metrics(client, seeded):
    body = client.get("/api/dashboard/workflow-metrics").get_json()
    assert body["total_workflows"] == 1
    assert body["total_agents"] == 2
    assert body["average_agents_per_workflow"] == 2.0
    assert body["average_messages"] == 3.0
    assert body["success_rate"] == 100.0
    assert body["average_cost"] == pytest.approx(0.01)
    assert set(body) == {
        "total_workflows",
        "total_agents",
        "average_agents_per_workflow",
        "average_messages",
        "average_parallel_branches",
        "average_latency",
        "average_cost",
        "success_rate",
    }


def test_workflow_metrics_empty(client, app_ctx):
    body = client.get("/api/dashboard/workflow-metrics").get_json()
    assert body["total_workflows"] == 0
    assert body["success_rate"] == 0
