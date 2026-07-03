# Troubleshooting

Fixes for common problems. If something isn't here, check the logs
(`docker compose logs -f backend`) and the [FAQ](faq.md).

## Server & Docker

### Port 5000 is already in use (macOS)

macOS reserves port 5000 for AirPlay Receiver. AgentScope's backend defaults to
**5001**. If you changed it, either free the port or set `PORT` to another value.

### `docker compose up` fails to start the backend

- The backend waits for the database's healthcheck. Give it a few seconds, then
  check `docker compose logs -f db`.
- Ensure nothing else is bound to `5001`, `8080` or `5432`.
- Rebuild cleanly: `docker compose down -v && docker compose up -d --build`.

### The dashboard loads but shows no data / API calls fail

- Confirm the backend is healthy: `curl http://localhost:5001/api/health`.
- Check `CORS_ORIGINS` includes your dashboard origin (e.g. `http://localhost:8080`
  in Docker, `http://localhost:5173` for the Vite dev server).
- In Docker, the frontend proxies `/api` to the backend via nginx — check
  `docker compose logs -f frontend`.

### Database connection errors

- Verify `DATABASE_URL`. The `postgres://` scheme is auto-normalized to
  `postgresql://`; a bad host/credentials will surface here.
- Without `DATABASE_URL`, a local SQLite file is used — fine for dev.

### Cascade deletes don't work on SQLite

SQLite enforces foreign keys only when the pragma is on. AgentScope enables
`PRAGMA foreign_keys=ON` automatically; if you connect with another tool, enable
it yourself.

## SDK

### My traces don't appear on the server

- Call `agentscope.configure(endpoint="http://localhost:5001")` **before** the
  traced code runs; without an endpoint, traces stay in memory only.
- Check reachability from where your app runs (containers can't reach
  `localhost` of the host — use the service name or host IP).
- If `AUTH_ENABLED=true`, pass a valid `api_key`.
- Enable `console=True` to confirm traces are being produced locally.

### `ModuleNotFoundError: No module named 'agentscope'`

Install the SDK (`pip install agentscope-lite`) or run the example scripts from
the repo root (they add `sdk/` to `sys.path`).

### Parallel workflow step raises "takes 0 positional arguments but 1 was given"

Each parallel branch receives the workflow input. Make branch callables accept
one argument (see [`examples/02_agent_tool_workflow.py`](../examples/02_agent_tool_workflow.py)).

### An exception "disappeared" inside a traced block

It didn't — a traced scope marks the span **failed**, records the error, and
**re-raises** unchanged. Check your own error handling upstream.

## CLI

### `agentscope: command not found`

Ensure the SDK is installed and its scripts directory is on your `PATH`, or run
`python -m agentscope` instead.

### CLI can't reach the server

Run `agentscope doctor` to diagnose connectivity. Set the endpoint with
`agentscope config set endpoint http://localhost:5001` or pass `--endpoint`.

### No color in the output

Color auto-enables on TTYs and honors `NO_COLOR`. Force it with `--color`, or
disable with `--no-color`.

## Auth

### 401 Unauthorized

Send `Authorization: Bearer <access_token>` (users) or `X-API-Key: <key>`
(services). Access tokens expire (default 15 min) — refresh with
`POST /api/auth/refresh`.

### 403 Forbidden

Your role is insufficient, or you're accessing another organization/project. Roles
are `admin` > `developer` > `viewer`. You cannot grant a role higher than your own.

### 429 Too Many Requests

You hit a rate limit (auth endpoints are limited). Respect the `Retry-After`
header, or tune `RATE_LIMIT_DEFAULT` / `RATE_LIMIT_ENABLED`.

### "cannot remove the last admin of an organization"

Every organization must keep at least one admin. Promote another member first.

## Plugins & providers

### A plugin won't enable

Check its dependencies: plugin `dependencies` (other plugins, version-pinned) and
`requires` (Python packages) must be satisfied. Errors name the unmet
requirement. Disabling a plugin cascades to its dependents.

### A provider health check fails

`GET /api/providers/:name/health` reflects reachability and credentials. Set the
provider's API key (via its `api_key_env`) and verify network access. Local
providers like Ollama need the local server running.

## Tests

### `No module named pytest`

Use the virtualenv's interpreter: `.venv/bin/python -m pytest` from `backend/`.
