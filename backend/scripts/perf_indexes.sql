-- Performance indexes for existing large PostgreSQL databases.
--
-- New/fresh databases already get every index below via SQLAlchemy's
-- create_all(). This script only matters for an EXISTING deployment whose tables
-- predate the v1.0 optimization pass and therefore need the newly added
-- composite indexes backfilled.
--
-- We use CREATE INDEX CONCURRENTLY so index builds do NOT take an
-- ACCESS EXCLUSIVE lock and never block reads/writes on a live database.
--
-- Usage:
--   psql "$DATABASE_URL" -f backend/scripts/perf_indexes.sql
--
-- Notes:
--   * CONCURRENTLY cannot run inside a transaction block; run this file as-is
--     (psql executes each statement autonomously).
--   * IF NOT EXISTS makes the script safe to re-run (idempotent).

-- Newest-first trace listing filtered by status (dashboard + list endpoint).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_traces_status_timestamp
    ON traces (status, timestamp);

-- Newest-first trace listing filtered by model.
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_traces_model_timestamp
    ON traces (model_name, timestamp);

-- Refresh planner statistics so the new indexes are considered immediately.
ANALYZE traces;
