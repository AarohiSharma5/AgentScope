"""Bounded background job execution.

Long-running work — replays, evaluations, model comparisons, large exports —
should never occupy a request-handling thread for seconds (or minutes). This
module provides a small, process-wide, bounded thread pool plus a lightweight
in-memory job registry so such work can be dispatched off-request and polled
for status.

Design
------
* **Bounded.** A single :class:`~concurrent.futures.ThreadPoolExecutor` sized by
  ``BACKGROUND_WORKERS`` caps concurrency, so a flood of long jobs degrades
  gracefully (they queue) instead of exhausting threads/connections.
* **App-context aware.** Each job runs inside a fresh Flask app context so it can
  use the ORM (``db.session``) exactly like a request handler, with the session
  cleaned up afterwards.
* **Observable.** Every submission gets a :class:`Job` record (``queued`` ->
  ``running`` -> ``succeeded``/``failed``) that a status endpoint can read.
* **Additive.** Existing synchronous endpoints keep working unchanged; callers
  opt into background execution via :func:`submit_job`.
"""
from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from flask import Flask

from .utils.timeutils import utcnow

logger = logging.getLogger("agentscope")


@dataclass
class Job:
    """A tracked unit of background work."""

    id: str
    name: str
    status: str = "queued"  # queued | running | succeeded | failed
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result: Any = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
        }


class JobManager:
    """Process-wide bounded executor with an in-memory job registry."""

    def __init__(self) -> None:
        self._app: Optional[Flask] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_jobs = 1000  # cap registry memory; evict oldest terminal jobs

    def init_app(self, app: Flask) -> None:
        """Bind to a Flask app and create the worker pool (idempotent)."""
        self._app = app
        # Reclaim a pool from a previous init (e.g. a worker reload) so we don't
        # leak its threads when replacing it.
        if self._executor is not None:
            self._executor.shutdown(wait=False)
        workers = int(app.config.get("BACKGROUND_WORKERS", 4)) or 1
        self._executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="agentscope-job"
        )
        app.extensions["job_manager"] = self
        logger.info("background job manager ready (%s workers)", workers)

    def submit(self, name: str, func: Callable, *args, **kwargs) -> Job:
        """Schedule ``func(*args, **kwargs)`` off-request and return its :class:`Job`."""
        if self._executor is None or self._app is None:
            raise RuntimeError("JobManager not initialized; call init_app() first")

        job = Job(id=uuid.uuid4().hex, name=name)
        with self._lock:
            self._jobs[job.id] = job
            self._evict_if_needed()

        self._executor.submit(self._run, job, func, args, kwargs)
        return job

    def _run(self, job: Job, func: Callable, args: tuple, kwargs: dict) -> None:
        job.status = "running"
        job.started_at = utcnow().isoformat()
        try:
            with self._app.app_context():  # type: ignore[union-attr]
                try:
                    job.result = func(*args, **kwargs)
                finally:
                    from .extensions import db

                    db.session.remove()
            job.status = "succeeded"
        except Exception as exc:  # noqa: BLE001 - record failure, never crash worker
            job.status = "failed"
            job.error = str(exc)
            logger.exception("background job %s (%s) failed", job.id, job.name)
        finally:
            job.finished_at = utcnow().isoformat()

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def _evict_if_needed(self) -> None:
        if len(self._jobs) <= self._max_jobs:
            return
        terminal = [
            j for j in self._jobs.values() if j.status in ("succeeded", "failed")
        ]
        terminal.sort(key=lambda j: j.finished_at or "")
        for job in terminal[: len(self._jobs) - self._max_jobs]:
            self._jobs.pop(job.id, None)

    def shutdown(self, wait: bool = False) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=wait)
            self._executor = None


#: Process-wide singleton wired up in the application factory.
job_manager = JobManager()


def submit_job(name: str, func: Callable, *args, **kwargs) -> Job:
    """Convenience wrapper around the singleton :class:`JobManager`."""
    return job_manager.submit(name, func, *args, **kwargs)


def get_job(job_id: str) -> Optional[Job]:
    return job_manager.get(job_id)


__all__ = ["Job", "JobManager", "job_manager", "submit_job", "get_job"]
