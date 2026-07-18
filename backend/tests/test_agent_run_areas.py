"""Tests for application/area segmentation on GET /api/agent-runs."""
from urllib.parse import quote

from app.extensions import db
from app.models.agent_trace import AgentRun, AgentStatus
from app.services import trace_service


def _run(project=None, system_prompt=None, agent_name="Assistant", status=AgentStatus.SUCCESS):
    """Create a parent trace (carrying the area) and an agent run under it."""
    trace = trace_service.create_trace(
        {"model_name": "gpt-4o", "project": project, "system_prompt": system_prompt}
    )
    run = AgentRun(
        request_id=trace.id,
        agent_name=agent_name,
        status=status,
        organization_id=trace.organization_id,
    )
    db.session.add(run)
    db.session.commit()
    return run


def _seed(app):
    with app.app_context():
        _run(project="billing-bot", system_prompt="You are a billing agent.")
        _run(project="billing-bot", system_prompt="You are a billing agent.")
        _run(project="code-assistant", system_prompt="You are a senior engineer.")
        # Untagged run: grouped by its parent trace's system prompt.
        _run(system_prompt="You are a sentiment classifier.")


def test_agent_runs_filter_by_project(app, client):
    _seed(app)
    res = client.get("/api/agent-runs?project=billing-bot").get_json()
    assert res["pagination"]["total"] == 2
    assert all(r["project"] == "billing-bot" for r in res["data"])
    # The inherited system prompt is exposed on each run row.
    assert all(r["system_prompt"] == "You are a billing agent." for r in res["data"])


def test_agent_runs_filter_by_system_prompt_untagged(app, client):
    _seed(app)
    res = client.get(
        "/api/agent-runs?system_prompt=" + quote("You are a sentiment classifier.")
    ).get_json()
    assert res["pagination"]["total"] == 1
    assert res["data"][0]["project"] is None


def test_agent_run_facets_group_by_application(app, client):
    _seed(app)
    facets = client.get("/api/agent-runs/facets").get_json()
    areas = facets["areas"]
    projects = {a["value"]: a for a in areas if a["type"] == "project"}
    assert projects["billing-bot"]["count"] == 2
    assert projects["billing-bot"]["system_prompt"] == "You are a billing agent."
    assert projects["code-assistant"]["count"] == 1
    # Untagged run surfaces as a system-prompt area, and the busiest area is first.
    assert any(
        a["type"] == "system_prompt" and a["value"] == "You are a sentiment classifier."
        for a in areas
    )
    assert areas[0]["value"] == "billing-bot"
    # Statuses are offered as the secondary refinement.
    assert set(facets["statuses"]) == set(AgentStatus.ALL)


def test_agent_runs_area_and_status_compose(app, client):
    with app.app_context():
        _run(project="billing-bot", status=AgentStatus.SUCCESS)
        _run(project="billing-bot", status=AgentStatus.FAILED)
    res = client.get("/api/agent-runs?project=billing-bot&status=failed").get_json()
    assert res["pagination"]["total"] == 1
    assert res["data"][0]["status"] == "failed"
