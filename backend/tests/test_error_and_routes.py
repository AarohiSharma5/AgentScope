"""Coverage for cross-cutting HTTP behavior that lacked tests:

* the global 404/405/500 error handlers all emit the shared ``{error}`` envelope;
* the background-jobs read endpoints (list / get / 404 / pagination);
* the many ingest validation branches in ``ingest_service`` reachable over HTTP.
"""
import time

import pytest


# -- Global error handlers --------------------------------------------------


def test_404_uses_standard_envelope(client):
    resp = client.get("/api/traces/999999")
    assert resp.status_code == 404
    assert "error" in resp.get_json()


def test_405_method_not_allowed_uses_standard_envelope(client):
    # /api/health is GET-only; a POST must yield a 405 in the shared envelope.
    resp = client.post("/api/health")
    assert resp.status_code == 405
    body = resp.get_json()
    assert body is not None and "error" in body


def test_500_internal_error_uses_standard_envelope(app):
    """An unexpected exception is caught by the catch-all handler, not leaked."""

    @app.route("/api/_boom")
    def _boom():
        raise RuntimeError("kaboom")

    resp = app.test_client().get("/api/_boom")
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"] == "internal server error"
    # The raw exception message must not leak to the client.
    assert "kaboom" not in resp.get_data(as_text=True)


# -- Background jobs read endpoints -----------------------------------------


def _await_job(manager, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job and job.status in ("succeeded", "failed"):
            return job
        time.sleep(0.01)
    pytest.fail("job did not finish in time")


def test_jobs_list_is_a_pagination_envelope(client):
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body) >= {"data", "pagination"}
    assert set(body["pagination"]) >= {"page", "limit", "total", "pages"}


def test_jobs_get_by_id_and_unknown_id(app):
    from app.jobs import job_manager

    client = app.test_client()
    job = job_manager.submit("noop", lambda: "ok")
    _await_job(job_manager, job.id)

    found = client.get(f"/api/jobs/{job.id}")
    assert found.status_code == 200
    payload = found.get_json()
    assert payload["id"] == job.id
    assert payload["status"] == "succeeded"
    assert payload["result"] == "ok"

    # The submitted job appears in the list too.
    listed = client.get("/api/jobs").get_json()["data"]
    assert any(j["id"] == job.id for j in listed)

    assert client.get("/api/jobs/no-such-job").status_code == 404


def test_jobs_pagination_bounds_are_validated(client):
    assert client.get("/api/jobs?limit=0").status_code == 400
    assert client.get("/api/jobs?page=-1").status_code == 400
    assert client.get("/api/jobs?page=1&limit=5").status_code == 200


# -- Ingest validation branches ---------------------------------------------


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({}, "agent_name is required"),
        ({"agent_name": "   "}, "agent_name is required"),
        ({"agent_name": "A", "status": "bogus"}, "invalid status"),
        ({"agent_name": "A", "steps": "nope"}, "steps must be a list"),
        ({"agent_name": "A", "parent_run_id": 999999}, "parent_run_id must reference"),
        ({"agent_name": "A", "request_id": "x"}, "request_id must be an integer"),
        ({"agent_name": "A", "request_id": 987654}, "does not reference an existing trace"),
        ({"agent_name": "A", "steps": ["nope"]}, "each step must be a JSON object"),
        (
            {"agent_name": "A", "steps": [{"tool_calls": [{}]}]},
            "each tool call needs a 'tool_name'",
        ),
        (
            {"agent_name": "A", "steps": [{"status": "bogus"}]},
            "invalid step status",
        ),
        (
            {"agent_name": "A", "steps": [{"latency_ms": "slow"}]},
            "step latency_ms must be a number",
        ),
        (
            {"agent_name": "A", "steps": [{"memory_accesses": "nope"}]},
            "memory_accesses must be a list",
        ),
        (
            {"agent_name": "A", "steps": [{"tool_calls": [{"tool_name": "t", "latency_ms": "x"}]}]},
            "tool latency_ms must be a number",
        ),
    ],
)
def test_agent_run_ingest_validation(client, payload, expected):
    resp = client.post("/api/agent-runs", json=payload)
    assert resp.status_code == 400, resp.get_data(as_text=True)
    assert expected in resp.get_json()["error"]


def test_agent_run_ingest_rejects_non_json_body(client):
    resp = client.post(
        "/api/agent-runs", data="not json", content_type="application/json"
    )
    assert resp.status_code == 400
    assert "valid JSON" in resp.get_json()["error"]


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"query": "q", "documents": "nope"}, "documents must be a list"),
        ({"query": "q", "documents": ["nope"]}, "each document must be a JSON object"),
        ({"query": "q", "retrieval_time_ms": "slow"}, "retrieval_time_ms must be a number"),
    ],
)
def test_retrieval_ingest_validation(client, payload, expected):
    resp = client.post("/api/retrievals", json=payload)
    assert resp.status_code == 400, resp.get_data(as_text=True)
    assert expected in resp.get_json()["error"]


def test_agent_run_ingest_happy_path_still_works(client):
    """A well-formed payload is accepted (guards against over-strict validation)."""
    resp = client.post(
        "/api/agent-runs",
        json={
            "agent_name": "Planner",
            "model_name": "gpt-4o",
            "steps": [{"step_type": "llm", "name": "gen", "output": "ok"}],
        },
    )
    assert resp.status_code == 201
    assert resp.get_json()["agent_name"] == "Planner"
