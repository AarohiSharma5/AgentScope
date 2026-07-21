"""DEMO_MODE: a public, read-only showcase instance.

Writes/ingest/OTLP/login are rejected with 403 while every read path keeps
working, and ``/version`` advertises the demo flag so the UI can show a banner.
"""
import pytest

from app import create_app
from app.config import Config
from app.extensions import db


@pytest.fixture()
def demo_client(tmp_path):
    class DemoConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'demo.db'}"
        DEMO_MODE = True
        DEMO_RESET_ON_BOOT = False

    app = create_app(DemoConfig)
    yield app.test_client()
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_reads_are_allowed(demo_client):
    assert demo_client.get("/api/health").status_code == 200
    assert demo_client.get("/api/traces").status_code == 200


def test_version_advertises_demo_flag(demo_client):
    body = demo_client.get("/api/version").get_json()
    assert body["demo"] is True


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/traces"),              # ingest a request trace
        ("post", "/api/otel/v1/traces"),      # OTLP ingest
        ("post", "/api/auth/login"),          # credential issuance
        ("delete", "/api/traces/1"),          # mutation
    ],
)
def test_all_writes_are_rejected(demo_client, method, path):
    resp = getattr(demo_client, method)(path, json={})
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "read_only_demo"


def test_non_api_paths_are_not_gated(demo_client):
    # The read-only guard only governs /api/*; a non-API POST isn't a 403 from it
    # (it 404s because no such route exists), proving the guard is scoped.
    assert demo_client.post("/not-api").status_code == 404
