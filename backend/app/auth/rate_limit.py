"""A small, thread-safe, fixed-window rate limiter with a pluggable store.

The default store is **in-process**: simple and dependency-free, but each worker
keeps its own window, so under *N* gunicorn workers the effective limit is *N×*
the configured value. For a shared limit across workers/hosts, set
``RATE_LIMIT_STORAGE_URL`` to a Redis URL and the limiter transparently switches
to a Redis-backed store (see :func:`configure_from_app`); the counting logic and
the :func:`rate_limited` decorator are unchanged. The limiter is disabled
globally via the ``RATE_LIMIT_ENABLED`` config flag.
"""
import logging
import threading
import time
from functools import wraps
from typing import Callable, Optional, Tuple

from flask import current_app, g, request

from .errors import RateLimitError

logger = logging.getLogger("agentscope")

_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def parse_rate(spec: str) -> Tuple[int, int]:
    """Parse a rate spec like ``"100/minute"`` into ``(limit, window_seconds)``."""
    try:
        count, unit = spec.split("/")
        unit = unit.rstrip("s")  # allow "minute" or "minutes"
        return int(count), _UNITS[unit]
    except (ValueError, KeyError):
        raise ValueError(f"invalid rate limit spec: {spec!r}")


class InMemoryWindowStore:
    """Per-process fixed-window counters. Not shared across workers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: dict[str, Tuple[float, int]] = {}

    def incr(self, key: str, window: int) -> Tuple[int, int]:
        """Increment ``key``'s window counter; return ``(count, reset_after)``."""
        now = time.time()
        with self._lock:
            start, count = self._windows.get(key, (now, 0))
            if now - start >= window:
                start, count = now, 0
            count += 1
            self._windows[key] = (start, count)
            return count, max(1, int(window - (now - start)))

    def clear(self) -> None:
        with self._lock:
            self._windows.clear()


class RedisWindowStore:
    """Shared fixed-window counters in Redis (atomic INCR + EXPIRE).

    A single window is one Redis key with a TTL; the first hit in a window sets
    the expiry, so counts reset automatically. Because the counter is shared, the
    configured limit is enforced across every worker and host.
    """

    def __init__(self, client, prefix: str = "asrl:") -> None:
        self._redis = client
        self._prefix = prefix

    def incr(self, key: str, window: int) -> Tuple[int, int]:
        redis_key = self._prefix + key
        pipe = self._redis.pipeline()
        pipe.incr(redis_key, 1)
        pipe.ttl(redis_key)
        count, ttl = pipe.execute()
        if ttl is None or ttl < 0:  # first hit (or no expiry yet): set the window
            self._redis.expire(redis_key, window)
            ttl = window
        return int(count), max(1, int(ttl))

    def clear(self) -> None:  # pragma: no cover - not used against a shared store
        pass


class RateLimiter:
    """Fixed-window counter over a pluggable :class:`store`."""

    def __init__(self, store=None) -> None:
        self._store = store or InMemoryWindowStore()

    def use_store(self, store) -> None:
        """Swap the backing store (e.g. to Redis once app config is known)."""
        self._store = store

    def hit(self, key: str, limit: int, window: int) -> Tuple[bool, int]:
        """Register a hit. Returns ``(allowed, retry_after_seconds)``."""
        count, reset_after = self._store.incr(key, window)
        if count > limit:
            return False, reset_after
        return True, 0

    def reset(self) -> None:
        clear = getattr(self._store, "clear", None)
        if callable(clear):
            clear()


#: Process-wide limiter instance.
limiter = RateLimiter()


def configure_from_app(app) -> None:
    """Point the process-wide limiter at a shared store when one is configured.

    Called from the app factory. With ``RATE_LIMIT_STORAGE_URL`` set to a Redis
    URL (and ``redis`` installed and reachable) the limiter uses a shared window
    so the limit holds across all workers; otherwise it stays in-process.
    """
    url = app.config.get("RATE_LIMIT_STORAGE_URL")
    if not url:
        return
    try:
        import redis  # optional dependency; only needed for the shared store

        client = redis.Redis.from_url(url)
        client.ping()
        limiter.use_store(RedisWindowStore(client))
        logger.info("rate limiter using shared Redis store at %s", url)
    except Exception:  # noqa: BLE001 - fall back rather than fail to boot
        logger.warning(
            "RATE_LIMIT_STORAGE_URL is set but Redis is unavailable; "
            "falling back to the per-process rate limiter",
            exc_info=True,
        )


def rate_limited(
    spec: Optional[str] = None,
    key_func: Optional[Callable[[], str]] = None,
    config_key: Optional[str] = None,
):
    """Decorator that enforces a rate limit on a view.

    Resolution order for the rate spec: an explicit ``spec`` argument, else the
    value at ``config_key`` in app config (e.g. ``"RATE_LIMIT_INGEST"``), else
    ``RATE_LIMIT_DEFAULT``. The bucket key is derived from ``key_func``
    (defaulting to the authenticated identity or client IP), namespaced by the
    endpoint.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_app.config.get("RATE_LIMIT_ENABLED", True):
                return view(*args, **kwargs)
            resolved = (
                spec
                or (current_app.config.get(config_key) if config_key else None)
                or current_app.config.get("RATE_LIMIT_DEFAULT", "120/minute")
            )
            limit, window = parse_rate(resolved)
            identity = key_func() if key_func else _default_key()
            bucket = f"{request.endpoint}:{identity}"
            allowed, retry_after = limiter.hit(bucket, limit, window)
            if not allowed:
                raise RateLimitError(
                    f"rate limit exceeded ({resolved})", retry_after=retry_after
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator


def _default_key() -> str:
    """Identity for rate limiting: authenticated principal, else client IP."""
    identity = getattr(g, "agentscope_identity", None)
    if identity is not None:
        return f"id:{identity.principal_id}"
    return f"ip:{request.remote_addr or 'unknown'}"
