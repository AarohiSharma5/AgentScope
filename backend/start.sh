#!/usr/bin/env sh
# Container start command for the AgentScope demo (and any Docker deploy that
# opts into it). Keeping this in a script — rather than inlining `sh -c "... &&
# ..."` in Render's dockerCommand — avoids shell quoting/operator ambiguity that
# can make the platform treat the whole line as a single (missing) command.
#
# 1. Prepare the database for DEMO_MODE (seed/reseed). This is a no-op when
#    DEMO_MODE is off, and it never aborts startup (demo_boot swallows errors).
# 2. Hand off to gunicorn, bound to the port the platform provides ($PORT), as a
#    single threaded worker (the live-stream hub is in-process).
set -e

python demo_boot.py || true

exec gunicorn \
  -b "0.0.0.0:${PORT:-8000}" \
  -k gthread \
  -w 1 \
  --threads 32 \
  --timeout 120 \
  run:app
