"""A tiny thread-safe, in-process TTL cache.

Used to memoize expensive, read-mostly aggregations (e.g. dashboard metrics)
for a few seconds so a burst of concurrent dashboard loads collapses into a
single database computation instead of one per request.

This is intentionally dependency-free and per-process. For multi-process /
multi-node deployments a shared cache (Redis/memcached) can be layered behind
the same :func:`cached` decorator later without changing call sites.
"""
import functools
import threading
import time
from typing import Any, Callable, Optional

from flask import current_app, has_app_context


class TTLCache:
    """A minimal thread-safe time-to-live cache keyed by hashable keys."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any, now: Optional[float] = None) -> tuple[bool, Any]:
        """Return ``(hit, value)``. ``hit`` is False when missing or expired."""
        now = now if now is not None else time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False, None
            expires_at, value = entry
            if expires_at < now:
                self._store.pop(key, None)
                return False, None
            return True, value

    def set(self, key: Any, value: Any, ttl: float) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


#: Process-wide cache instance shared by the :func:`cached` decorator.
_cache = TTLCache()


def clear_cache() -> None:
    """Drop all cached entries (used by tests and after bulk writes)."""
    _cache.clear()


def _resolve_ttl(explicit_ttl: Optional[float]) -> float:
    if explicit_ttl is not None:
        return explicit_ttl
    if has_app_context():
        return float(current_app.config.get("METRICS_CACHE_TTL", 0) or 0)
    return 0.0


def cached(ttl: Optional[float] = None, key: Optional[str] = None):
    """Memoize a function's result for ``ttl`` seconds.

    ``ttl`` defaults to the app's ``METRICS_CACHE_TTL`` config (resolved at call
    time); a TTL of 0 disables caching, so the decorator is always safe to apply
    and can be toggled entirely via configuration.
    """

    def decorator(func: Callable) -> Callable:
        namespace = key or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            effective_ttl = _resolve_ttl(ttl)
            if effective_ttl <= 0:
                return func(*args, **kwargs)
            cache_key = (namespace, args, tuple(sorted(kwargs.items())))
            hit, value = _cache.get(cache_key)
            if hit:
                return value
            value = func(*args, **kwargs)
            _cache.set(cache_key, value, effective_ttl)
            return value

        wrapper.cache_clear = clear_cache  # type: ignore[attr-defined]
        return wrapper

    return decorator
