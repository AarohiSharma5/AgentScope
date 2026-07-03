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
- Tables are created automatically on startup (`db.create_all()`); back up the
  database volume/instance regularly.

## Backend server

The Docker image serves the app with **gunicorn using threaded (`gthread`)
workers** and an extended timeout, which is required for long-lived SSE and
WebSocket connections. A typical command:

```bash
gunicorn --worker-class gthread --workers 2 --threads 8 \
         --timeout 120 --bind 0.0.0.0:5001 "app:create_app()"
```

Scale by adding workers/replicas behind a load balancer. Because the streaming
rate limiter and `LiveTraceManager` are **in-process**, each worker keeps its own
live-subscriber set and rate-limit windows — fine for most deployments; use
sticky sessions for SSE, or a shared broker if you need cross-worker fan-out.

## Configuration reference

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `DATABASE_URL` | *(SQLite)* | PostgreSQL connection string. |
| `SECRET_KEY` | `dev-secret-key` | **Set a strong value.** |
| `PORT` | `5001` | Backend port. |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins. |
| `STREAM_HEARTBEAT_INTERVAL` | `15` | SSE/WebSocket heartbeat seconds. |
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

Authentication is **opt-in and backward compatible**. The auth endpoints
(`/api/auth/*`, `/api/organizations/*`) are always available; global enforcement
on the data routes is off until you set `AUTH_ENABLED=true`.

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

- [ ] Strong `SECRET_KEY` / `JWT_SECRET`; never commit secrets.
- [ ] `AUTH_ENABLED=true` and TLS in front of the app.
- [ ] Restrict `CORS_ORIGINS` to your real dashboard origin(s).
- [ ] Managed PostgreSQL with backups; wipe defaults (`change-me-in-production`).
- [ ] Rate limiting enabled; consider a shared store for multi-worker limits.
- [ ] Review enabled plugins and provider credentials.

## Upgrades

Releases are additive and backward compatible across `v0.1 → v1.0`. Pull the new
images/code and restart; existing data and APIs continue to work. See
[CHANGELOG.md](../CHANGELOG.md).
