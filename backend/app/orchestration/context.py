"""Shared context passed between collaborating agents.

A single :class:`AgentContext` instance is created by the orchestrator and shared
by every agent it spawns, giving them a common scratch space (facts, plans,
intermediate results) that survives across ``send``/``execute`` calls.
"""
from typing import Any, Iterator, Mapping, Optional


class AgentContext:
    """A lightweight, shared key/value store for a conversation's agents."""

    def __init__(self, initial: Optional[Mapping[str, Any]] = None) -> None:
        self._data: dict[str, Any] = dict(initial or {})

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for ``key``, or ``default`` if absent."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set ``key`` to ``value``."""
        self._data[key] = value

    def update(self, *args: Mapping[str, Any], **kwargs: Any) -> None:
        """Bulk-update the context from a mapping and/or keyword arguments."""
        self._data.update(*args, **kwargs)

    def all(self) -> dict[str, Any]:
        """Return a shallow copy of the full context."""
        return dict(self._data)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"<AgentContext keys={list(self._data)}>"
