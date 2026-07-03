#!/usr/bin/env python
"""Benchmark critical AgentScope read APIs under a large synthetic dataset.

Seeds N traces (and optional agent runs) into a throwaway database, then times
the hottest read endpoints so the effect of indexes, single-query aggregation
and metrics caching is measurable and repeatable.

Usage
-----
    # Default: 100k traces on a temp SQLite DB
    python backend/scripts/benchmark_api.py

    # Bigger dataset, more samples
    python backend/scripts/benchmark_api.py --rows 500000 --iterations 50

    # Benchmark against PostgreSQL
    DATABASE_URL=postgresql://user:pass@localhost/agentscope \
        python backend/scripts/benchmark_api.py --rows 1000000

The database is created fresh and (for the temp SQLite case) deleted afterwards.
Never point ``DATABASE_URL`` at a database you care about.
"""
import argparse
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

# Make the backend package importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.trace import Trace, TraceStatus  # noqa: E402
from app.utils.timeutils import utcnow  # noqa: E402

MODELS = ["gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "gemini-1.5-pro", "llama-3-70b"]


def seed_traces(rows: int, batch: int = 5000) -> None:
    """Bulk-insert ``rows`` traces using fast, ORM-free inserts."""
    now = utcnow()
    inserted = 0
    while inserted < rows:
        n = min(batch, rows - inserted)
        mappings = []
        for i in range(n):
            idx = inserted + i
            mappings.append(
                {
                    "user_prompt": f"prompt {idx}",
                    "system_prompt": "you are helpful",
                    "model_name": random.choice(MODELS),
                    "timestamp": now,
                    "latency_ms": random.uniform(50, 2000),
                    "input_tokens": random.randint(10, 500),
                    "output_tokens": random.randint(10, 800),
                    "total_tokens": random.randint(20, 1300),
                    "estimated_cost": random.uniform(0.0001, 0.05),
                    "final_response": "ok",
                    "status": TraceStatus.SUCCESS
                    if random.random() > 0.1
                    else TraceStatus.FAILED,
                }
            )
        db.session.bulk_insert_mappings(Trace, mappings)
        db.session.commit()
        inserted += n
        print(f"  seeded {inserted:,}/{rows:,}", end="\r", flush=True)
    print()


def time_endpoint(client, path: str, iterations: int) -> dict:
    """Call ``path`` ``iterations`` times and return timing percentiles (ms)."""
    samples = []
    for _ in range(iterations):
        start = time.perf_counter()
        resp = client.get(path)
        samples.append((time.perf_counter() - start) * 1000)
        assert resp.status_code == 200, f"{path} -> {resp.status_code}"
    samples.sort()
    return {
        "min": samples[0],
        "p50": statistics.median(samples),
        "p95": samples[min(len(samples) - 1, int(len(samples) * 0.95))],
        "max": samples[-1],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100_000, help="traces to seed")
    parser.add_argument("--iterations", type=int, default=30, help="samples per endpoint")
    args = parser.parse_args()

    tmp_db = None
    if not os.getenv("DATABASE_URL"):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        tmp_db = tmp.name
        os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db}"

    class BenchConfig(Config):
        # Exercise the production cache path.
        METRICS_CACHE_TTL = 5

    app = create_app(BenchConfig)
    backend = "PostgreSQL" if not tmp_db else "SQLite (temp)"
    print(f"Backend: {backend}")
    print(f"Seeding {args.rows:,} traces...")

    with app.app_context():
        t0 = time.perf_counter()
        seed_traces(args.rows)
        print(f"Seed time: {time.perf_counter() - t0:.1f}s\n")

    client = app.test_client()

    endpoints = {
        "GET /api/traces?limit=100": "/api/traces?limit=100",
        "GET /api/stats (cold+warm cache)": "/api/stats",
        "GET /api/dashboard/agent-metrics": "/api/dashboard/agent-metrics",
        "GET /api/dashboard/rag-metrics": "/api/dashboard/rag-metrics",
    }

    print(f"Timing endpoints ({args.iterations} iterations each):\n")
    header = f"{'endpoint':40} {'min':>9} {'p50':>9} {'p95':>9} {'max':>9}"
    print(header)
    print("-" * len(header))
    for label, path in endpoints.items():
        stats = time_endpoint(client, path, args.iterations)
        print(
            f"{label:40} "
            f"{stats['min']:8.2f}m {stats['p50']:8.2f}m "
            f"{stats['p95']:8.2f}m {stats['max']:8.2f}m"
        )

    if tmp_db and os.path.exists(tmp_db):
        os.unlink(tmp_db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
