# Docker

The whole stack — PostgreSQL, the Flask backend and the React frontend — runs
with one command via `docker-compose.yml`.

## Services

| Service | Image / build | Host port | Notes |
| ------- | ------------- | --------- | ----- |
| `db` | `postgres:16-alpine` | `5432` | Data persisted in the `agentscope_pgdata` volume; has a `pg_isready` healthcheck. |
| `backend` | `./backend` (gunicorn) | `8000` | Waits for `db` to be healthy; `DATABASE_URL` points at the `db` service. |
| `frontend` | `./frontend` (nginx) | `8080` → `80` | Serves the SPA and proxies `/api` to the backend. |

## Bring it up

```bash
docker compose up -d --build
```

| Service | URL |
| ------- | --- |
| Frontend | http://localhost:8080 |
| Backend API | http://localhost:8000/api |
| PostgreSQL | localhost:5432 |

Load sample data once (optional):

```bash
docker compose exec backend python seed.py
```

## Everyday commands

```bash
docker compose ps          # status of all three services
docker compose logs -f     # tail logs (add a service name to filter)
docker compose restart backend
docker compose down        # stop everything (data persists in the volume)
docker compose down -v     # stop and wipe the database volume
```

You can also start the stack from the CLI, which auto-detects the compose file:

```bash
agentscope start
```

## Environment variables

The compose file sets sensible defaults. Override them in `docker-compose.yml`,
an `.env` file, or your shell:

| Variable | Compose default | Purpose |
| -------- | --------------- | ------- |
| `DATABASE_URL` | `postgresql://agentscope:agentscope@db:5432/agentscope` | Backend DB connection. |
| `CORS_ORIGINS` | `http://localhost:8080` | Allowed dashboard origin. |
| `SECRET_KEY` | `change-me-in-production` | **Change this in production.** |
| `PORT` | `8000` | Backend port. |

For the full configuration matrix (auth, JWT, rate limiting, streaming, plugins)
see [Installation](installation.md#configuration-overview) and
[Deployment](deployment.md).

## Streaming & threaded workers

The backend image runs gunicorn with **threaded (`gthread`) workers** and an
extended timeout so long-lived SSE/WebSocket connections stay open. If you tune
gunicorn yourself, keep threaded workers for the `/api/stream` and `/api/ws`
endpoints to work correctly.

## Production notes

- Set a strong `SECRET_KEY` (and `JWT_SECRET`) and enable `AUTH_ENABLED=true`.
- Put the frontend/nginx behind TLS (or a reverse proxy that terminates TLS).
- Point `DATABASE_URL` at a managed PostgreSQL instance and back up the volume.
- See [Deployment](deployment.md) for scaling, auth and hardening.
