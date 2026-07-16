"""Tests for the v1.0 authentication & multi-tenancy subsystem.

Covers JWT encode/decode, password hashing, API-key hashing, the rate limiter,
role hierarchy and the full REST surface (register/login/refresh, org/member/
project/api-key isolation and RBAC, and audit logging).
"""
import time

import pytest

from app.auth import keys, tokens
from app.auth.rate_limit import RateLimiter, limiter, parse_rate
from app.auth.roles import Role, role_satisfies


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Rate limiter is a process-global singleton; isolate it per test."""
    limiter.reset()
    yield
    limiter.reset()


# -- unit: tokens -----------------------------------------------------------


def test_jwt_roundtrip_and_type():
    token = tokens.encode({"sub": 7}, "secret", expires_in=60, token_type="access")
    claims = tokens.decode(token, "secret", expected_type="access")
    assert claims["sub"] == 7
    assert "iat" in claims and "exp" in claims


def test_jwt_rejects_bad_signature():
    token = tokens.encode({"sub": 1}, "secret", expires_in=60)
    with pytest.raises(tokens.InvalidToken):
        tokens.decode(token, "different-secret")


def test_jwt_rejects_wrong_type():
    token = tokens.encode({"sub": 1}, "secret", expires_in=60, token_type="refresh")
    with pytest.raises(tokens.InvalidToken):
        tokens.decode(token, "secret", expected_type="access")


def test_jwt_expiry():
    token = tokens.encode({"sub": 1}, "secret", expires_in=-1)
    with pytest.raises(tokens.ExpiredToken):
        tokens.decode(token, "secret")


def test_jwt_rejects_alg_none(monkeypatch):
    """A token asking for alg=none (or any unsupported alg) is rejected (M12)."""
    import base64
    import json

    def seg(obj):
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    forged = f"{seg({'alg': 'none', 'typ': 'JWT'})}.{seg({'sub': 1, 'exp': 9999999999})}."
    with pytest.raises(tokens.InvalidToken):
        tokens.decode(forged, "secret")


def test_jwt_requires_exp(monkeypatch):
    """A token minted without exp cannot be replayed forever (M12)."""
    token = tokens.encode({"sub": 1}, "secret")  # no expires_in -> no exp claim
    with pytest.raises(tokens.InvalidToken):
        tokens.decode(token, "secret")
    # Opt-out is available for callers that intentionally allow non-expiring tokens.
    assert tokens.decode(token, "secret", require_exp=False)["sub"] == 1


def test_jwt_verifies_issuer():
    """When an issuer is expected it must be present and match (M12)."""
    token = tokens.encode({"sub": 1, "iss": "agentscope"}, "secret", expires_in=60)
    assert tokens.decode(token, "secret", issuer="agentscope")["sub"] == 1
    with pytest.raises(tokens.InvalidToken):
        tokens.decode(token, "secret", issuer="someone-else")
    other = tokens.encode({"sub": 1}, "secret", expires_in=60)  # no iss claim
    with pytest.raises(tokens.InvalidToken):
        tokens.decode(other, "secret", issuer="agentscope")


# -- unit: keys, roles, rate limit ------------------------------------------


def test_api_key_hash_and_verify():
    raw, prefix, hashed = keys.new_key("as")
    assert raw.startswith("as_")
    assert raw.startswith(prefix)
    assert keys.verify_key(raw, hashed)
    assert not keys.verify_key(raw + "x", hashed)


def test_role_hierarchy():
    assert role_satisfies(Role.ADMIN, Role.VIEWER)
    assert role_satisfies(Role.DEVELOPER, Role.DEVELOPER)
    assert not role_satisfies(Role.VIEWER, Role.DEVELOPER)


def test_rate_limiter_fixed_window():
    rl = RateLimiter()
    assert parse_rate("2/minute") == (2, 60)
    assert rl.hit("k", 2, 60)[0] is True
    assert rl.hit("k", 2, 60)[0] is True
    allowed, retry_after = rl.hit("k", 2, 60)
    assert allowed is False and retry_after >= 1


# -- helpers for API tests --------------------------------------------------


def _register(client, email="admin@acme.test", org="Acme", password="password123"):
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "Admin", "organization_name": org},
    )
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    return body


def _auth_header(tokens_obj):
    return {"Authorization": f"Bearer {tokens_obj['access_token']}"}


# -- API: register / login / refresh ----------------------------------------


def test_register_creates_user_org_and_admin(client):
    body = _register(client)
    assert body["user"]["email"] == "admin@acme.test"
    assert body["membership"]["role"] == Role.ADMIN
    assert "access_token" in body["tokens"] and "refresh_token" in body["tokens"]


def test_register_duplicate_email_rejected(client):
    _register(client)
    resp = client.post(
        "/api/auth/register",
        json={"email": "admin@acme.test", "password": "password123", "organization_name": "Other"},
    )
    assert resp.status_code == 400


def test_login_and_me(client):
    _register(client)
    resp = client.post("/api/auth/login", json={"email": "admin@acme.test", "password": "password123"})
    assert resp.status_code == 200
    tokens_obj = resp.get_json()["tokens"]

    me = client.get("/api/auth/me", headers=_auth_header(tokens_obj))
    assert me.status_code == 200
    assert me.get_json()["user"]["email"] == "admin@acme.test"
    assert len(me.get_json()["memberships"]) == 1


def test_login_wrong_password(client):
    _register(client)
    resp = client.post("/api/auth/login", json={"email": "admin@acme.test", "password": "nope"})
    assert resp.status_code == 401


def test_refresh_token(client):
    body = _register(client)
    resp = client.post("/api/auth/refresh", json={"refresh_token": body["tokens"]["refresh_token"]})
    assert resp.status_code == 200
    assert "access_token" in resp.get_json()["tokens"]


def test_refresh_token_is_single_use_and_rotates(client):
    """A refresh token works once; the old one is revoked after rotation (M11)."""
    body = _register(client)
    original = body["tokens"]["refresh_token"]

    first = client.post("/api/auth/refresh", json={"refresh_token": original})
    assert first.status_code == 200
    rotated = first.get_json()["tokens"]["refresh_token"]
    assert rotated != original

    # The rotated token is valid...
    assert client.post("/api/auth/refresh", json={"refresh_token": rotated}).status_code == 200
    # ...but replaying the original (already-rotated) token is rejected.
    assert client.post("/api/auth/refresh", json={"refresh_token": original}).status_code == 401


def test_refresh_token_reuse_revokes_whole_family(client):
    """Replaying a rotated token revokes the family, killing the live token (M11)."""
    body = _register(client)
    original = body["tokens"]["refresh_token"]

    rotated = client.post(
        "/api/auth/refresh", json={"refresh_token": original}
    ).get_json()["tokens"]["refresh_token"]

    # Replay the already-used original -> reuse detected -> family revoked.
    assert client.post("/api/auth/refresh", json={"refresh_token": original}).status_code == 401
    # The legitimately-rotated token is now revoked too, forcing a re-login.
    assert client.post("/api/auth/refresh", json={"refresh_token": rotated}).status_code == 401


def test_password_change_revokes_refresh_tokens(client):
    """Changing a password invalidates refresh tokens issued before it (M11)."""
    body = _register(client)
    refresh = body["tokens"]["refresh_token"]
    headers = _auth_header(body["tokens"])

    changed = client.post(
        "/api/auth/change-password",
        json={"current_password": "password123", "new_password": "newpassword123"},
        headers=headers,
    )
    assert changed.status_code == 200
    # The pre-reset refresh token no longer works.
    assert client.post("/api/auth/refresh", json={"refresh_token": refresh}).status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_access_token_query_param_fallback(client):
    """EventSource/SSE can't send headers, so an access_token query param works."""
    body = _register(client)
    access = body["tokens"]["access_token"]
    ok = client.get(f"/api/auth/me?access_token={access}")
    assert ok.status_code == 200
    assert ok.get_json()["user"]["email"] == "admin@acme.test"
    # A bogus query token is still rejected.
    assert client.get("/api/auth/me?access_token=garbage").status_code == 401


# -- API: RBAC & organization isolation -------------------------------------


def test_org_isolation_between_tenants(client):
    a = _register(client, email="a@a.test", org="Acme")
    b = _register(client, email="b@b.test", org="Beta")
    org_a = a["organization"]["id"]

    # Member of Beta cannot read Acme.
    resp = client.get(f"/api/organizations/{org_a}", headers=_auth_header(b["tokens"]))
    assert resp.status_code == 403

    # Admin of Acme can.
    resp = client.get(f"/api/organizations/{org_a}", headers=_auth_header(a["tokens"]))
    assert resp.status_code == 200


def test_viewer_cannot_manage_members(client):
    admin = _register(client, email="admin@acme.test", org="Acme")
    org_id = admin["organization"]["id"]
    # Create a viewer user in another org, then add to Acme as viewer.
    _register(client, email="viewer@acme.test", org="Personal")

    add = client.post(
        f"/api/organizations/{org_id}/members",
        json={"email": "viewer@acme.test", "role": Role.VIEWER},
        headers=_auth_header(admin["tokens"]),
    )
    assert add.status_code == 201

    viewer_login = client.post(
        "/api/auth/login", json={"email": "viewer@acme.test", "password": "password123"}
    ).get_json()["tokens"]

    # Viewer may read members but not add them.
    assert client.get(
        f"/api/organizations/{org_id}/members", headers={"Authorization": f"Bearer {viewer_login['access_token']}"}
    ).status_code == 200
    forbidden = client.post(
        f"/api/organizations/{org_id}/members",
        json={"email": "admin@acme.test", "role": Role.VIEWER},
        headers={"Authorization": f"Bearer {viewer_login['access_token']}"},
    )
    assert forbidden.status_code == 403


def test_cannot_grant_role_higher_than_own(client):
    admin = _register(client, email="admin@acme.test", org="Acme")
    org_id = admin["organization"]["id"]
    _register(client, email="dev@acme.test", org="DevHome")
    client.post(
        f"/api/organizations/{org_id}/members",
        json={"email": "dev@acme.test", "role": Role.DEVELOPER},
        headers=_auth_header(admin["tokens"]),
    )
    dev_tokens = client.post(
        "/api/auth/login", json={"email": "dev@acme.test", "password": "password123"}
    ).get_json()["tokens"]

    # A developer cannot create an admin API key (higher than own role).
    resp = client.post(
        f"/api/organizations/{org_id}/api-keys",
        json={"name": "k", "role": Role.ADMIN},
        headers=_auth_header(dev_tokens),
    )
    assert resp.status_code == 403


# -- API: projects & api keys -----------------------------------------------


def test_project_and_api_key_lifecycle(client):
    admin = _register(client)
    org_id = admin["organization"]["id"]
    headers = _auth_header(admin["tokens"])

    proj = client.post(
        f"/api/organizations/{org_id}/projects", json={"name": "Search"}, headers=headers
    )
    assert proj.status_code == 201
    project_id = proj.get_json()["id"]

    created = client.post(
        f"/api/organizations/{org_id}/api-keys",
        json={"name": "ci", "role": Role.DEVELOPER, "project_id": project_id},
        headers=headers,
    )
    assert created.status_code == 201
    raw = created.get_json()["key"]
    assert raw and raw.startswith("as_")

    # The key authenticates and is scoped to its organization.
    me = client.get("/api/auth/me", headers={"X-API-Key": raw})
    assert me.status_code == 200
    assert me.get_json()["identity"]["auth_type"] == "api_key"
    assert me.get_json()["identity"]["organization_id"] == org_id

    # Listing never leaks the secret.
    listed = client.get(f"/api/organizations/{org_id}/api-keys", headers=headers).get_json()
    assert all("key" not in k for k in listed["data"])

    # Revoke -> key stops working.
    key_id = created.get_json()["id"]
    assert client.delete(f"/api/organizations/{org_id}/api-keys/{key_id}", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers={"X-API-Key": raw}).status_code == 401


def test_api_key_cannot_cross_organizations(client):
    a = _register(client, email="a@a.test", org="Acme")
    b = _register(client, email="b@b.test", org="Beta")
    org_a, org_b = a["organization"]["id"], b["organization"]["id"]

    created = client.post(
        f"/api/organizations/{org_a}/api-keys",
        json={"name": "k", "role": Role.ADMIN},
        headers=_auth_header(a["tokens"]),
    )
    raw = created.get_json()["key"]

    # Acme's key cannot read Beta.
    resp = client.get(f"/api/organizations/{org_b}", headers={"X-API-Key": raw})
    assert resp.status_code == 403


# -- API key: last_used_at debounce (M1) ------------------------------------


def _make_api_key(client, role=Role.DEVELOPER, email="k@k.test", org="Keys"):
    admin = _register(client, email=email, org=org)
    org_id = admin["organization"]["id"]
    created = client.post(
        f"/api/organizations/{org_id}/api-keys",
        json={"name": "k", "role": role},
        headers=_auth_header(admin["tokens"]),
    )
    assert created.status_code == 201
    body = created.get_json()
    return body["key"], body["id"]


def test_should_flush_last_used_debounces_per_key():
    """The in-memory gate returns True at most once per window per key (M1)."""
    from datetime import timedelta

    from app.auth import context as ctx
    from app.utils.timeutils import utcnow

    ctx._last_used_flushed.clear()
    t0 = utcnow()
    # First observation flushes; an immediate repeat within the window does not.
    assert ctx._should_flush_last_used(4242, t0, 60) is True
    assert ctx._should_flush_last_used(4242, t0, 60) is False
    # Once the window elapses, it flushes again.
    assert ctx._should_flush_last_used(4242, t0 + timedelta(seconds=61), 60) is True
    # A different key is tracked independently.
    assert ctx._should_flush_last_used(9999, t0, 60) is True


def test_api_key_last_used_is_debounced(client, app):
    """Rapid repeat auth with one key rewrites last_used_at only once (M1)."""
    from app.auth import context as ctx
    from app.extensions import db
    from app.models.auth import ApiKey

    ctx._last_used_flushed.clear()
    raw, key_id = _make_api_key(client)

    assert client.get("/api/auth/me", headers={"X-API-Key": raw}).status_code == 200
    with app.app_context():
        first = db.session.get(ApiKey, key_id).last_used_at
    assert first is not None

    # A second call within the (default 60s) window must not rewrite the row.
    assert client.get("/api/auth/me", headers={"X-API-Key": raw}).status_code == 200
    with app.app_context():
        second = db.session.get(ApiKey, key_id).last_used_at
    assert second == first


def test_api_key_last_used_debounce_disabled(client, app):
    """A window of 0 restores exact write-on-every-request behavior (M1)."""
    from app.auth import context as ctx
    from app.extensions import db
    from app.models.auth import ApiKey

    ctx._last_used_flushed.clear()
    app.config["API_KEY_LAST_USED_DEBOUNCE_SECONDS"] = 0
    raw, key_id = _make_api_key(client, email="k2@k.test", org="Keys2")

    assert client.get("/api/auth/me", headers={"X-API-Key": raw}).status_code == 200
    with app.app_context():
        first = db.session.get(ApiKey, key_id).last_used_at

    time.sleep(0.01)
    assert client.get("/api/auth/me", headers={"X-API-Key": raw}).status_code == 200
    with app.app_context():
        second = db.session.get(ApiKey, key_id).last_used_at
    # Both calls wrote, so the timestamp advanced.
    assert first is not None and second is not None and second > first


# -- API: audit logs & rate limiting ----------------------------------------


def test_audit_logs_recorded_and_scoped(client):
    admin = _register(client)
    org_id = admin["organization"]["id"]
    resp = client.get(f"/api/organizations/{org_id}/audit-logs", headers=_auth_header(admin["tokens"]))
    assert resp.status_code == 200
    actions = {row["action"] for row in resp.get_json()["data"]}
    # Registration recorded the org creation under this org.
    assert "user.registered" in actions or "organization.created" in actions


def test_login_rate_limited(client):
    _register(client)
    # login limit is 10/minute; the 11th attempt should be throttled.
    last = None
    for _ in range(11):
        last = client.post("/api/auth/login", json={"email": "admin@acme.test", "password": "wrong"})
    assert last.status_code == 429
    assert last.headers.get("Retry-After") is not None
