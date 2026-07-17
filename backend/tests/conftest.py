"""Shared pytest fixtures.

By default each test runs against an isolated, file-backed SQLite database in a
temporary directory, so tests are hermetic and never touch a real dev database
while exercising the exact same models and SQL.

Set ``TEST_DATABASE_URL`` (e.g. a PostgreSQL DSN) to run the suite against a
real server instead — the CI Postgres job uses this to exercise dialect,
cascade and pooling behavior. Each test drops and recreates the schema so runs
stay isolated on the shared database.
"""
import os

import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.services import trace_service
from app.utils.cache import clear_cache

_TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture()
def app(tmp_path):
    """A fresh Flask app bound to a throwaway database (SQLite, or TEST_DATABASE_URL)."""

    db_uri = _TEST_DATABASE_URL or f"sqlite:///{tmp_path / 'test.db'}"

    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = db_uri
        # Disable the metrics cache so assertions on freshly written data are
        # deterministic (production keeps the default short TTL).
        METRICS_CACHE_TTL = 0

    clear_cache()
    # On a shared server DB, start each test from a clean schema.
    if _TEST_DATABASE_URL:
        _reset_schema(TestConfig)
    app = create_app(TestConfig)
    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()
    clear_cache()


def _reset_schema(config_class) -> None:
    """Drop any leftover schema before a test when using a shared server DB."""
    reset_app = create_app(config_class)
    with reset_app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Isolate the process-wide rate limiter between tests.

    The limiter is a process singleton; now that ingest/chat/import routes are
    rate limited too, its counters would otherwise bleed across tests. Reset
    around every test so limits are per-test and deterministic.
    """
    from app.auth.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


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
