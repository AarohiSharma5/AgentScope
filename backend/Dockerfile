# Pinned to 3.12 to match CI (tests/release/SDK all target 3.12) and because
# binary wheels (e.g. psycopg2-binary) exist for it — 3.14 has no cp314 wheel yet,
# forcing a source build that fails in the slim image (no libpq/compiler).
FROM python:3.12-slim

# Avoid .pyc files and buffer flushing; keep logs immediate.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Production WSGI server. run.py exposes `app = create_app()`.
# A SINGLE threaded (gthread) worker with many threads: long-lived SSE/WebSocket
# streams (v0.6) each hold a thread, and the extended timeout keeps them from
# being reaped mid-stream. One worker is deliberate — the LiveTraceManager hub
# is in-process, so with multiple workers a client would miss events emitted on
# other workers. To scale horizontally, put a shared broker (Redis/NATS) behind
# the hub; see docs/deployment.md. All REST endpoints work unchanged.
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-k", "gthread", "-w", "1", "--threads", "32", "--timeout", "120", "run:app"]
