# Release Notes — v1.0.0

**AgentScope v1.0.0** is the first stable, production-ready release. It marks the
point where AgentScope grew from a single web application into a full
observability **platform** for AI agents, tools and workflows — with an
installable SDK, a first-class CLI, authentication, complete documentation,
CI/CD, and a performance pass designed to scale to millions of traces.

> **100% backward compatible.** Every REST endpoint, database schema and
> frontend page from v0.1–v0.6 is unchanged. Upgrading is drop-in — see the
> [Migration Guide](migration.md).

## Highlights

### Install it anywhere — the `agentscope-lite` SDK
```bash
pip install agentscope-lite
```
```python
from agentscope import trace, Agent, Workflow, Tool

@trace
def answer(q): ...
```
Dependency-free, async/thread-safe (via `contextvars`), with decorator,
context-manager and manual tracing, environment-based configuration, and
pluggable exporters (Console, Memory, Logging, HTTP → your AgentScope server).

### Drive it from the terminal — the `agentscope` CLI
`init`, `start`, `trace`, `replay`, `evaluate`, `compare`, `plugins`,
`providers`, `export`, `import`, `config`, `doctor`, `status`, `version`, plus an
interactive shell. Colored, cross-platform output and `docker compose`
auto-detection.

### Secure it — authentication & multi-tenancy
Organizations, projects, users, API keys and RBAC (Admin/Developer/Viewer) with
JWT auth, hashed passwords and API keys, org/project isolation, rate limiting and
audit logs. **Off by default** (`AUTH_ENABLED=false`) so existing deployments are
untouched; opt in when you're ready.

### Scale it — performance
Connection pooling, composite indexes, single-pass dashboard aggregations, a
metrics cache, bounded counts + keyset pagination, a bounded background job
manager, cached stream serialization and memoized frontend rows. See the
[Performance guide](performance.md) and the bundled benchmark harness.

### Extend it — plugins & providers (from v0.6)
A full plugin system and a vendor-neutral provider abstraction (OpenAI,
Anthropic, Gemini, Ollama, OpenRouter, Azure, Groq, DeepSeek, Mistral) let you
add capabilities and models without changing core code.

### Watch it live — streaming & live dashboard (from v0.6)
Real-time SSE/WebSocket event streaming and a live dashboard with auto-updating
tables, timeline and execution graph.

## Quality gates

- **441 automated tests** — backend (345), frontend (55), SDK (41) — all green.
- **CI/CD** on Linux, macOS and Windows: Ruff lint, Bandit + pip-audit + CodeQL
  security scanning, coverage, frontend build, Docker image builds.
- **SQLite and PostgreSQL** both verified; Dockerized end-to-end.

## Install / upgrade

```bash
# Server (Docker)
docker compose up --build

# Python SDK
pip install agentscope-lite

# From source
git clone https://github.com/AarohiSharma5/AgentScope.git
```

Existing PostgreSQL users: backfill the new indexes online with
`psql "$DATABASE_URL" -f backend/scripts/perf_indexes.sql`.

See the full, itemized change list in the [CHANGELOG](../CHANGELOG.md).

## License

Released under the [MIT License](../LICENSE).
