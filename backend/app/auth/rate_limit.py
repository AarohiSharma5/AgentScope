"""A small, thread-safe, in-memory rate limiter (fixed-window).

Sufficient for a single process; for multi-process deployments each worker
keeps its own window (a shared store like Redis would be a drop-in later). The
limiter is disabled globally via the ``RATE_LIMIT_ENABLED`` config flag.
"""
import threading
import time
from functools import wraps
from typing import Callable, Optional, Tuple

from flask import current_app, g, request

from .errors import RateLimitError

_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def parse_rate(spec: str) -> Tuple[int, int]:
    """Parse a rate spec like ``"100/minute"`` into ``(limit, window_seconds)``."""
    try:
        count, unit = spec.split("/")
        unit = unit.rstrip("s")  # allow "minute" or "minutes"
        return int(count), _UNITS[unit]
    except (ValueError, KeyError):
        raise ValueError(f"invalid rate limit spec: {spec!r}")


class RateLimiter:
    """Fixed-window counter keyed by an arbitrary string."""

    def __init__(self):
        self._lock = threading.Lock()
        self._windows: dict[str, Tuple[float, int]] = {}

    def hit(self, key: str, limit: int, window: int) -> Tuple[bool, int]:
        """Register a hit. Returns ``(allowed, retry_after_seconds)``."""
        now = time.time()
        with self._lock:
            start, count = self._windows.get(key, (now, 0))
            if now - start >= window:
                start, count = now, 0
            count += 1
            self._windows[key] = (start, count)
            if count > limit:
                return False, max(1, int(window - (now - start)))
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()


#: Process-wide limiter instance.
limiter = RateLimiter()


def rate_limited(spec: Optional[str] = None, key_func: Optional[Callable[[], str]] = None):
    """Decorator that enforces a rate limit on a view.

    ``spec`` defaults to the app's ``RATE_LIMIT_DEFAULT``. The bucket key is
    derived from ``key_func`` (defaulting to the authenticated identity or the
    client IP), namespaced by the endpoint.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_app.config.get("RATE_LIMIT_ENABLED", True):
                return view(*args, **kwargs)
            resolved = spec or current_app.config.get("RATE_LIMIT_DEFAULT", "120/minute")
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
