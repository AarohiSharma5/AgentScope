"""Shared context passed between collaborating agents.

A single :class:`AgentContext` instance is created by the orchestrator and shared
by every agent it spawns, giving them a common scratch space (facts, plans,
intermediate results) that survives across ``send``/``execute`` calls.

Thread-safety and the value-immutability contract
--------------------------------------------------
Because parallel workflow branches run their handlers on separate threads while
sharing one context, every access is guarded by a lock so concurrent reads and
writes never observe a torn ``dict`` *at the mapping level* (adding, replacing
or removing a key is atomic).

The lock does **not** extend into the stored values. If a value is a mutable
container (``list``/``dict``/custom object), mutating it in place from one thread
while another reads it is a data race the lock cannot protect against —
``ctx.get("results")`` returns the *same* object every caller shares, and
``all()``/iteration return shallow copies.

Therefore stored values are treated as **immutable**: to change one, build a new
value and ``set()`` it, rather than mutating the object returned by ``get()``.
For the read-modify-write case (append to a list, bump a counter) use
:meth:`AgentContext.mutate`, which performs the whole cycle under the lock on a
private deep copy and stores the result atomically.
"""
import copy
import threading
from typing import Any, Callable, Iterator, Mapping, Optional


class AgentContext:
    """A lightweight, thread-safe shared key/value store for a conversation's agents.

    Values are shared by reference and must be treated as immutable (see the
    module docstring); use :meth:`mutate` for safe read-modify-write updates.
    """

    def __init__(self, initial: Optional[Mapping[str, Any]] = None) -> None:
        self._data: dict[str, Any] = dict(initial or {})
        self._lock = threading.RLock()
        # Optional workflow cancel token, bound by the engine so handlers can
        # cooperatively stop in-flight work (threads can't be preempted).
        self._cancel_token: Any = None

    def bind_cancel_token(self, token: Any) -> None:
        """Attach the running workflow's cancellation token (used by the engine)."""
        self._cancel_token = token

    @property
    def cancelled(self) -> bool:
        """Whether the running workflow has requested cancellation.

        Long-running handlers should poll this and return promptly when true;
        it is the only reliable way to interrupt in-flight work, since the
        engine cannot forcibly kill a running handler thread.
        """
        token = self._cancel_token
        return bool(token is not None and token.cancelled)

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for ``key``, or ``default`` if absent.

        The value is returned by reference and shared with other threads; do not
        mutate it in place (see :meth:`mutate`).
        """
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set ``key`` to ``value`` (atomic replacement of the key)."""
        with self._lock:
            self._data[key] = value

    def mutate(self, key: str, mutator: Callable[[Any], Any], default: Any = None) -> Any:
        """Atomically read-modify-write ``key`` under the lock.

        ``mutator`` receives a deep copy of the current value (or ``default`` when
        the key is absent) and returns the new value to store; whatever it returns
        is written back and also returned. Because the whole cycle holds the lock
        and operates on a private copy, this is the safe way to update a mutable
        container without violating the value-immutability contract::

            ctx.mutate("results", lambda r: [*r, item], default=[])
            ctx.mutate("count", lambda c: c + 1, default=0)
        """
        with self._lock:
            current = copy.deepcopy(self._data.get(key, default))
            new_value = mutator(current)
            self._data[key] = new_value
            return new_value

    def update(self, *args: Mapping[str, Any], **kwargs: Any) -> None:
        """Bulk-update the context from a mapping and/or keyword arguments."""
        with self._lock:
            self._data.update(*args, **kwargs)

    def all(self) -> dict[str, Any]:
        """Return a shallow copy of the full context.

        The returned dict is a snapshot, but its values are still shared by
        reference; do not mutate them in place (see :meth:`mutate`).
        """
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
