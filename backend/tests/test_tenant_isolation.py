"""Tenant isolation (phase 1): traces and conversations are scoped per org.

Verifies the audit fix that observability data written by an org-bound API key
is stamped with that organization and only visible to callers in the same org,
while remaining fully backward compatible when auth is disabled.
"""
import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.services import auth_service

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
    list_a = client.get("/api/traces", headers={"X-API-Key": key_a}).get_json()
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
