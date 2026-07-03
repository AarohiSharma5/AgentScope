# Performance & Scaling

AgentScope is built to stay responsive from a laptop demo up to a production
deployment holding **millions of traces**, a large PostgreSQL database,
many concurrent users and long-running workflows. This page documents the
optimizations shipped in v1.0, how to tune them, and how to reproduce the
benchmarks.

Everything here is **backward compatible** — no API shapes changed, and every
optimization is either automatic or controlled by an environment variable with a
safe default.

---

## Summary of improvements

| Area | What changed | Why it matters at scale |
| --- | --- | --- |
| Connection pooling | Real pool sizing + `pool_pre_ping` + `pool_recycle` + LIFO reuse | Concurrent users no longer contend for a tiny/stale pool |
| Indexes | Composite `(status, timestamp)` / `(model, timestamp)` on `traces` (other tables already covered) | Filtered, newest-first listing avoids full scans |
| Query performance | Dashboard metrics collapsed from **5–7 queries to 1–2** per endpoint | Fewer round-trips; each is index/aggregate friendly |
| Caching | Short-TTL in-process cache for expensive aggregations | A burst of dashboard loads collapses into one computation |
| Pagination | Bounded `COUNT(*)` + keyset (seek) helpers | Deep pagination and huge-table counts stay fast |
| Background jobs | Bounded worker pool with a job registry | Long tasks never tie up request threads |
| Streaming | Per-event serialization is cached across all subscribers | Fan-out to many live clients serializes once |
| Frontend | Memoized table rows (`LiveTable`, `TracesTable`) | High-frequency live updates re-render only changed rows |

---

## Connection pooling

The SQLAlchemy engine is now configured for real concurrent load (PostgreSQL).
SQLite keeps only the cheap `pool_pre_ping` guard since it uses its own pool.

Tunable via environment variables (defaults shown):

| Variable | Default | Meaning |
| --- | --- | --- |
| `DB_POOL_SIZE` | `10` | Persistent connections per process |
| `DB_MAX_OVERFLOW` | `20` | Extra connections allowed under burst |
| `DB_POOL_TIMEOUT` | `30` | Seconds to wait for a free connection |
| `DB_POOL_RECYCLE` | `1800` | Recycle connections after 30 min (avoids stale server-side timeouts) |

`pool_pre_ping=True` transparently discards dead connections, and
`pool_use_lifo=True` keeps a small set of hot connections warm while letting idle
ones expire.

Size the pool relative to your worker/thread count and PostgreSQL's
`max_connections`: roughly `workers × (DB_POOL_SIZE + DB_MAX_OVERFLOW)` must stay
under the server limit (put PgBouncer in front for very high fan-out).

## Indexes

Every hot query path is backed by an index. Most tables already carried composite
indexes from earlier review passes; v1.0 adds the two the `traces` table was
missing:

- `ix_traces_status_timestamp (status, timestamp)`
- `ix_traces_model_timestamp (model_name, timestamp)`

These back the dashboard's "newest first, optionally filtered by status/model"
queries without scanning the table.

**Fresh databases** get every index automatically via `create_all()`.
**Existing large PostgreSQL databases** should backfill the new indexes without
locking the table:

```bash
psql "$DATABASE_URL" -f backend/scripts/perf_indexes.sql
```

The script uses `CREATE INDEX CONCURRENTLY IF NOT EXISTS`, so it is safe to run
online and is idempotent.

## Query performance: single-pass aggregations

Dashboard metric endpoints previously issued one query per widget (5–7 round
trips). They now compute all aggregates over the same table in a single query
using conditional `SUM(CASE …)` for rates:

- `GET /api/stats` — 1 query (was 5)
- `GET /api/dashboard/agent-metrics` — 2 queries + 3 unavoidable child-table
  counts (was 7)
- `GET /api/dashboard/rag-metrics` — 4 queries (was 8)

All aggregations remain correct across SQLite and PostgreSQL (verified by
`tests/test_performance.py`).

## Caching

Expensive read-mostly aggregations are wrapped with a tiny, thread-safe,
per-process TTL cache (`app/utils/cache.py`). A burst of concurrent dashboard
loads collapses into a single database computation for the TTL window.

| Variable | Default | Meaning |
| --- | --- | --- |
| `METRICS_CACHE_TTL` | `5` | Seconds to cache metrics; `0` disables caching |

The cache is applied to `get_stats`, `get_agent_metrics` and `get_rag_metrics`.
Tests set the TTL to `0` for deterministic assertions on freshly written data.
For multi-process deployments the same `cached` decorator can later be backed by
Redis without changing call sites.

## Pagination

Two helpers in `app/utils/pagination.py` keep listing fast on huge tables:

- **`count_query(query, max_count)`** — caps `COUNT(*)` using a limited subquery
  so a list footer never triggers a full-table count. Set `MAX_COUNT_LIMIT`
  (default `0` = exact counts) to enable "1,000,000+"-style bounded totals.
- **`keyset_page(query, id_column, limit, after_id)`** — seek pagination that
  filters on the last-seen id instead of `OFFSET`, keeping deep pages
  constant-time on an indexed id.

Existing offset-based endpoints are unchanged; these are opt-in building blocks.

## Background jobs

`app/jobs.py` provides a process-wide, **bounded** `ThreadPoolExecutor` plus an
in-memory job registry so long-running work (replay, evaluation, comparison,
large exports) can run off-request:

```python
from app.jobs import submit_job

job = submit_job("replay", run_replay, replay_id)
# -> poll GET /api/jobs/<job.id>  ->  queued | running | succeeded | failed
```

Each job runs inside a fresh Flask app context (full ORM access) with the session
cleaned up afterwards. Concurrency is capped by `BACKGROUND_WORKERS` (default
`4`), so a flood of jobs queues gracefully instead of exhausting threads and
database connections. Inspect jobs via `GET /api/jobs` and `GET /api/jobs/<id>`.

## Streaming efficiency

A single broadcast event is delivered to every live subscriber. Event wire
encodings (`to_sse()` / `to_json()`) are now computed lazily and cached on the
event, so fanning one event out to N subscribers serializes **once** instead of N
times. Combined with the existing bounded per-subscriber queues (drop-newest
backpressure) and heartbeats, the streaming hub scales to many concurrent live
dashboards.

## Frontend rendering

Live and trace tables now use memoized row components:

- `LiveTable` wraps each row in `React.memo`. The live reducer produces immutable
  updates (unchanged rows keep their reference) and column configs are stable
  module constants, so a high-frequency event stream re-renders only the rows
  that actually changed.
- `TracesTable` memoizes rows and the row-click handler (`useCallback`), so
  periodic refreshes don't re-render the whole page.

---

## Benchmarks

Reproduce with the bundled harness. It seeds a synthetic dataset into a throwaway
database and times the hottest read endpoints:

```bash
# 200k traces on a temp SQLite DB, 40 samples per endpoint
python backend/scripts/benchmark_api.py --rows 200000 --iterations 40

# 1M traces against PostgreSQL
DATABASE_URL=postgresql://user:pass@localhost/agentscope \
    python backend/scripts/benchmark_api.py --rows 1000000
```

Representative results — **200,000 traces**, temp SQLite, 40 iterations
(response latency in milliseconds):

| Endpoint | min | p50 | p95 |
| --- | --- | --- | --- |
| `GET /api/traces?limit=100` | 2.7 | 2.9 | 4.7 |
| `GET /api/stats` (cached) | 0.28 | 0.31 | 0.53 |
| `GET /api/dashboard/agent-metrics` | 0.28 | 0.30 | 0.52 |
| `GET /api/dashboard/rag-metrics` | 0.26 | 0.28 | 0.57 |

The first (cold) `/api/stats` call computes the full aggregate in a single query
(~30–40 ms at 200k rows on SQLite); every subsequent call within the TTL window
is served from cache in well under a millisecond. On PostgreSQL with the
composite indexes, the cold aggregate is comparable and list endpoints stay
flat as the table grows because they page on indexed columns.

## Production checklist

- Run behind **gunicorn with threaded workers** (see [deployment](deployment.md))
  so streaming connections and background jobs have threads to run on.
- Point `DATABASE_URL` at PostgreSQL and run `backend/scripts/perf_indexes.sql`
  once on existing databases.
- Tune `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` to your worker count and Postgres
  `max_connections`; consider PgBouncer for large fleets.
- Leave `METRICS_CACHE_TTL` at a few seconds for dashboards (raise it for very
  large tables; set `0` only when you need always-fresh metrics).
- Set `MAX_COUNT_LIMIT` (e.g. `10000`) once tables reach millions of rows to
  avoid exact full-table counts in list footers.
