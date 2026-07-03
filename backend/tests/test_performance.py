"""Tests for the v1.0 performance infrastructure.

Covers the TTL cache, bounded/keyset pagination helpers and the background job
manager, plus a smoke check that the single-query dashboard aggregations still
return correct values.
"""
import time

import pytest

from app.extensions import db
from app.jobs import JobManager
from app.models.trace import Trace, TraceStatus
from app.services import trace_service
from app.utils.cache import TTLCache, cached, clear_cache
from app.utils.pagination import count_query, keyset_page


# -- TTL cache --------------------------------------------------------------


def test_ttl_cache_hit_and_expiry():
    cache = TTLCache()
    cache.set("k", 42, ttl=0.05)
    hit, value = cache.get("k")
    assert hit and value == 42
    time.sleep(0.06)
    hit, _ = cache.get("k")
    assert not hit


def test_cached_decorator_memoizes_within_ttl(app):
    calls = {"n": 0}

    @cached(ttl=10)
    def expensive():
        calls["n"] += 1
        return calls["n"]

    with app.app_context():
        clear_cache()
        assert expensive() == 1
        assert expensive() == 1  # served from cache; underlying not re-run
        assert calls["n"] == 1
        clear_cache()
        assert expensive() == 2


def test_cached_decorator_disabled_when_ttl_zero(app):
    calls = {"n": 0}

    @cached()  # falls back to config METRICS_CACHE_TTL, which is 0 in tests
    def counter():
        calls["n"] += 1
        return calls["n"]

    with app.app_context():
        assert counter() == 1
        assert counter() == 2  # no caching -> recomputed


# -- Pagination helpers -----------------------------------------------------


def _make_traces(n):
    for i in range(n):
        db.session.add(Trace(model_name="gpt-4o", user_prompt=f"p{i}"))
    db.session.commit()


def test_count_query_exact_and_bounded(app):
    with app.app_context():
        _make_traces(25)
        q = Trace.query
        assert count_query(q) == 25
        # Capped count stops early and reports the cap as "at least".
        assert count_query(q, max_count=10) == 10
        assert count_query(q, max_count=100) == 25


def test_keyset_page_is_stable_and_ordered(app):
    with app.app_context():
        _make_traces(10)
        first = keyset_page(Trace.query, Trace.id, limit=4)
        assert len(first) == 4
        ids = [t.id for t in first]
        assert ids == sorted(ids, reverse=True)  # newest-first
        # Next page continues after the last id with no overlap.
        nxt = keyset_page(Trace.query, Trace.id, limit=4, after_id=ids[-1])
        assert all(t.id < ids[-1] for t in nxt)


# -- Background jobs --------------------------------------------------------


def test_job_manager_runs_and_reports_success(app):
    manager = JobManager()
    manager.init_app(app)
    result = {}

    def work(x):
        result["value"] = x * 2
        return x * 2

    job = manager.submit("double", work, 21)
    _await(manager, job.id)
    done = manager.get(job.id)
    assert done.status == "succeeded"
    assert done.result == 42
    assert result["value"] == 42
    manager.shutdown(wait=True)


def test_job_manager_records_failure(app):
    manager = JobManager()
    manager.init_app(app)

    def boom():
        raise ValueError("nope")

    job = manager.submit("boom", boom)
    _await(manager, job.id)
    done = manager.get(job.id)
    assert done.status == "failed"
    assert "nope" in done.error
    manager.shutdown(wait=True)


def _await(manager, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job and job.status in ("succeeded", "failed"):
            return
        time.sleep(0.01)
    pytest.fail("job did not finish in time")


# -- Aggregation correctness (single-query paths) ---------------------------


def test_get_stats_single_query_values(app):
    with app.app_context():
        db.session.add(Trace(model_name="m", total_tokens=100, latency_ms=200,
                             estimated_cost=0.01, status=TraceStatus.SUCCESS))
        db.session.add(Trace(model_name="m", total_tokens=300, latency_ms=400,
                             estimated_cost=0.03, status=TraceStatus.FAILED))
        db.session.commit()
        stats = trace_service.get_stats()
        assert stats["total_requests"] == 2
        assert stats["avg_tokens"] == 200
        assert stats["avg_latency_ms"] == 300
        assert stats["success_rate"] == 50.0
