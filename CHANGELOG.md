# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-01

First MVP release of **AgentScope** — the AI Request Tracer.

### Added

- **Trace data model** capturing 13 fields per LLM request: user prompt, system
  prompt, model name, timestamp, input/output/total tokens, estimated cost,
  latency, retrieved documents, tool calls, final response, and status.
- **REST API** (Flask) with endpoints:
  - `POST /api/traces` — ingest a trace
  - `GET /api/traces` — list traces (most recent first, paginated)
  - `GET /api/traces/:id` — fetch a single trace
  - `GET /api/stats` — aggregate dashboard metrics
  - `GET /api/health` — health check
- **Trace service layer** with automatic cost estimation from a per-model price
  table and aggregate stats (total requests, average latency, average tokens,
  average cost, success rate).
- **`TraceRecorder` middleware** — a context manager that automatically captures
  latency and success/failure status around an LLM call and persists it.
- **HTTP request logging** hooks for basic access logging.
- **React + TailwindCSS frontend** with a dark, developer-tool UI:
  - Dashboard with 5 metric cards and a table of all requests.
  - Trace detail page showing every captured field.
- **PostgreSQL** support via SQLAlchemy (with a zero-config SQLite fallback for
  local development).
- **Dockerized stack** — `docker compose up` starts PostgreSQL, the Flask
  backend (gunicorn), and the React frontend (nginx) together.
- **Documentation**: README, architecture diagram, screenshots, and seed script.

[0.1.0]: https://github.com/your-org/agentscope/releases/tag/v0.1.0
