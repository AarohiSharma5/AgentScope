"""Tests for filtering/search on GET /api/traces and the facets endpoint."""
from datetime import timedelta
from urllib.parse import quote

from app.extensions import db
from app.models.trace import TraceStatus
from app.services import trace_service
from app.utils.timeutils import utcnow


def _mk(
    model,
    prompt,
    status=TraceStatus.SUCCESS,
    response=None,
    ago_hours=0,
    project=None,
    system_prompt=None,
):
    trace = trace_service.create_trace(
        {
            "model_name": model,
            "user_prompt": prompt,
            "final_response": response,
            "status": status,
            "project": project,
            "system_prompt": system_prompt,
        }
    )
    if ago_hours:
        trace.timestamp = utcnow() - timedelta(hours=ago_hours)
        db.session.commit()
    return trace


def _seed(app):
    with app.app_context():
        _mk("gpt-4o", "summarize the invoice", ago_hours=1, project="billing-bot")
        _mk(
            "gpt-4o",
            "translate to french",
            status=TraceStatus.FAILED,
            ago_hours=48,
            project="billing-bot",
        )
        _mk("claude-3-haiku", "write a poem about invoices", ago_hours=3, project="content-gen")
        # Untagged (no project) trace grouped by its system prompt instead.
        _mk(
            "gpt-4o-mini",
            "classify sentiment",
            response="totally positive",
            ago_hours=5,
            system_prompt="You are a sentiment classifier.",
        )


def test_filter_by_model(app, client):
    _seed(app)
    res = client.get("/api/traces?model=gpt-4o").get_json()
    assert res["pagination"]["total"] == 2
    assert all(t["model_name"] == "gpt-4o" for t in res["data"])


def test_filter_by_status(app, client):
    _seed(app)
    res = client.get("/api/traces?status=failed").get_json()
    assert res["pagination"]["total"] == 1
    assert res["data"][0]["status"] == "failed"


def test_invalid_status_is_rejected(app, client):
    _seed(app)
    resp = client.get("/api/traces?status=bogus")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_search_matches_prompt_and_response(app, client):
    _seed(app)
    # "invoice" appears in a user_prompt and a different trace's prompt.
    res = client.get("/api/traces?q=invoice").get_json()
    prompts = [t["user_prompt"] for t in res["data"]]
    assert res["pagination"]["total"] == 2
    assert all("invoice" in p for p in prompts)

    # Match on final_response only.
    res = client.get("/api/traces?q=positive").get_json()
    assert res["pagination"]["total"] == 1
    assert res["data"][0]["model_name"] == "gpt-4o-mini"


def test_since_until_window(app, client):
    _seed(app)
    since = quote((utcnow() - timedelta(hours=4)).isoformat())
    res = client.get(f"/api/traces?since={since}").get_json()
    # Only the 1h and 3h old traces fall inside the last 4 hours.
    assert res["pagination"]["total"] == 2


def test_invalid_datetime_is_rejected(app, client):
    resp = client.get("/api/traces?since=not-a-date")
    assert resp.status_code == 400


def test_sort_oldest_first(app, client):
    _seed(app)
    res = client.get("/api/traces?sort=timestamp").get_json()
    times = [t["timestamp"] for t in res["data"]]
    assert times == sorted(times)


def test_combined_filters(app, client):
    _seed(app)
    res = client.get("/api/traces?model=gpt-4o&status=success&q=invoice").get_json()
    assert res["pagination"]["total"] == 1
    assert res["data"][0]["user_prompt"] == "summarize the invoice"


def test_facets_lists_distinct_models(app, client):
    _seed(app)
    facets = client.get("/api/traces/facets").get_json()
    assert set(facets["models"]) == {"gpt-4o", "gpt-4o-mini", "claude-3-haiku"}
    assert facets["statuses"] == ["failed", "success"]


def test_filter_by_project(app, client):
    _seed(app)
    res = client.get("/api/traces?project=billing-bot").get_json()
    assert res["pagination"]["total"] == 2
    assert all(t["project"] == "billing-bot" for t in res["data"])


def test_filter_by_system_prompt_for_untagged(app, client):
    _seed(app)
    res = client.get(
        "/api/traces?system_prompt=" + quote("You are a sentiment classifier.")
    ).get_json()
    assert res["pagination"]["total"] == 1
    assert res["data"][0]["project"] is None
    assert res["data"][0]["model_name"] == "gpt-4o-mini"


def test_facets_areas_split_project_and_system_prompt(app, client):
    _seed(app)
    areas = client.get("/api/traces/facets").get_json()["areas"]
    projects = {a["value"]: a for a in areas if a["type"] == "project"}
    prompts = [a for a in areas if a["type"] == "system_prompt"]

    assert projects["billing-bot"]["count"] == 2
    assert projects["content-gen"]["count"] == 1
    # The untagged trace shows up as a system-prompt area, not a project.
    assert any(a["value"] == "You are a sentiment classifier." for a in prompts)
    # Busiest area first.
    assert areas[0]["value"] == "billing-bot"
