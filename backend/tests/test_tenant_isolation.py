"""Tenant isolation (phase 1): traces and conversations are scoped per org.

Verifies the audit fix that observability data written by an org-bound API key
is stamped with that organization and only visible to callers in the same org,
while remaining fully backward compatible when auth is disabled.
"""
import pytest

from app import create_app
from app.auth import Identity, set_identity
from app.config import Config
from app.extensions import db
from app.models.agent_trace import AgentStatus
from app.services import (
    auth_service,
    evaluation_service,
    trace_service,
    workflow_service,
)

_STRONG = "s" * 48


@pytest.fixture()
def tenant_app(tmp_path):
    class _C(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'tenant.db'}"
        METRICS_CACHE_TTL = 0
        AUTH_ENABLED = True
        SECRET_KEY = _STRONG
        JWT_SECRET = _STRONG

    app = create_app(_C)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _org_key(app, email, org_name):
    """Create an organization + an API key in it, returning the raw key."""
    with app.app_context():
        user = auth_service.create_user(email=email, password="password123")
        org, _ = auth_service.create_organization(org_name, user)
        _, raw = auth_service.create_api_key(
            org_id=org.id, name="ingest", role="admin", actor_role="admin"
        )
        return raw


def test_traces_are_isolated_per_organization(tenant_app):
    key_a = _org_key(tenant_app, "a@acme.test", "Acme")
    key_b = _org_key(tenant_app, "b@beta.test", "Beta")
    client = tenant_app.test_client()

    # Each org ingests one trace with its own API key.
    ra = client.post("/api/traces", json={"model_name": "gpt-4o", "user_prompt": "A"},
                     headers={"X-API-Key": key_a})
    rb = client.post("/api/traces", json={"model_name": "gpt-4o", "user_prompt": "B"},
                     headers={"X-API-Key": key_b})
    assert ra.status_code == 201 and rb.status_code == 201
    id_a, id_b = ra.get_json()["id"], rb.get_json()["id"]

    # Org A lists only its own trace...
    list_a = client.get("/api/traces", headers={"X-API-Key": key_a}).get_json()["data"]
    ids_a = {t["id"] for t in list_a}
    assert id_a in ids_a and id_b not in ids_a

    # ...and cannot read org B's trace by id (hidden -> 404).
    assert client.get(f"/api/traces/{id_b}", headers={"X-API-Key": key_a}).status_code == 404
    assert client.get(f"/api/traces/{id_a}", headers={"X-API-Key": key_a}).status_code == 200

    # Stats are scoped too (org A sees exactly its own request count).
    stats_a = client.get("/api/stats", headers={"X-API-Key": key_a}).get_json()
    assert stats_a["total_requests"] == 1


def test_traces_unscoped_when_auth_disabled(client):
    """With auth off (default fixture), no org stamping/scoping occurs."""
    r = client.post("/api/traces", json={"model_name": "gpt-4o"})
    assert r.status_code == 201
    assert r.get_json()["organization_id"] is None
    # All traces remain visible without credentials.
    assert client.get("/api/traces").status_code == 200


# -- Phase 2: child resource types ------------------------------------------


def _agent_run_payload(agent_name):
    return {
        "agent_name": agent_name,
        "user_prompt": "hi",
        "model_name": "gpt-4o",
        "steps": [{"step_type": "llm", "name": "gen", "output": "ok"}],
    }


def test_agent_runs_isolated_per_organization(tenant_app):
    key_a = _org_key(tenant_app, "a@acme.test", "Acme")
    key_b = _org_key(tenant_app, "b@beta.test", "Beta")
    client = tenant_app.test_client()

    ra = client.post("/api/agent-runs", json=_agent_run_payload("Planner-A"),
                     headers={"X-API-Key": key_a})
    rb = client.post("/api/agent-runs", json=_agent_run_payload("Planner-B"),
                     headers={"X-API-Key": key_b})
    assert ra.status_code == 201 and rb.status_code == 201
    id_a, id_b = ra.get_json()["id"], rb.get_json()["id"]

    # Org A lists only its own run...
    list_a = client.get("/api/agent-runs", headers={"X-API-Key": key_a}).get_json()["data"]
    ids_a = {r["id"] for r in list_a}
    assert id_a in ids_a and id_b not in ids_a

    # ...and cannot read org B's run by id (hidden -> 404).
    assert client.get(f"/api/agent-runs/{id_b}", headers={"X-API-Key": key_a}).status_code == 404
    assert client.get(f"/api/agent-runs/{id_a}", headers={"X-API-Key": key_a}).status_code == 200

    # Agent metrics are scoped too (org A counts exactly its own run).
    metrics_a = client.get("/api/dashboard/agent-metrics", headers={"X-API-Key": key_a}).get_json()
    assert metrics_a["total_agent_runs"] == 1


def test_retrievals_isolated_per_organization(tenant_app):
    key_a = _org_key(tenant_app, "a@acme.test", "Acme")
    key_b = _org_key(tenant_app, "b@beta.test", "Beta")
    client = tenant_app.test_client()

    ra = client.post("/api/retrievals", json={"query": "alpha", "documents": [{"chunk_text": "x"}]},
                     headers={"X-API-Key": key_a})
    rb = client.post("/api/retrievals", json={"query": "beta", "documents": [{"chunk_text": "y"}]},
                     headers={"X-API-Key": key_b})
    assert ra.status_code == 201 and rb.status_code == 201
    id_a, id_b = ra.get_json()["id"], rb.get_json()["id"]

    list_a = client.get("/api/retrievals", headers={"X-API-Key": key_a}).get_json()["data"]
    ids_a = {r["id"] for r in list_a}
    assert id_a in ids_a and id_b not in ids_a
    assert client.get(f"/api/retrievals/{id_b}", headers={"X-API-Key": key_a}).status_code == 404

    # RAG metrics are scoped (org A sees exactly its own retrieval).
    metrics_a = client.get("/api/dashboard/rag-metrics", headers={"X-API-Key": key_a}).get_json()
    assert metrics_a["total_retrievals"] == 1


# -- Phase 2: conversations, evaluations and workflow definitions -----------
#
# These resources have no plain REST "create" endpoint (conversations come from
# the multi-agent SDK, evaluations from the engine), so we seed them through the
# service layer inside a request context whose identity carries the target org —
# exercising the exact same organization stamping the live code uses — then
# assert the HTTP list/detail endpoints scope by tenant.


def _org_id_for(app, email):
    with app.app_context():
        user = auth_service.get_user_by_email(email)
        return auth_service.list_user_organizations(user)[0].id


def _seed_org_resources(app, org_id):
    """Create a trace, conversation and evaluation owned by ``org_id``."""
    with app.test_request_context():
        set_identity(
            Identity(auth_type="api_key", api_key_id=None, organization_id=org_id, role="admin")
        )
        trace = trace_service.create_trace({"model_name": "gpt-4o", "user_prompt": "seed"})
        conversation = workflow_service.create_conversation_run(
            trace.id, conversation_name=f"conv-{org_id}"
        )
        workflow = workflow_service.create_workflow_definition(
            workflow_name=f"wf-{org_id}", version="1"
        )
        evaluation = evaluation_service.create_evaluation_run(
            conversation.id, evaluation_type="rule_based", status=AgentStatus.SUCCESS
        )
        db.session.commit()
        return {
            "conversation": conversation.id,
            "workflow": workflow.id,
            "evaluation": evaluation.id,
        }


def test_conversations_isolated_per_organization(tenant_app):
    key_a = _org_key(tenant_app, "a@acme.test", "Acme")
    key_b = _org_key(tenant_app, "b@beta.test", "Beta")
    a = _seed_org_resources(tenant_app, _org_id_for(tenant_app, "a@acme.test"))
    b = _seed_org_resources(tenant_app, _org_id_for(tenant_app, "b@beta.test"))
    client = tenant_app.test_client()

    ids_a = {c["id"] for c in client.get("/api/conversations", headers={"X-API-Key": key_a}).get_json()["data"]}
    assert a["conversation"] in ids_a and b["conversation"] not in ids_a

    # Detail of another org's conversation is hidden (404).
    assert client.get(f"/api/conversations/{b['conversation']}", headers={"X-API-Key": key_a}).status_code == 404
    assert client.get(f"/api/conversations/{a['conversation']}", headers={"X-API-Key": key_a}).status_code == 200

    # Workflow metrics count only the caller's own conversations.
    metrics_a = client.get("/api/dashboard/workflow-metrics", headers={"X-API-Key": key_a}).get_json()
    assert metrics_a["total_workflows"] == 1


def test_workflow_definitions_isolated_per_organization(tenant_app):
    key_a = _org_key(tenant_app, "a@acme.test", "Acme")
    key_b = _org_key(tenant_app, "b@beta.test", "Beta")
    a = _seed_org_resources(tenant_app, _org_id_for(tenant_app, "a@acme.test"))
    b = _seed_org_resources(tenant_app, _org_id_for(tenant_app, "b@beta.test"))
    client = tenant_app.test_client()

    ids_a = {w["id"] for w in client.get("/api/workflows", headers={"X-API-Key": key_a}).get_json()["data"]}
    assert a["workflow"] in ids_a and b["workflow"] not in ids_a
    assert client.get(f"/api/workflows/{b['workflow']}", headers={"X-API-Key": key_a}).status_code == 404


def test_evaluations_isolated_per_organization(tenant_app):
    key_a = _org_key(tenant_app, "a@acme.test", "Acme")
    key_b = _org_key(tenant_app, "b@beta.test", "Beta")
    a = _seed_org_resources(tenant_app, _org_id_for(tenant_app, "a@acme.test"))
    b = _seed_org_resources(tenant_app, _org_id_for(tenant_app, "b@beta.test"))
    client = tenant_app.test_client()

    ids_a = {e["id"] for e in client.get("/api/evaluations", headers={"X-API-Key": key_a}).get_json()["data"]}
    assert a["evaluation"] in ids_a and b["evaluation"] not in ids_a

    assert client.get(f"/api/evaluations/{b['evaluation']}", headers={"X-API-Key": key_a}).status_code == 404
    assert client.get(f"/api/evaluations/{a['evaluation']}", headers={"X-API-Key": key_a}).status_code == 200

    # Evaluation metrics are scoped to the caller's org.
    metrics_a = client.get("/api/dashboard/evaluation-metrics", headers={"X-API-Key": key_a}).get_json()
    assert metrics_a["total_evaluations"] == 1


# -- Phase 2: JWT (dashboard user) tenant scoping ---------------------------


def _register(client, email, org, password="password123"):
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "organization_name": org},
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def test_jwt_single_membership_is_auto_scoped(tenant_app):
    """A JWT user in exactly one org is scoped to it with no header needed."""
    client = tenant_app.test_client()
    token = _register(client, "owner@acme.test", "Acme")["tokens"]["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    # Writing as the JWT user stamps their sole org.
    own = client.post("/api/traces", json={"model_name": "gpt-4o", "user_prompt": "own"}, headers=auth)
    assert own.status_code == 201
    assert own.get_json()["organization_id"] is not None
    own_id = own.get_json()["id"]

    # A different org's trace, via that org's own API key.
    key_b = _org_key(tenant_app, "b@beta.test", "Beta")
    id_b = client.post("/api/traces", json={"model_name": "gpt-4o", "user_prompt": "B"},
                       headers={"X-API-Key": key_b}).get_json()["id"]

    ids = {t["id"] for t in client.get("/api/traces", headers=auth).get_json()["data"]}
    assert own_id in ids and id_b not in ids


def test_jwt_multi_org_requires_active_org_selection(tenant_app):
    """A JWT user in several orgs sees nothing until they select one via header."""
    client = tenant_app.test_client()
    token = _register(client, "multi@acme.test", "Acme")["tokens"]["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    with tenant_app.app_context():
        user = auth_service.get_user_by_email("multi@acme.test")
        acme_id = auth_service.list_user_organizations(user)[0].id
        other = auth_service.create_user(email="beta-owner@beta.test", password="password123")
        beta, _ = auth_service.create_organization("Beta", other)
        auth_service.add_member(beta.id, email="multi@acme.test", role="admin", actor_role="admin")
        beta_id = beta.id

    # Seed one trace in each org, selecting the active org per write.
    client.post("/api/traces", json={"model_name": "gpt-4o", "user_prompt": "acme"},
                headers={**auth, "X-Organization-Id": str(acme_id)})
    client.post("/api/traces", json={"model_name": "gpt-4o", "user_prompt": "beta"},
                headers={**auth, "X-Organization-Id": str(beta_id)})

    # No active org selected -> deny-by-default (nothing), not every org's data.
    assert client.get("/api/traces", headers=auth).get_json()["data"] == []

    # With a header, scoped to that org only.
    acme_list = client.get(
        "/api/traces", headers={**auth, "X-Organization-Id": str(acme_id)}
    ).get_json()["data"]
    assert [t["user_prompt"] for t in acme_list] == ["acme"]

    # A header for an org the user does not belong to -> 403.
    assert client.get("/api/traces", headers={**auth, "X-Organization-Id": "99999"}).status_code == 403


def test_jwt_user_cannot_read_another_orgs_resource(tenant_app):
    """C1/C2: a JWT dashboard user cannot read another org's data by id, nor by
    forging an X-Organization-Id header for an org they don't belong to."""
    client = tenant_app.test_client()
    token = _register(client, "owner@acme.test", "Acme")["tokens"]["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    # The Acme user writes their own trace (auto-scoped to their sole org)...
    own_id = client.post(
        "/api/traces", json={"model_name": "gpt-4o", "user_prompt": "own"}, headers=auth
    ).get_json()["id"]

    # ...and Beta writes one via Beta's own API key.
    key_b = _org_key(tenant_app, "b@beta.test", "Beta")
    beta_id = client.post(
        "/api/traces", json={"model_name": "gpt-4o", "user_prompt": "beta"},
        headers={"X-API-Key": key_b},
    ).get_json()["id"]
    beta_org_id = _org_id_for(tenant_app, "b@beta.test")

    # The Acme user can read their own resource, but Beta's is hidden (404, not 403,
    # so existence isn't leaked cross-tenant).
    assert client.get(f"/api/traces/{own_id}", headers=auth).status_code == 200
    assert client.get(f"/api/traces/{beta_id}", headers=auth).status_code == 404

    # Forging Beta's org id (the user is not a member) is rejected outright (403),
    # so they can't pivot into Beta's tenant to read beta_id either.
    forged = {**auth, "X-Organization-Id": str(beta_org_id)}
    assert client.get("/api/traces", headers=forged).status_code == 403
    assert client.get(f"/api/traces/{beta_id}", headers=forged).status_code == 403


def test_cached_metrics_are_keyed_per_tenant(tmp_path):
    """With caching ENABLED, one org's cached metrics never bleed into another's.

    Guards C3: the per-org metric caches key on organization_id, so warming
    org A's entry must not serve A's totals to org B within the TTL window.
    """
    from app.utils.cache import clear_cache

    class _C(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'cache.db'}"
        METRICS_CACHE_TTL = 30  # caching ON (the tenant_app fixture disables it)
        AUTH_ENABLED = True
        SECRET_KEY = _STRONG
        JWT_SECRET = _STRONG

    app = create_app(_C)
    clear_cache()
    try:
        key_a = _org_key(app, "a@acme.test", "Acme")
        key_b = _org_key(app, "b@beta.test", "Beta")
        client = app.test_client()

        # Org A: one agent run; org B: two.
        client.post("/api/agent-runs", json=_agent_run_payload("A1"), headers={"X-API-Key": key_a})
        client.post("/api/agent-runs", json=_agent_run_payload("B1"), headers={"X-API-Key": key_b})
        client.post("/api/agent-runs", json=_agent_run_payload("B2"), headers={"X-API-Key": key_b})

        # Warm A's cache entry first; B must compute its own, not reuse A's.
        a = client.get("/api/dashboard/agent-metrics", headers={"X-API-Key": key_a}).get_json()
        b = client.get("/api/dashboard/agent-metrics", headers={"X-API-Key": key_b}).get_json()
        assert a["total_agent_runs"] == 1
        assert b["total_agent_runs"] == 2
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()
        clear_cache()


def test_live_stream_events_are_tenant_scoped(tenant_app):
    """Guards C4: an org's writes emit events tagged with that org, and a stream
    only fans out its own tenant's events (never another org's)."""
    from app.streaming import EventType
    from app.streaming.manager import live_trace_manager

    key_a = _org_key(tenant_app, "a@acme.test", "Acme")
    with tenant_app.app_context():
        user_a = auth_service.get_user_by_email("a@acme.test")
        org_a_id = auth_service.list_user_organizations(user_a)[0].id

    live_trace_manager.reset()
    # One watcher scoped to org A, one scoped to a different org.
    watcher_a = live_trace_manager.subscribe(org_scope=org_a_id, heartbeat_interval=0.1)
    watcher_other = live_trace_manager.subscribe(org_scope=org_a_id + 999, heartbeat_interval=0.1)
    try:
        client = tenant_app.test_client()
        resp = client.post(
            "/api/traces",
            json={"model_name": "gpt-4o", "user_prompt": "A"},
            headers={"X-API-Key": key_a},
        )
        assert resp.status_code == 201

        # Org A's watcher receives the event, tagged with org A.
        event = next(watcher_a.stream())
        assert event.type == EventType.TRACE_STARTED
        assert event.organization_id == org_a_id

        # A watcher for a different org gets nothing but a heartbeat.
        assert next(watcher_other.stream()).type == EventType.HEARTBEAT
    finally:
        live_trace_manager.reset()
