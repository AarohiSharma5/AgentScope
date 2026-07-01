# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.3.0]: https://github.com/your-org/agentscope/releases/tag/v0.3.0
[0.2.0]: https://github.com/your-org/agentscope/releases/tag/v0.2.0
[0.1.0]: https://github.com/your-org/agentscope/releases/tag/v0.1.0
