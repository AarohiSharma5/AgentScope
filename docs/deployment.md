# Deployment

This guide covers running AgentScope in production: configuration, database,
authentication, streaming, scaling and hardening.

For local Docker usage see [Docker](docker.md). For env-var basics see
[Installation](installation.md#configuration-overview).

## Recommended topology

```mermaid
flowchart LR
    Client --> TLS[TLS / reverse proxy]
    TLS --> FE[nginx + React SPA]
    FE -->|/api| BE[gunicorn + Flask]
    BE --> PG[(Managed PostgreSQL)]
```

The React frontend (nginx) proxies `/api` to the Flask backend, which persists to
PostgreSQL. Terminate TLS at a reverse proxy or the nginx layer.

## Database

- Use **PostgreSQL** in production. Set `DATABASE_URL`
  (`postgresql://user:pass@host:5432/dbname`). The `postgres://` scheme is
  auto-normalized to `postgresql://`.
- SQLite is fine for local/dev but not for concurrent production load.
- Back up the database volume/instance regularly.

### Schema migrations (Alembic)

By default the app auto-creates any missing tables at startup
(`db.create_all()`), which is convenient for local/SQLite use but **cannot
evolve an existing schema** (added/renamed/removed columns are ignored). For
production, let **Alembic** own the schema instead:

```bash
cd backend
export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
export USE_MIGRATIONS=true          # stop the app from auto-creating tables
alembic upgrade head                # create/upgrade the schema
```

- Set `USE_MIGRATIONS=true` in production so schema changes only happen through
  reviewed migrations (run `alembic upgrade head` as a release/deploy step).
- **Adopting migrations on an existing `create_all` database:** the schema
  already matches the initial migration, so just record it without re-running
  DDL — `alembic stamp head` — then use `alembic upgrade head` for future
  changes.
- **Authoring a change:** edit the models, then
  `alembic revision --autogenerate -m "describe change"`, review the generated
  file, and commit it. Migrations use batch mode so they apply on both SQLite
  and PostgreSQL.

## Backend server

The Docker image serves the app with a **single gunicorn threaded (`gthread`)
worker** and an extended timeout. Threads keep long-lived SSE/WebSocket
connections cheap (one thread each, not a whole worker); the single worker is
deliberate (see streaming caveat below). A typical command:

```bash
gunicorn --worker-class gthread --workers 1 --threads 32 \
         --timeout 120 --bind 0.0.0.0:8000 "app:create_app()"
```

### Streaming and scaling (important)

By default the real-time hub (`LiveTraceManager`) and the auth rate limiter are
**in-process**: their state lives in one worker's memory. Consequences for the
streaming endpoints (`/api/stream`, `/api/ws`):

- **Without a broker, run streaming on a single worker.** Events are fanned out
  only to subscribers connected to the *same* worker that emitted them. With
  multiple workers, a live client silently misses every event produced on
  another worker (roughly `1 − 1/workers` of them), and `Last-Event-ID` replay
  only covers one worker's history buffer. The default image therefore runs
  `--workers 1`.
- **A single threaded worker scales vertically** (tens of thousands of
  concurrent SSE/WS connections and ample REST throughput for typical
  dashboards) because threads, not workers, carry the streams.

### Scaling streaming across workers/replicas (Redis)

Set **`STREAM_BROKER_URL`** to a Redis URL to fan events out across every worker
and replica via Redis pub/sub. Each worker publishes its events to a shared
channel and a background listener delivers peer workers' events into its own
local subscribers; event ids come from a Redis `INCR` counter so `Last-Event-ID`
reconnection stays coherent cluster-wide. It degrades gracefully — if Redis is
briefly unreachable, id allocation falls back to a local counter and publish
failures are logged, never breaking the request that produced the event.

```bash
STREAM_BROKER_URL=redis://redis:6379/0     # or reuse RATE_LIMIT_STORAGE_URL / REDIS_URL
gunicorn --worker-class gthread --workers 4 --threads 32 \
         --timeout 120 --bind 0.0.0.0:8000 "app:create_app()"
```

Requires the `redis` package (already in `requirements.txt`). Pair it with a
shared rate-limit store (`RATE_LIMIT_STORAGE_URL`) so limits hold cluster-wide.
The non-streaming REST API is stateless and safe to scale horizontally either
way.

Every event is tagged with its owning organization at emit time and a stream
only ever delivers its subscriber's own tenant's events (matching the tenant
isolation on the REST API).

## Configuration reference

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `AGENTSCOPE_ENV` | `development` | Set to `production` to enforce a safe posture at boot (auth on + strong secrets, or the app refuses to start). |
| `DATABASE_URL` | *(SQLite)* | PostgreSQL connection string. |
| `USE_MIGRATIONS` | `false` | When `true`, skip `create_all()`; manage schema via `alembic upgrade head`. |
| `SECRET_KEY` | `dev-secret-key` | **Set a strong value.** |
| `PORT` | `8000` | Backend port. |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins. |
| `STREAM_HEARTBEAT_INTERVAL` | `15` | SSE/WebSocket heartbeat seconds. |
| `STREAM_BROKER_URL` | _(unset)_ | Redis URL for cross-worker streaming fan-out; unset = single-worker in-process. |
| `AGENTSCOPE_MODEL_PRICES` | _(unset)_ | Model prices (USD/1K tokens) as inline JSON or a file path; extends built-ins. |
| `PLUGINS_AUTOLOAD` | `true` | Discover/enable plugins at startup. |
| `PLUGINS_PACKAGES` | `app.plugins.builtins` | Packages scanned for plugins. |
| `PLUGINS_ENTRYPOINT_GROUP` | `agentscope.plugins` | pip entry-point group for third-party plugins. |
| `AUTH_ENABLED` | `false` | Enforce auth on data routes. |
| `JWT_SECRET` | `SECRET_KEY` | JWT signing secret. |
| `JWT_ACCESS_TTL` | `900` | Access-token lifetime (s). |
| `JWT_REFRESH_TTL` | `2592000` | Refresh-token lifetime (s). |
| `API_KEY_PREFIX` | `as` | Prefix for minted API keys. |
| `RATE_LIMIT_ENABLED` | `true` | Enable the auth rate limiter. |
| `RATE_LIMIT_DEFAULT` | `120/minute` | Default rate limit. |

## Authentication & multi-tenancy

Authentication is **opt-in and backward compatible** in development. The auth
endpoints (`/api/auth/*`, `/api/organizations/*`) are always available; global
enforcement on the data routes is off until you set `AUTH_ENABLED=true`.

**In production it is not optional.** Set `AGENTSCOPE_ENV=production` and the app
**refuses to boot** unless `AUTH_ENABLED=true` and strong, non-default
`SECRET_KEY` / `JWT_SECRET` are set — so an open or forgeable-token deployment
can never ship by accident.

Setup:

1. Set strong `SECRET_KEY` and `JWT_SECRET`.
2. Register the first admin + organization:
   ```bash
   curl -X POST https://your-host/api/auth/register \
     -H "Content-Type: application/json" \
     -d '{"email":"admin@acme.com","password":"a-strong-password","organization_name":"Acme"}'
   ```
3. Authenticate requests with `Authorization: Bearer <access_token>` (users) or
   `X-API-Key: <key>` (services). Mint keys via
   `POST /api/organizations/:id/api-keys`.

Security properties:

- Passwords hashed with PBKDF2-SHA256 (werkzeug).
- JWTs signed HS256 with constant-time verification; short-lived access tokens +
  long-lived refresh tokens.
- API keys stored only as SHA-256 hashes; the raw secret is shown once.
- **Roles:** `admin` > `developer` > `viewer`; organization and project isolation
  enforced at a single service choke point.
- Rate limiting on auth endpoints; audit logging of security-relevant actions.

See the [REST API auth section](reference/rest-api.md#authentication--tenancy-v10).

## Hardening checklist

- [ ] `AGENTSCOPE_ENV=production` (enforces the two items below at boot).
- [ ] Strong `SECRET_KEY` / `JWT_SECRET`; never commit secrets.
- [ ] `AUTH_ENABLED=true` and TLS in front of the app.
- [ ] Restrict `CORS_ORIGINS` to your real dashboard origin(s).
- [ ] Managed PostgreSQL with backups; wipe defaults (`change-me-in-production`).
- [ ] `USE_MIGRATIONS=true` and `alembic upgrade head` run as a deploy step.
- [ ] Rate limiting enabled; consider a shared store for multi-worker limits.
- [ ] Review enabled plugins and provider credentials.

## Upgrades

Releases are additive and backward compatible across `v0.1 → v1.0`. Pull the new
images/code and restart; existing data and APIs continue to work. When running
with `USE_MIGRATIONS=true`, run `alembic upgrade head` after pulling so any new
schema is applied. See [CHANGELOG.md](../CHANGELOG.md).
