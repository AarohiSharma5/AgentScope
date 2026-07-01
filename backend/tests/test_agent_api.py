"""API tests for the v0.2 agent-tracing and chat endpoints."""


def _seed_run(client, prompt="hello"):
    """Create one traced agent run via the chat flow; return the JSON body."""
    res = client.post("/api/chat", json={"user_prompt": prompt, "model_name": "gpt-4o"})
    assert res.status_code == 201
    return res.get_json()


def test_chat_endpoint_requires_prompt(client):
    res = client.post("/api/chat", json={})
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_chat_endpoint_returns_response_and_ids(client):
    body = _seed_run(client, "What is AgentScope?")
    assert body["status"] == "success"
    assert body["response"]
    assert isinstance(body["request_id"], int)
    assert isinstance(body["agent_run_id"], int)


def test_list_agent_runs_envelope_and_pagination(client):
    _seed_run(client)
    _seed_run(client)

    res = client.get("/api/agent-runs?page=1&limit=1")
    assert res.status_code == 200
    body = res.get_json()
    assert set(body.keys()) == {"data", "pagination"}
    assert set(body["pagination"].keys()) == {"page", "limit", "total", "pages"}
    assert body["pagination"]["total"] == 2
    assert body["pagination"]["pages"] == 2
    assert len(body["data"]) == 1


def test_list_agent_runs_validates_params(client):
    assert client.get("/api/agent-runs?limit=99999").status_code == 400
    assert client.get("/api/agent-runs?page=0").status_code == 400
    assert client.get("/api/agent-runs?status=bogus").status_code == 400

    bad_sort = client.get("/api/agent-runs?sort=nope")
    assert bad_sort.status_code == 400
    assert "allowed" in bad_sort.get_json()["details"]


def test_get_agent_run_detail_and_404(client):
    body = _seed_run(client)
    detail = client.get(f"/api/agent-runs/{body['agent_run_id']}").get_json()
    for key in ("steps", "tool_executions", "memory_accesses", "retriever_traces", "timeline"):
        assert key in detail
    assert [s["step_type"] for s in detail["steps"]][0] == "planner"

    missing = client.get("/api/agent-runs/424242")
    assert missing.status_code == 404
    assert missing.get_json() == {"error": "agent run not found"}


def test_runs_for_request_consistent_envelope_and_404(client):
    body = _seed_run(client)
    ok = client.get(f"/api/requests/{body['request_id']}/agent-runs")
    assert ok.status_code == 200
    assert set(ok.get_json().keys()) == {"data", "pagination"}

    missing = client.get("/api/requests/999999/agent-runs")
    assert missing.status_code == 404


def test_agent_metrics_shape(client):
    _seed_run(client)
    metrics = client.get("/api/dashboard/agent-metrics").get_json()
    expected = {
        "total_agent_runs",
        "average_latency",
        "average_steps",
        "average_tool_calls",
        "average_memory_calls",
        "average_retrievals",
        "average_cost",
        "success_rate",
    }
    assert expected.issubset(metrics.keys())
    assert metrics["total_agent_runs"] == 1


def test_search_matches_agent_name(client):
    _seed_run(client)
    res = client.get("/api/agent-runs?q=Chatbot")
    assert res.get_json()["pagination"]["total"] == 1
    empty = client.get("/api/agent-runs?q=zzz-no-match")
    assert empty.get_json()["pagination"]["total"] == 0


def test_unknown_route_returns_json_error(client):
    res = client.get("/api/nope")
    assert res.status_code == 404
    assert "error" in res.get_json()
    assert res.content_type.startswith("application/json")
