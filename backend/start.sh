#!/usr/bin/env sh
# Container start command for the AgentScope demo (and any Docker deploy that
# opts into it). Keeping this in a script — rather than inlining `sh -c "... &&
# ..."` in Render's dockerCommand — avoids shell quoting/operator ambiguity that
# can make the platform treat the whole line as a single (missing) command.
#
# Ordering matters: seeding a *networked* database (e.g. Neon over the public
# internet) is dominated by per-statement round-trips and can take several
# minutes. If we blocked startup on it, the web server would never bind in time
# and the platform's health check (GET /api/health) would time out and fail the
# deploy — which is exactly what happened before this change.
#
# So we:
# 1. Kick off demo_boot in the *background*. It seeds/reseeds when DEMO_MODE is
#    on (and is a no-op otherwise); it swallows its own errors. Data trickles in
#    over the next few minutes without holding up the server.
# 2. Immediately exec gunicorn so it binds to $PORT and answers the health probe
#    right away. `create_app()` runs `db.create_all()` at boot, so the schema
#    exists before any request, and /api/health is a static response that never
#    touches the database.
set -e

# 1. Create/repair the schema *synchronously and single-threaded* first. Running
#    create_all() from two processes at once (seeder + gunicorn worker) races on
#    CREATE TABLE and kills the worker; doing it here, alone, before anything
#    else, makes every later create_all() a no-op. Honors DEMO_RESET_ON_BOOT.
python demo_boot.py schema || true

# 2. Seed the *data* in the background. This phase never issues DDL, so it can
#    safely run alongside the web server. Data trickles in over a few minutes
#    without holding up startup or the health check.
python demo_boot.py seed &

# 3. Start the web server. It binds immediately (its create_all() is a no-op now)
#    and answers GET /api/health — a static response that never touches the DB.
exec gunicorn \
  -b "0.0.0.0:${PORT:-8000}" \
  -k gthread \
  -w 1 \
  --threads 32 \
  --timeout 120 \
  run:app
