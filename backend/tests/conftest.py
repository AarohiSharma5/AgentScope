"""Shared pytest fixtures.

Each test runs against an isolated, file-backed SQLite database created in a
temporary directory, so tests are hermetic and never touch a real Postgres /
dev database while still exercising the exact same models and SQL.
"""
import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.services import trace_service
from app.utils.cache import clear_cache


@pytest.fixture()
def app(tmp_path):
    """A fresh Flask app bound to a throwaway SQLite database."""

    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        # Disable the metrics cache so assertions on freshly written data are
        # deterministic (production keeps the default short TTL).
        METRICS_CACHE_TTL = 0

    clear_cache()
    app = create_app(TestConfig)
    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()
    clear_cache()


@pytest.fixture()
def client(app):
    """Flask test client for API-level tests."""
    return app.test_client()


@pytest.fixture()
def app_ctx(app):
    """Push an application context for tests that touch the ORM/SDK directly."""
    with app.app_context():
        yield


@pytest.fixture()
def request_trace(app_ctx):
    """Create and return a parent request Trace for agent-run tests."""
    return trace_service.create_trace(
        {"user_prompt": "hello", "model_name": "gpt-4o"}
    )
