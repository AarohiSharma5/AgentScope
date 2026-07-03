# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-07-03

The first **stable, production-ready** release. AgentScope graduates from a
web-app-only tool to a full platform: an installable Python SDK, a first-class
CLI, authentication and multi-tenancy, complete documentation, CI/CD, and a
performance pass built to scale to millions of traces. Fully backward compatible
with v0.1–v0.6 — every existing API and database is unchanged.

### Added

- **`agentscope-lite` Python SDK** (`sdk/`): a dependency-free, `pip install`-able
  package exposing `from agentscope import trace, Agent, Workflow, Tool`.
  Supports decorator, context-manager and manual tracing, `contextvars`-based
  async/thread-safe span context, configuration via `AGENTSCOPE_*` env vars, and
  pluggable exporters (Console, Memory, Logging, HTTP → `/api/traces`).
- **`agentscope` CLI**: `init`, `start`, `trace`, `replay`, `evaluate`,
  `compare`, `plugins`, `providers`, `export`, `import`, `config`, `doctor`,
  `status`, `version` plus an interactive shell. Colored, cross-platform output
  (Windows VT + `NO_COLOR`), a config wizard, and `docker compose` auto-detection.
- **Authentication & multi-tenancy**: `Organization`, `User`, `Membership`,
  `Project`, `ApiKey` and `AuditLog` models; JWT (stdlib HS256), pbkdf2 password
  hashing, hashed API keys, RBAC (Admin/Developer/Viewer), org/project isolation,
  in-memory rate limiting and audit logs. Opt-in and **off by default**
  (`AUTH_ENABLED=false`) so existing deployments are unaffected.
- **Complete documentation** (`docs/`): getting-started, installation,
  quickstart, tracing/workflows/replay/evaluation/providers/plugins guides,
  REST/SDK/CLI/architecture reference, deployment, Docker, performance, CI/CD,
  FAQ and troubleshooting — plus nine runnable examples and Mermaid diagrams.
- **CI/CD** (GitHub Actions): lint (Ruff), security (Bandit + pip-audit), CodeQL,
  cross-platform pytest matrix (Linux/macOS/Windows) with coverage, frontend
  build/tests, Docker image builds, and a release pipeline (PyPI via OIDC, GHCR,
  GitHub Releases). Dependabot for pip/npm/docker/actions.
- **Community & release files**: release notes, migration guide, contributing
  guide, Code of Conduct, security policy, and issue/PR templates.

### Performance

- **Connection pooling** for PostgreSQL (`pool_size`, `max_overflow`,
  `pool_recycle`, `pool_pre_ping`, LIFO reuse) — all env-tunable.
- **Composite indexes** on `traces` (`status,timestamp` / `model,timestamp`) plus
  `backend/scripts/perf_indexes.sql` to backfill existing databases online.
- **Single-pass dashboard aggregations** (5–7 queries collapsed to 1–2) and a
  short-TTL in-process **metrics cache** (`METRICS_CACHE_TTL`).
- **Bounded counts + keyset pagination** helpers for huge tables.
- **Bounded background job manager** (`BACKGROUND_WORKERS`) with
  `GET /api/jobs[/<id>]`, cached per-event stream serialization, and memoized
  frontend table rows.
- Benchmark harness (`backend/scripts/benchmark_api.py`) and
  [performance docs](docs/performance.md).

## [0.6.0] - 2026-07-03

Adds **real-time streaming, extensibility and portability**: live SSE/WebSocket
event streaming, a plugin system, a vendor-neutral provider abstraction, an
export/import subsystem, and a live-mode dashboard. Additive and backward
compatible with v0.1–v0.5.

### Added

- **Real-time streaming** (`streaming/`): a thread-safe `LiveTraceManager`
  pub/sub hub broadcasting trace/agent/step/tool/retriever/memory/workflow/
  evaluation events over **Server-Sent Events** (`/api/stream`) and **WebSocket**.
  Connection management, heartbeats, drop-newest backpressure with bounded
  per-subscriber queues, `Last-Event-ID` reconnection replay and graceful
  disconnect. Emission is exception-safe and never disrupts persistence.
- **Plugin system** (`plugins/`): `PluginManager`, `PluginRegistry`,
  `PluginLoader` and `PluginBase` supporting custom tools, evaluators, memories,
  retrievers, LLM providers and UI extensions. Full lifecycle (install, load,
  enable, disable, uninstall, reload) with auto-registration, metadata, semantic
  versioning, dependency checking and cascading enable/disable of dependents.
  Discovers packages, filesystem drop-ins and pip entry points. REST-managed.
- **Provider abstraction** (`providers/`): vendor-neutral `LLMProvider`,
  `EmbeddingProvider`, `RetrieverProvider`, `MemoryProvider` and `ToolProvider`
  interfaces exposing `chat()`, `embed()`, `stream()`, token counting, cost
  estimation and health checks, with discoverable capabilities. Adapters for
  OpenAI, Anthropic, Google Gemini, Ollama, OpenRouter, Azure OpenAI, Groq,
  DeepSeek and Mistral. New providers register without touching core code.
- **Export/import subsystem** (`exporting/`): export conversations, workflows,
  replays, evaluations and analytics to OpenTelemetry (OTLP/JSON, GenAI semantic
  conventions), JSON, CSV, SQLite, PostgreSQL, Zip archive and a portable
  **Trace Bundle**; importers reconstruct the database and support replay from
  exported traces.
- **Live-mode dashboard** (frontend): real-time updating tables, live timeline,
  streaming execution graph, and Running Conversations/Agents/Replays/Evaluations
  cards with live tokens/latency/cost. Reusable `useEventStream`/`useLiveState`
  hooks and `LiveTable`/`LiveTimeline`/`LiveExecutionGraph`/`LiveStatCard`
  components, with reconnect, pause/resume and topic filtering.

## [0.5.0] - 2026-07-03

Adds **replay, evaluation and model comparison** — re-run any traced
conversation under new parameters, score it with pluggable evaluators, compare
one workflow across many models, and diff prompts and traces. Built additively
on the v0.1–v0.4 tracing layers, with full backward compatibility.

### Added

- **Evaluation data model** (`evaluation_trace.py`): `ReplayRun`,
  `PromptVersion`, `EvaluationRun`, `EvaluationMetric` and `ModelComparison`,
  with relationships, cascade deletes and composite indexes.
- **Replay Engine** (`orchestration/replay_engine.py`): rebuilds a portable
  snapshot of a traced conversation and re-runs it via the Multi-Agent SDK,
  faithfully reusing workflow, agents, prompts, memory, retrieved documents and
  tool calls — while overriding model, temperature, `top_p`, system prompt,
  memory or tools. Runs **mock** (deterministic, cost re-estimated) or **live**
  (caller-supplied agent/tool handlers). Records a `ReplayRun` and can compare
  original vs replay.
- **Evaluation Engine** (`evaluation/`): pluggable `Evaluator` interface with 10
  built-in rule-based metrics (correctness, groundedness, faithfulness, context
  precision/recall, answer relevance, tool success, memory usage, latency and
  cost scores), an injectable **LLM-as-a-Judge**, and **custom** evaluators —
  with weighted overall scoring and synchronous / asynchronous execution.
- **Model Comparison Engine** (`comparison/`): runs one workflow against many
  models (replay + optional evaluation per model), stores pairwise
  `ModelComparison` records, and produces a ranking summary and side-by-side
  matrix. Provider-agnostic (model names are opaque strings).
- **Automatic prompt versioning + diffs** (`services/prompt_service.py`,
  `services/diff_service.py`): every assembled prompt is captured as a hashed,
  de-duplicated `PromptVersion`; word-level **prompt diffs** and full **trace
  diffs** (steps, tools, memory, retriever, latency, cost, tokens) power a
  side-by-side Diffs UI.
- **REST API**: `GET/POST /api/replays`, `GET /api/replays/:id`,
  `GET/POST /api/evaluations`, `GET /api/evaluations/:id`,
  `GET/POST /api/comparisons`, `GET /api/prompt-versions[/:id]`,
  `GET /api/prompt-diff`, `GET /api/trace-diff`,
  `GET /api/dashboard/evaluation-metrics`,
  `GET /api/dashboard/evaluation-analytics`.
- **Frontend**: Replays (list + detail with original-vs-replay diff),
  Evaluations (overall score, metric cards, radar chart, score history),
  Comparisons (side-by-side + winner), a Diffs page (split/unified prompt diff
  and trace diff), and an Analytics dashboard (daily cost / latency / tokens /
  evaluation score / failure rate) — with reusable Bar / Line / Radar charts.

### Changed

- Extended the frontend API client with a POST helper and the v0.5 endpoints;
  the navigation now wraps gracefully as sections grew.
- Reused the replay snapshot + conversation totals across the comparison and
  diff services, avoiding duplicated trace-reconstruction/aggregation logic.

### Tests

- Backend: replay engine (same/different model, temperature, system prompt,
  memory, mock & live tools, comparison), evaluation engine (all metrics,
  weighting, LLM-judge, custom, async, errors), comparison engine (multi-model,
  pairwise records, summary/side-by-side, provider-agnostic), prompt versioning
  and prompt/trace diff, and the full v0.5 REST API.
- Frontend: Vitest suites for the chart primitives, eval/diff components and the
  Diffs page (mocked client).
- Verified SQLite **and** PostgreSQL compatibility (`scripts/check_pg_v05.py`,
  now covering prompt/trace diff) and the full **Docker** stack end-to-end.

## [0.4.0] - 2026-07-01

Adds **multi-agent workflow orchestration** — coordinate collaborating agents,
run JSON-defined workflows, and trace typed agent-to-agent communication, built
additively on the v0.1–v0.3 tracing layers.

### Added

- **Workflow data model** (`workflow_trace.py`): `ConversationRun`, `AgentNode`
  (recursive parent/child tree), `AgentMessage` (with reply threading and
  conversation linkage), `WorkflowDefinition` and `WorkflowExecution`, with
  cascade / SET NULL behaviour and composite indexes.
- **Multi-Agent SDK** (`orchestration/`): `AgentOrchestrator`, `Agent`,
  `AgentContext` and `AgentRegistry` — nested parent/child agents, parallel
  execution, a shared context, conversation persistence and automatic
  timestamps / latency / status.
- **Workflow Engine** (`orchestration/engine.py`): executes JSON workflow
  definitions with sequential, parallel and conditional flow, retries, loops
  (bounded by `max_visits` / `max_steps`), overall and per-node timeouts, and
  cooperative cancellation. Every execution is traced automatically.
- **Agent communication layer** (`services/message_service.py`): typed messages
  (instruction, observation, question, answer, critique, tool result, memory
  result) with direct send, broadcast, reply threading, conversation history,
  search and timeline — every message records sender, receiver, timestamp,
  latency, token usage and metadata.
- **REST API**: `GET /api/workflows`, `GET /api/workflows/:id`,
  `GET /api/conversations`, `GET /api/conversations/:id`, `GET /api/messages`,
  `GET /api/dashboard/workflow-metrics`.
- **Workflows & Conversations frontend**: workflow list/detail with an
  interactive **execution graph** (DAG with zoom, pan, node selection, hover),
  agent tree, agent cards, a vertical timeline and a chat-like message viewer.

### Changed

- Extracted a shared sort helper (`utils/sorting.py`) and centralised
  page/limit validation (`utils/pagination.parse_page_limit`), removing the
  duplicated sort/pagination logic across the trace, RAG and workflow layers.
- Prevented N+1 queries in the workflow, conversation and message queries via
  `selectinload` eager-loading (verified with query-count tests).
- Extended `StatusBadge` and `AgentStatus` with `cancelled` and `timeout`
  states used by the workflow engine.

### Tests

- Backend: workflow-engine (sequential, parallel, retries, timeout,
  cancellation, loops), multi-agent SDK (creation, messaging, parent/child,
  nested/parallel execution, shared context), communication layer (send,
  broadcast, reply, history, search, timeline, N+1 guard) and workflow REST API
  (pagination, filtering, search, error handling).
- Frontend: Vitest suite covering the DAG layout, execution graph, agent
  tree/card, message viewer, timeline and tables.
- Verified SQLite **and** PostgreSQL compatibility (`scripts/check_pg_v04.py`).

## [0.3.0] - 2026-07-01

Adds the **RAG Observatory** — end-to-end observability for retrieval-augmented
generation, built additively on the v0.2 agent-tracing layer.

### Added

- **RAG data model** (`rag_trace.py`): `RetrievedDocument`, `EmbeddingTrace`
  (one-to-one with a retriever trace) and `PromptAssembly` (one-to-one with an
  agent run), with cascade deletes and performance indexes.
- **`TraceRecorder` v0.3 methods**: `record_embedding`, `record_retrieved_document`,
  `record_chunk`, `record_similarity`, `record_reranking`, and
  `record_prompt_assembly` — with automatic latency, token counting and cost
  estimation. Fully backward compatible with v0.2.
- **`RetrievalService`** — a vendor-neutral, fully traced retrieval pipeline with
  `EmbeddingProvider` / `VectorStore` interfaces and adapters for **Chroma,
  FAISS, Pinecone, Qdrant** (plus an in-memory store and offline hashing
  embedder). Every embedding, search, document and prompt assembly is persisted.
- **REST API**: `GET /api/retrievals`, `GET /api/retrievals/:id`,
  `GET /api/prompts/:id`, `GET /api/dashboard/rag-metrics`.
- **RAG Observatory frontend**: retrieval list, retrieval/embedding detail
  (embedding card, similarity chart, document viewer, timeline) and a prompt
  viewer with copy / expand-collapse / syntax highlighting.

### Changed

- Eliminated N+1 queries in the retrieval list/detail endpoints via `selectinload`
  eager-loading (verified with a query-count test).
- De-duplicated the paginated-collection envelope (`utils/pagination.py`) and the
  ISO datetime serializer (`serializers/common.py`) across route/serializer modules.
- Added structured logging across the v0.3 service functions and stronger input
  validation on the RAG endpoints.

### Tests

- Backend: v0.3 SDK, service-layer, retrieval-service, adapter and RAG API tests
  (including prompt reconstruction, embedding cost, and an N+1 guard).
- Frontend: Vitest + Testing Library suite covering the format helpers and the
  RAG components.
- Verified SQLite **and** PostgreSQL compatibility.

## [0.2.0] - 2026-07-01

Adds **Agent Execution Tracing** on top of the request tracer.

### Added

- **Agent-tracing data model**: `AgentRun` (self-referential run tree), `AgentStep`,
  `ToolExecution`, `MemoryAccess`, `RetrieverTrace`, with cascade deletes and
  composite indexes.
- **`TraceRecorder` SDK** for full agent-execution lifecycles: nested runs, steps,
  tool/memory/retriever sub-records, automatic timestamps, latency and status,
  exception-safe context managers, and high-level chatbot-flow helpers.
- **REST API**: `GET /api/agent-runs`, `GET /api/agent-runs/:id`,
  `GET /api/requests/:id/agent-runs`, `GET /api/dashboard/agent-metrics` — with
  pagination, search, sorting and filtering.
- **Chatbot flow integration** (`chat_service` + `POST /api/chat`) that traces the
  full Planner → Memory → Retriever → Tool → LLM → Verifier pipeline automatically.
- **Agent Runs frontend**: list and detail pages with a timeline, execution tree,
  and step/tool/memory/retriever cards.

### Changed

- Shared utilities for time, JSON validation and error envelopes; SQLite foreign-key
  enforcement; consistent response formats.

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

[1.0.0]: https://github.com/AarohiSharma5/AgentScope/releases/tag/v1.0.0
[0.6.0]: https://github.com/AarohiSharma5/AgentScope/releases/tag/v0.6.0
[0.5.0]: https://github.com/AarohiSharma5/AgentScope/releases/tag/v0.5.0
[0.4.0]: https://github.com/AarohiSharma5/AgentScope/releases/tag/v0.4.0
[0.3.0]: https://github.com/AarohiSharma5/AgentScope/releases/tag/v0.3.0
[0.2.0]: https://github.com/AarohiSharma5/AgentScope/releases/tag/v0.2.0
[0.1.0]: https://github.com/AarohiSharma5/AgentScope/releases/tag/v0.1.0
