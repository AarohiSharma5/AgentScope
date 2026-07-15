"""Cooperative commit batching so a multi-row write can be one transaction.

Service ``create_*`` / ``finish_*`` helpers call :func:`commit` instead of
``db.session.commit()`` directly. By default that commits immediately (unchanged
behavior for the in-process recorder and single-row routes). Inside a
:func:`deferred_commits` block it *flushes* instead — assigning primary keys
without ending the transaction — so an orchestrating caller (e.g. HTTP ingestion
of a whole agent run: run + steps + tools + memory + retrievals + documents) can
wrap many writes in one atomic transaction and commit exactly once at the end.

This turns a "transaction storm" (100+ commits / connection round-trips for a
single nested payload) into a single commit, and makes ingestion atomic (a
failure part-way through rolls the whole thing back instead of leaving partial
rows).

The active flag is thread-local, so concurrent requests and worker threads never
affect each other's batching.
"""
import threading
from contextlib import contextmanager

from ..extensions import db

_state = threading.local()


def deferring() -> bool:
    """Whether the current thread is inside a :func:`deferred_commits` block."""
    return getattr(_state, "active", False)


def commit() -> None:
    """Commit now, or flush (to assign ids) when inside a deferred batch."""
    if deferring():
        db.session.flush()
    else:
        db.session.commit()


@contextmanager
def deferred_commits():
    """Within this block, :func:`commit` flushes instead of committing.

    The caller owns the final ``db.session.commit()`` / ``db.session.rollback()``.
    Nesting is safe: only the outermost block drives the behavior, and the flag
    is always restored on exit.
    """
    previous = deferring()
    _state.active = True
    try:
        yield
    finally:
        _state.active = previous
