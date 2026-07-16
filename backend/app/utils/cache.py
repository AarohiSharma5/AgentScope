"""A tiny thread-safe, in-process TTL cache.

Used to memoize expensive, read-mostly aggregations (e.g. dashboard metrics)
for a few seconds so a burst of concurrent dashboard loads collapses into a
single database computation instead of one per request.

This is intentionally dependency-free and per-process. For multi-process /
multi-node deployments a shared cache (Redis/memcached) can be layered behind
the same :func:`cached` decorator later without changing call sites.

Beyond a plain TTL map it provides three properties that matter under real load:

* **Single-flight (stampede protection).** On a miss, concurrent callers for the
  *same* key serialize on a per-key lock so only the first runs the expensive
  computation; the rest wait and read its result. Different keys still compute in
  parallel. Without this, a cold cache under a burst lets every request hit the
  database at once (a "cache stampede").
* **Bounded size (LRU).** The store is capped at ``max_size`` entries and evicts
  the least-recently-used entry on overflow, so high-cardinality keys (e.g.
  per-org × per-function) cannot grow the process memory without bound.
* **Invalidation.** :meth:`TTLCache.invalidate` (and the per-function
  ``wrapper.invalidate`` handle) drop stale entries immediately after a write,
  instead of waiting out the TTL.
"""
import functools
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

from flask import current_app, has_app_context

#: Default cap on the number of live entries. Sized generously for the handful of
#: aggregations we cache across a realistic number of tenants; overflow evicts
#: the least-recently-used entry rather than growing unbounded.
DEFAULT_MAX_SIZE = 2048


class TTLCache:
    """A thread-safe TTL cache with LRU eviction and single-flight fills."""

    def __init__(self, max_size: int = DEFAULT_MAX_SIZE) -> None:
        self._lock = threading.Lock()
        # Ordered by recency of use: the left end is the LRU eviction candidate.
        self._store: "OrderedDict[Any, tuple[float, Any]]" = OrderedDict()
        # Per-key locks for single-flight fills, ref-counted so they are dropped
        # once no caller is using them (the lock table stays bounded too).
        self._key_locks: dict[Any, list] = {}
        self._max_size = max_size

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
            self._store.move_to_end(key)
            return True, value

    def set(self, key: Any, value: Any, ttl: float) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + ttl, value)
            self._store.move_to_end(key)
            # Evict least-recently-used entries until back within the bound.
            while len(self._store) > self._max_size:
                self._store.popitem(last=False)

    def get_or_set(self, key: Any, ttl: float, compute: Callable[[], Any]) -> Any:
        """Return the cached value for ``key`` or compute-and-store it once.

        Concurrent misses on the same key serialize on a per-key lock so
        ``compute`` runs exactly once; the losers re-read the freshly stored
        value instead of piling onto the backing store (single-flight).
        """
        hit, value = self.get(key)
        if hit:
            return value

        key_lock = self._acquire_key_lock(key)
        try:
            with key_lock:
                # Re-check under the per-key lock: the flight leader may have
                # already populated the entry while we waited.
                hit, value = self.get(key)
                if hit:
                    return value
                value = compute()
                self.set(key, value, ttl)
                return value
        finally:
            self._release_key_lock(key)

    def invalidate(self, predicate: Callable[[Any], bool]) -> int:
        """Drop every entry whose key matches ``predicate``; return the count."""
        with self._lock:
            keys = [k for k in self._store if predicate(k)]
            for k in keys:
                self._store.pop(k, None)
            return len(keys)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    # -- per-key lock bookkeeping ------------------------------------------

    def _acquire_key_lock(self, key: Any) -> threading.Lock:
        with self._lock:
            entry = self._key_locks.get(key)
            if entry is None:
                entry = [threading.Lock(), 0]
                self._key_locks[key] = entry
            entry[1] += 1
            return entry[0]

    def _release_key_lock(self, key: Any) -> None:
        with self._lock:
            entry = self._key_locks.get(key)
            if entry is None:
                return
            entry[1] -= 1
            if entry[1] <= 0:
                self._key_locks.pop(key, None)


#: Process-wide cache instance shared by the :func:`cached` decorator.
_cache = TTLCache()


def clear_cache() -> None:
    """Drop all cached entries (used by tests and on full invalidation)."""
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

    The wrapped function exposes:

    * ``wrapper.invalidate(*args, **kwargs)`` — drop the entry for a specific
      argument set, or every entry for this function when called with no args.
    * ``wrapper.cache_clear()`` — drop the whole process cache.
    """

    def decorator(func: Callable) -> Callable:
        namespace = key or f"{func.__module__}.{func.__qualname__}"

        def _make_key(args, kwargs):
            return (namespace, args, tuple(sorted(kwargs.items())))

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            effective_ttl = _resolve_ttl(ttl)
            if effective_ttl <= 0:
                return func(*args, **kwargs)
            cache_key = _make_key(args, kwargs)
            return _cache.get_or_set(cache_key, effective_ttl, lambda: func(*args, **kwargs))

        def invalidate(*args, **kwargs) -> int:
            """Invalidate one argument set, or the whole function namespace."""
            if not args and not kwargs:
                return _cache.invalidate(lambda k: k[0] == namespace)
            target = _make_key(args, kwargs)
            return _cache.invalidate(lambda k: k == target)

        wrapper.invalidate = invalidate  # type: ignore[attr-defined]
        wrapper.cache_clear = clear_cache  # type: ignore[attr-defined]
        return wrapper

    return decorator
