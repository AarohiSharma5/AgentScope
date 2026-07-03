# Migration Guide

This guide covers upgrading between AgentScope versions. The headline: **there
are no breaking changes across v0.1 → v1.0.** Every release has been strictly
additive — existing REST endpoints, database schemas and frontend routes keep
working unchanged. You can upgrade in place.

## TL;DR

| From | To | Action required |
| --- | --- | --- |
| any 0.x | 1.0.0 | None to keep current behavior. Optionally backfill indexes and adopt new opt-in features below. |

---

## Upgrading to v1.0.0

### 1. Nothing is required
v1.0.0 does not change any existing API contract or table. Pull the new version,
rebuild, and everything behaves exactly as before.

```bash
git pull
docker compose up --build   # or restart your gunicorn workers
```

The application calls `db.create_all()` on startup, so **new** tables (auth /
multi-tenancy) are created automatically and remain empty and unused unless you
enable authentication.

### 2. (PostgreSQL, large tables) Backfill performance indexes
Fresh databases get every index automatically. Existing PostgreSQL databases
should backfill the two new composite indexes on `traces` — done online, no
table lock:

```bash
psql "$DATABASE_URL" -f backend/scripts/perf_indexes.sql
```

SQLite users need do nothing (indexes are created on startup).

### 3. (Optional) Tune performance
All defaults are safe. To tune for scale, set any of:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `20` | Connection pool sizing |
| `DB_POOL_RECYCLE` / `DB_POOL_TIMEOUT` | `1800` / `30` | Recycle / wait timeouts |
| `METRICS_CACHE_TTL` | `5` | Seconds to cache dashboard metrics (`0` disables) |
| `MAX_COUNT_LIMIT` | `0` | Cap list-footer counts on huge tables (`0` = exact) |
| `BACKGROUND_WORKERS` | `4` | Background job pool size |

See the [Performance guide](performance.md) for details.

### 4. (Optional) Enable authentication & multi-tenancy
Auth is **off by default**. To turn it on:

```bash
AUTH_ENABLED=true
JWT_SECRET=<a-strong-random-secret>
```

Then register a user and mint API keys via the auth endpoints (see the
[REST API reference](reference/rest-api.md) and
[example 09](../examples/09_auth_api_keys.py)). With `AUTH_ENABLED=false` the
auth endpoints still exist for opt-in use but nothing is enforced on the data
routes.

### 5. (Optional) Adopt the SDK and CLI
```bash
pip install agentscope-lite
```
The SDK is a separate, dependency-free package; installing it does not affect the
server. The CLI ships with it (`agentscope --help`). See the
[SDK](reference/sdk.md) and [CLI](reference/cli.md) references.

---

## Notes for earlier upgrades

- **0.5 → 0.6** — Added streaming, plugins, providers and export/import, plus the
  live dashboard. All additive; `db.create_all()` adds any new tables on startup.
- **0.4 → 0.5** — Added replay, evaluation, comparison and prompt/trace diffs
  (new tables only).
- **0.3 → 0.4** — Added multi-agent workflows and conversations (new tables only).
- **0.2 → 0.3** — Added RAG/embedding/prompt-assembly tracing (new tables only).
- **0.1 → 0.2** — Added agent-execution tracing (new tables only).

In every case: pull, restart, done. New tables are created automatically and old
data/endpoints are untouched.

## Rollback

Because no migrations rewrite existing tables, rolling back to a previous version
is safe — the older code simply ignores the newer, unused tables. (If you enabled
authentication and want to fully remove it, drop the auth tables manually; this
is optional.)

## Database migrations

AgentScope uses SQLAlchemy's `create_all()` for additive schema management, which
covers every release to date. If your deployment requires managed, versioned
migrations (e.g. Alembic), you can introduce them without conflict — the current
schema is the source of truth and no destructive changes have ever been shipped.
