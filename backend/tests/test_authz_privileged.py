"""Authorization on privileged, instance-level endpoints (audit fix H2).

Plugin lifecycle, background-job inspection and bundle import/export are not
scoped to a URL organization, so they must require an administrative principal
when auth is enforced (``@require_admin``). They also remain fully open when
auth is disabled (backward-compatible single-user dev). Imports are additionally
size-capped.
"""
import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.services import auth_service

_STRONG = "s" * 48


@pytest.fixture()
def auth_app(tmp_path):
    class _C(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'authz.db'}"
        METRICS_CACHE_TTL = 0
        AUTH_ENABLED = True
        SECRET_KEY = _STRONG
        JWT_SECRET = _STRONG
        RATE_LIMIT_ENABLED = False  # keep the size/authz assertions deterministic

    app = create_app(_C)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _key(app, email, org_name, role="admin"):
    """Create an org + an API key with ``role``, returning the raw key."""
    with app.app_context():
        user = auth_service.create_user(email=email, password="password123")
        org, _ = auth_service.create_organization(org_name, user)
        _, raw = auth_service.create_api_key(
            org_id=org.id, name="k", role=role, actor_role="admin"
        )
        return raw


# -- Plugin lifecycle -------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/plugins/demo/enable"),
        ("post", "/api/plugins/demo/disable"),
        ("post", "/api/plugins/demo/reload"),
        ("delete", "/api/plugins/demo"),
    ],
)
def test_plugin_lifecycle_forbidden_for_non_admin(auth_app, method, path):
    viewer = _key(auth_app, "v@acme.test", "Acme", role="viewer")
    client = auth_app.test_client()
    resp = getattr(client, method)(path, headers={"X-API-Key": viewer})
    assert resp.status_code == 403


def test_plugin_read_is_allowed_for_any_principal(auth_app):
    viewer = _key(auth_app, "v@acme.test", "Acme", role="viewer")
    client = auth_app.test_client()
    # Discovery is not privileged: a viewer can list plugins.
    assert client.get("/api/plugins", headers={"X-API-Key": viewer}).status_code == 200


def test_admin_passes_authz_on_plugin_lifecycle(auth_app):
    admin = _key(auth_app, "a@acme.test", "Acme", role="admin")
    client = auth_app.test_client()
    # Admin clears authorization; an unknown plugin then 404s (not 403).
    resp = client.post("/api/plugins/does-not-exist/enable", headers={"X-API-Key": admin})
    assert resp.status_code == 404


# -- Background jobs --------------------------------------------------------


def test_jobs_require_admin(auth_app):
    viewer = _key(auth_app, "v@acme.test", "Acme", role="viewer")
    admin = _key(auth_app, "a@acme.test", "Acme2", role="admin")
    client = auth_app.test_client()
    assert client.get("/api/jobs", headers={"X-API-Key": viewer}).status_code == 403
    assert client.get("/api/jobs", headers={"X-API-Key": admin}).status_code == 200


# -- Export / import --------------------------------------------------------


def test_export_and_import_forbidden_for_non_admin(auth_app):
    viewer = _key(auth_app, "v@acme.test", "Acme", role="viewer")
    client = auth_app.test_client()
    assert client.get("/api/export/analytics", headers={"X-API-Key": viewer}).status_code == 403
    assert client.post("/api/import", data=b"{}", headers={"X-API-Key": viewer}).status_code == 403
    assert (
        client.post("/api/import/replay", data=b"{}", headers={"X-API-Key": viewer}).status_code
        == 403
    )


def test_admin_can_export_analytics(auth_app):
    admin = _key(auth_app, "a@acme.test", "Acme", role="admin")
    client = auth_app.test_client()
    resp = client.get("/api/export/analytics", headers={"X-API-Key": admin})
    assert resp.status_code == 200


def test_export_is_scoped_to_caller_org(auth_app):
    """An admin of org A cannot export a conversation owned by org B (404)."""
    from app.models.agent_trace import AgentStatus
    from app.models.trace import Trace
    from app.models.workflow_trace import ConversationRun

    key_a = _key(auth_app, "a@acme.test", "Acme", role="admin")
    with auth_app.app_context():
        owner_b = auth_service.create_user(email="b@beta.test", password="password123")
        org_b, _ = auth_service.create_organization("Beta", owner_b)
        trace = Trace(model_name="gpt-4o", organization_id=org_b.id)
        db.session.add(trace)
        db.session.commit()
        conv = ConversationRun(
            request_trace_id=trace.id,
            conversation_name="secret",
            status=AgentStatus.SUCCESS,
            organization_id=org_b.id,
        )
        db.session.add(conv)
        db.session.commit()
        conv_id = conv.id

    client = auth_app.test_client()
    resp = client.get(f"/api/export/conversation/{conv_id}", headers={"X-API-Key": key_a})
    assert resp.status_code == 404


def test_import_body_size_is_capped(tmp_path):
    class _C(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'authz-size.db'}"
        METRICS_CACHE_TTL = 0
        AUTH_ENABLED = True
        SECRET_KEY = _STRONG
        JWT_SECRET = _STRONG
        RATE_LIMIT_ENABLED = False
        MAX_IMPORT_BYTES = 64  # tiny cap for the test

    app = create_app(_C)
    try:
        admin = _key(app, "a@acme.test", "Acme", role="admin")
        client = app.test_client()
        oversized = b"x" * 128
        resp = client.post("/api/import", data=oversized, headers={"X-API-Key": admin})
        assert resp.status_code == 413
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


# -- Backward compatibility (auth off) --------------------------------------


def test_privileged_routes_open_when_auth_disabled(client):
    """The default fixture leaves AUTH off: privileged routes stay reachable."""
    assert client.get("/api/jobs").status_code == 200
    assert client.get("/api/plugins").status_code == 200
    # Import still validates its body (empty -> 400), just without an authz gate.
    assert client.post("/api/import", data=b"").status_code == 400
