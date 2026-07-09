# Installation

AgentScope has three installable pieces:

| Piece | What it is | Install |
| ----- | ---------- | ------- |
| **Server** | Flask API + React dashboard + database | Docker (recommended) or manual |
| **SDK** | `agentscope-lite` — the Python client | `pip install agentscope-lite` |
| **CLI** | the `agentscope` command | bundled with the SDK |

## Requirements

- **Docker** & Docker Compose (for the one-command stack), **or**
- **Python 3.10+** and **Node.js 18+** for a manual install.
- PostgreSQL is optional — the backend falls back to a local SQLite file with
  zero configuration.

## Option A — the full stack with Docker (recommended)

From the repository root:

```bash
docker compose up -d --build
```

| Service | URL |
| ------- | --- |
| Frontend (dashboard) | http://localhost:8080 |
| Backend API | http://localhost:8000/api |
| PostgreSQL | localhost:5432 |

Optionally load sample data once:

```bash
docker compose exec backend python seed.py
```

See [Docker](docker.md) for a deeper reference. To stop:

```bash
docker compose down       # keep data
docker compose down -v    # wipe the database volume
```

## Option B — run the server manually

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # optional: set DATABASE_URL for PostgreSQL
python seed.py            # optional: load sample traces
python run.py             # http://localhost:8000
```

> The backend listens on **port 8000** by default (macOS reserves 5000 for
> AirPlay). Override with the `PORT` environment variable. Without
> `DATABASE_URL`, a local SQLite file is used.

### Frontend

```bash
cd frontend
npm install
npm run dev               # http://localhost:5173 (proxies /api to :8000)
```

## Option C — install the SDK

The SDK is dependency-free (standard library only) and works with or without a
running server.

```bash
pip install agentscope-lite
```

To install from the repository (editable):

```bash
cd sdk
pip install -e .
```

The import name is `agentscope`:

```python
from agentscope import trace, Agent, Workflow, Tool
```

Installing the package also provides the **CLI**:

```bash
agentscope version
python -m agentscope version   # equivalent
```

See [SDK](reference/sdk.md) and [CLI](reference/cli.md) for full references.

## Configuration overview

The server reads configuration from environment variables (or `backend/.env`):

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `DATABASE_URL` | *(SQLite file)* | PostgreSQL connection string. |
| `USE_MIGRATIONS` | `false` | Manage schema via Alembic (`alembic upgrade head`) instead of auto-create. |
| `PORT` | `8000` | Backend port. |
| `SECRET_KEY` | `dev-secret-key` | Flask secret. |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed dashboard origins. |
| `STREAM_HEARTBEAT_INTERVAL` | `15` | SSE/WebSocket heartbeat seconds. |
| `PLUGINS_AUTOLOAD` | `true` | Discover/enable plugins at startup. |
| `AUTH_ENABLED` | `false` | Enforce auth on data routes (opt-in). |
| `JWT_SECRET` | `SECRET_KEY` | JWT signing secret. |
| `JWT_ACCESS_TTL` / `JWT_REFRESH_TTL` | `900` / `2592000` | Token lifetimes (s). |
| `API_KEY_PREFIX` | `as` | Prefix for minted API keys. |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_DEFAULT` | `true` / `120/minute` | Rate limiting. |

The SDK reads `AGENTSCOPE_ENDPOINT`, `AGENTSCOPE_API_KEY`,
`AGENTSCOPE_SERVICE_NAME`, `AGENTSCOPE_CONSOLE`, `AGENTSCOPE_LOG`,
`AGENTSCOPE_ENABLED`, `AGENTSCOPE_DEFAULT_MODEL`. See [Deployment](deployment.md)
for production settings.
