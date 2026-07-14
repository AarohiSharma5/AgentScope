FROM python:3.14-slim

# Avoid .pyc files and buffer flushing; keep logs immediate.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Production WSGI server. run.py exposes `app = create_app()`.
# Threaded (gthread) workers so long-lived SSE/WebSocket streams (v0.6) each
# hold a thread instead of an entire worker, and a higher timeout so streaming
# connections are not reaped mid-stream. Backward compatible with all existing
# REST endpoints.
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-k", "gthread", "-w", "2", "--threads", "16", "--timeout", "120", "run:app"]
