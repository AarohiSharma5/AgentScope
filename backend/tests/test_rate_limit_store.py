"""A4: shared (cross-worker) rate-limit store.

The limiter delegates to a pluggable store; with ``RATE_LIMIT_STORAGE_URL`` set
it uses a Redis-backed fixed window so the configured limit holds across every
worker instead of being multiplied by the worker count. These tests exercise the
Redis store's counting/TTL semantics with a fake client (no live Redis needed)
and verify graceful fallback when Redis is unavailable.
"""
import types

import pytest

from app.auth.rate_limit import (
    InMemoryWindowStore,
    RateLimiter,
    RedisWindowStore,
    configure_from_app,
    limiter,
)


class _FakePipeline:
    """Records queued commands and replays them in order on ``execute`` — like
    a redis-py transactional pipeline (INCR + TTL executed atomically)."""

    def __init__(self, redis):
        self._redis = redis
        self._ops = []

    def incr(self, key, amount=1):
        self._ops.append(("incr", (key, amount)))
        return self

    def ttl(self, key):
        self._ops.append(("ttl", (key,)))
        return self

    def execute(self):
        return [getattr(self._redis, op)(*args) for op, args in self._ops]


class FakeRedis:
    """Minimal in-memory Redis stand-in with a controllable clock."""

    def __init__(self):
        self._counts = {}
        self._expiry = {}  # key -> absolute expiry time
        self.now = 1000.0

    def _maybe_expire(self, key):
        exp = self._expiry.get(key)
        if exp is not None and self.now >= exp:
            self._counts.pop(key, None)
            self._expiry.pop(key, None)

    def incr(self, key, amount=1):
        self._maybe_expire(key)
        self._counts[key] = self._counts.get(key, 0) + amount
        return self._counts[key]

    def ttl(self, key):
        self._maybe_expire(key)
        if key not in self._counts:
            return -2  # no such key
        exp = self._expiry.get(key)
        if exp is None:
            return -1  # exists but no expiry set yet
        return int(exp - self.now)

    def expire(self, key, window):
        if key in self._counts:
            self._expiry[key] = self.now + window
            return True
        return False

    def pipeline(self):
        return _FakePipeline(self)


def test_redis_window_store_enforces_limit_and_reports_reset():
    store = RedisWindowStore(FakeRedis())
    rl = RateLimiter(store=store)

    assert rl.hit("bucket", limit=2, window=60)[0] is True
    assert rl.hit("bucket", limit=2, window=60)[0] is True
    allowed, retry_after = rl.hit("bucket", limit=2, window=60)
    assert allowed is False
    assert 1 <= retry_after <= 60  # window's remaining seconds


def test_redis_window_store_sets_ttl_on_first_hit_only():
    fake = FakeRedis()
    store = RedisWindowStore(fake)

    store.incr("k", 60)  # first hit sets the window
    fake.now += 10  # 10s elapse
    _, reset_after = store.incr("k", 60)  # same window; expiry NOT extended
    assert reset_after == pytest.approx(50, abs=1)


def test_redis_window_store_resets_after_window_expires():
    fake = FakeRedis()
    store = RedisWindowStore(fake)
    rl = RateLimiter(store=store)

    assert rl.hit("k", limit=1, window=60)[0] is True
    assert rl.hit("k", limit=1, window=60)[0] is False  # limited within the window
    fake.now += 61  # window elapses
    assert rl.hit("k", limit=1, window=60)[0] is True  # counter reset -> allowed


def test_redis_window_store_is_shared_across_limiters():
    """Two limiters (modelling two workers) over one store share the window."""
    fake = FakeRedis()
    worker_a = RateLimiter(store=RedisWindowStore(fake))
    worker_b = RateLimiter(store=RedisWindowStore(fake))

    assert worker_a.hit("k", limit=2, window=60)[0] is True
    assert worker_b.hit("k", limit=2, window=60)[0] is True
    # The third hit — on either worker — trips the shared limit.
    assert worker_a.hit("k", limit=2, window=60)[0] is False


def test_configure_from_app_uses_redis_when_available(monkeypatch):
    fake = FakeRedis()
    fake.ping = lambda: True  # configure_from_app pings before switching
    fake_redis_module = types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda url: fake)
    )
    monkeypatch.setitem(__import__("sys").modules, "redis", fake_redis_module)

    original = limiter._store
    try:
        app = types.SimpleNamespace(config={"RATE_LIMIT_STORAGE_URL": "redis://x:6379/0"})
        configure_from_app(app)
        assert isinstance(limiter._store, RedisWindowStore)
    finally:
        limiter.use_store(original)


def test_configure_from_app_falls_back_when_redis_unavailable(monkeypatch):
    def _boom(url):
        raise ConnectionError("no redis here")

    fake_redis_module = types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=_boom)
    )
    monkeypatch.setitem(__import__("sys").modules, "redis", fake_redis_module)

    original = limiter._store
    try:
        limiter.use_store(InMemoryWindowStore())
        app = types.SimpleNamespace(config={"RATE_LIMIT_STORAGE_URL": "redis://down:6379/0"})
        configure_from_app(app)  # must not raise
        assert isinstance(limiter._store, InMemoryWindowStore)  # unchanged
    finally:
        limiter.use_store(original)


def test_configure_from_app_noop_without_url():
    original = limiter._store
    try:
        configure_from_app(types.SimpleNamespace(config={"RATE_LIMIT_STORAGE_URL": None}))
        assert limiter._store is original  # nothing swapped
    finally:
        limiter.use_store(original)
