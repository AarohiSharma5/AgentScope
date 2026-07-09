"""Shared context passed between collaborating agents.

A single :class:`AgentContext` instance is created by the orchestrator and shared
by every agent it spawns, giving them a common scratch space (facts, plans,
intermediate results) that survives across ``send``/``execute`` calls.

Because parallel workflow branches run their handlers on separate threads while
sharing one context, every access is guarded by a lock so concurrent reads and
writes never observe a torn ``dict``.
"""
import threading
from typing import Any, Iterator, Mapping, Optional


class AgentContext:
    """A lightweight, thread-safe shared key/value store for a conversation's agents."""

    def __init__(self, initial: Optional[Mapping[str, Any]] = None) -> None:
        self._data: dict[str, Any] = dict(initial or {})
        self._lock = threading.RLock()

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for ``key``, or ``default`` if absent."""
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set ``key`` to ``value``."""
        with self._lock:
            self._data[key] = value

    def update(self, *args: Mapping[str, Any], **kwargs: Any) -> None:
        """Bulk-update the context from a mapping and/or keyword arguments."""
        with self._lock:
            self._data.update(*args, **kwargs)

    def all(self) -> dict[str, Any]:
        """Return a shallow copy of the full context."""
        with self._lock:
            return dict(self._data)

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._data

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(dict(self._data))

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __repr__(self) -> str:
        return f"<AgentContext keys={list(self._data)}>"
