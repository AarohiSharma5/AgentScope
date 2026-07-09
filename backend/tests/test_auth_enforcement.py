"""Tests for global auth enforcement (AUTH_ENABLED) and the secret guard.

These verify the fixes for the production-readiness audit:

* ``AUTH_ENABLED`` actually protects data routes when on (and stays fully
  backward compatible when off), and
* the app refuses to boot with default/placeholder secrets while auth is on.

Also covers the bounded/validated pagination on ``GET /api/traces``.
"""
import pytest

from app import create_app
from app.config import Config
from app.extensions import db

_STRONG = "s" * 48


def _make_app(tmp_path, **overrides):
    class _C(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'auth-enforce.db'}"
        METRICS_CACHE_TTL = 0

    for key, value in overrides.items():
        setattr(_C, key, value)
    return create_app(_C)


def _register(client, email="admin@acme.test", org="Acme", password="password123"):
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "organization_name": org},
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["tokens"]["access_token"]


# -- Backward compatibility (auth off by default) ---------------------------


def test_data_routes_open_when_auth_disabled(client):
    """The default fixture app leaves AUTH_ENABLED off: data routes stay open."""
    assert client.get("/api/traces").status_code == 200
    assert client.get("/api/health").status_code == 200


# -- Secret guard -----------------------------------------------------------


def test_boot_rejected_with_default_secret_when_auth_enabled(tmp_path):
    with pytest.raises(RuntimeError):
        _make_app(tmp_path, AUTH_ENABLED=True)  # inherits default dev secret


def test_boot_ok_with_strong_secrets_when_auth_enabled(tmp_path):
    app = _make_app(
        tmp_path, AUTH_ENABLED=True, SECRET_KEY=_STRONG, JWT_SECRET=_STRONG
    )
    try:
        assert app.config["AUTH_ENABLED"] is True
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


# -- Enforcement when enabled ----------------------------------------------


def test_auth_enforced_on_data_routes(tmp_path):
    app = _make_app(
        tmp_path, AUTH_ENABLED=True, SECRET_KEY=_STRONG, JWT_SECRET=_STRONG
    )
    client = app.test_client()
    try:
        # Health + credential-issuing endpoints remain reachable.
        assert client.get("/api/health").status_code == 200

        # Data route rejected without credentials.
        assert client.get("/api/traces").status_code == 401

        # A registered user's access token unlocks the data route.
        token = _register(client)
        ok = client.get("/api/traces", headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200

        # Present-but-invalid credentials are rejected.
        bad = client.get(
            "/api/traces", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert bad.status_code == 401
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


# -- Bounded / validated pagination on GET /api/traces ---------------------


@pytest.mark.parametrize(
    "query,expected",
    [
        ("limit=0", 400),
        ("limit=100000", 400),
        ("limit=abc", 400),
        ("offset=-1", 400),
        ("limit=10&offset=0", 200),
        ("", 200),
    ],
)
def test_traces_pagination_is_bounded(client, query, expected):
    assert client.get(f"/api/traces?{query}").status_code == expected
