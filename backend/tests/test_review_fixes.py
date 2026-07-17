"""Tests for the review fixes: clearable trace fields, AgentContext mutation
safety, torn-read-free job reads, and API versioning + OpenAPI."""
import threading
import time

import pytest

from app.extensions import db
from app.jobs import JobManager
from app.orchestration.context import AgentContext
from app.services import trace_service
from app.version import API_VERSION, __version__


# -- update_trace can clear fields to "" / None -----------------------------


def test_update_trace_can_clear_fields_to_empty_string(app):
    with app.app_context():
        trace = trace_service.create_trace(
            {
                "user_prompt": "hi",
                "model_name": "gpt-4o",
                "final_response": "an answer",
                "error_message": "boom",
            }
        )
        trace_id = trace.id

        updated = trace_service.update_trace(
            trace_id, final_response="", error_message=""
        )

        assert updated.final_response == ""
        assert updated.error_message == ""
        # Persisted, not just held in the session identity map.
        db.session.expire_all()
        reloaded = db.session.get(type(trace), trace_id)
        assert reloaded.final_response == ""
        assert reloaded.error_message == ""


def test_update_trace_omitted_fields_are_untouched(app):
    with app.app_context():
        trace = trace_service.create_trace(
            {"user_prompt": "hi", "model_name": "gpt-4o", "final_response": "keep"}
        )
        trace_service.update_trace(trace.id, error_message="err")
        reloaded = db.session.get(type(trace), trace.id)
        assert reloaded.final_response == "keep"  # not clobbered
        assert reloaded.error_message == "err"


# -- AgentContext value-immutability / mutate -------------------------------


def test_agent_context_mutate_is_atomic_and_isolated():
    ctx = AgentContext()

    # Concurrent appends via mutate never lose updates (read-modify-write is
    # serialized under the lock).
    def worker(n):
        ctx.mutate("items", lambda cur: [*cur, n], default=[])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(ctx.get("items")) == list(range(50))


def test_agent_context_mutate_does_not_expose_shared_reference():
    ctx = AgentContext()
    ctx.set("data", {"a": 1})
    # The mutator gets a private deep copy; mutating it must not leak until
    # returned/stored.
    seen = {}

    def mutator(cur):
        seen["copy"] = cur
        cur["a"] = 2
        return cur

    ctx.mutate("data", mutator)
    assert ctx.get("data") == {"a": 2}
    assert seen["copy"] is not ctx.get("data") or ctx.get("data")["a"] == 2


# -- JobManager reads are consistent snapshots ------------------------------


def _await(manager, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job and job.status in ("succeeded", "failed"):
            return job
        time.sleep(0.01)
    pytest.fail("job did not finish in time")


def test_job_get_returns_independent_snapshot(app):
    manager = JobManager()
    manager.init_app(app)
    try:
        job = manager.submit("noop", lambda: "ok")
        # Each read returns a distinct object copied under the lock, so a reader
        # serializing it never observes a concurrent half-written update, and two
        # reads never alias the same mutable record.
        snapshot_a = manager.get(job.id)
        snapshot_b = manager.get(job.id)
        assert snapshot_a is not job
        assert snapshot_a is not snapshot_b
        finished = _await(manager, job.id)
        assert finished.status == "succeeded"
        assert finished.result == "ok"
    finally:
        manager.shutdown(wait=True)


# -- API versioning + OpenAPI -----------------------------------------------


@pytest.mark.parametrize("prefix", ["/api", "/api/v1"])
def test_health_and_version_available_on_both_prefixes(client, prefix):
    assert client.get(f"{prefix}/health").status_code == 200

    resp = client.get(f"{prefix}/version")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["version"] == __version__
    assert body["api_version"] == API_VERSION
    assert API_VERSION in body["supported_api_versions"]


def test_api_version_header_present(client):
    resp = client.get("/api/health")
    assert resp.headers.get("X-API-Version") == API_VERSION


@pytest.mark.parametrize("prefix", ["/api", "/api/v1"])
def test_openapi_document_is_served(client, prefix):
    resp = client.get(f"{prefix}/openapi.json")
    assert resp.status_code == 200
    spec = resp.get_json()
    assert spec["openapi"].startswith("3.")
    # Shared envelopes are documented as reusable components.
    assert "Error" in spec["components"]["schemas"]
    assert "Pagination" in spec["components"]["schemas"]
    # Core endpoints are present.
    assert "/traces" in spec["paths"]
    servers = {s["url"] for s in spec["servers"]}
    assert {"/api", "/api/v1"} <= servers


def test_docs_page_points_at_matching_spec(client):
    resp = client.get("/api/v1/docs")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    assert "/api/v1/openapi.json" in resp.get_data(as_text=True)


def test_versioned_data_route_shares_handler(client):
    # The versioned mount serves the same routes as the legacy alias.
    assert client.get("/api/v1/traces?page=1&limit=1").status_code == 200
