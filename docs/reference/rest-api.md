# REST API Reference

The backend exposes a JSON REST API under `/api`. This is the complete endpoint
list across all versions.

## Conventions

- **Collections** return `{ "data": [...], "pagination": { page, limit, total, pages } }`.
- **Single resources** return the serialized object directly.
- **Created resources** return the object with HTTP `201`.
- **Errors** return `{ "error": message, "details": { ...optional } }` with the
  appropriate status code (`400`, `401`, `403`, `404`, `429`, `500`).
- List endpoints accept `page`, `limit` (max 100) and, where noted, `sort`,
  `search` and filter parameters.

Base URL in local development: `http://localhost:8000/api`.

## Health

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/api/health` | Liveness check. |

## Request tracing (v0.1)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| POST | `/api/traces` | Ingest a new trace. |
| GET | `/api/traces` | List traces (most recent). |
| GET | `/api/traces/:id` | Get a single trace. |
| GET | `/api/stats` | Aggregate dashboard metrics. |

**Ingest example**

```bash
curl -X POST http://localhost:8000/api/traces \
  -H "Content-Type: application/json" \
  -d '{"model_name":"gpt-4o","user_prompt":"Hi","input_tokens":10,
       "output_tokens":20,"final_response":"Hello!","latency_ms":420}'
```

## Agent execution tracing (v0.2)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| POST | `/api/agent-runs` | Ingest a full agent run (steps, tools, memory, retrievals). |
| GET | `/api/agent-runs` | List runs (pagination, search, sort, filter). |
| GET | `/api/agent-runs/:id` | Run detail: steps, tools, memory, timeline. |
| GET | `/api/requests/:id/agent-runs` | All runs for a request. |
| GET | `/api/dashboard/agent-metrics` | Aggregate agent-execution metrics. |

Use `POST /api/agent-runs` to populate the **Agent Runs** view from an external
app (e.g. a chatbot). Pass `request_id` to attach the run to an existing trace,
or omit it to have a parent request trace created from the top-level fields
(`model_name`, `user_prompt`, `final_response`, token counts, ...). Nested
`retrievals` on a step also populate the RAG Observatory. Returns the created run
(same shape as `GET /api/agent-runs/:id`).

**Ingest example**

```bash
curl -X POST http://localhost:8000/api/agent-runs \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "Chatbot", "agent_type": "chatbot",
    "model_name": "gpt-4o", "user_prompt": "refund policy?",
    "final_response": "Refunds within 30 days.", "status": "success", "latency_ms": 900,
    "steps": [
      {"step_type": "retrieval", "name": "Retriever", "input": "refund policy",
       "retrievals": [{"query": "refund policy", "retrieval_time_ms": 22,
         "documents": [{"document_name": "Refund policy", "source": "kb",
                        "score": 0.95, "snippet": "Refunds within 30 days...", "selected": true}]}]},
      {"step_type": "llm", "name": "LLM Generation", "output": "Refunds within 30 days.",
       "token_usage": {"input": 120, "output": 18, "total": 138}, "cost": 0,
       "tool_calls": [{"tool_name": "search_kb", "arguments": {"q": "refund"}, "result": {"hits": 1}}]}
    ]
  }'
```

## RAG Observatory (v0.3)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| POST | `/api/retrievals` | Ingest a single retrieval (documents + embedding). |
| GET | `/api/retrievals` | List retrievals (pagination, search, sort, filter). |
| GET | `/api/retrievals/:id` | Retrieval detail: embedding, docs, scores, prompt, timeline. |
| GET | `/api/prompts/:id` | Reconstructed prompt (all sections + final). |
| GET | `/api/dashboard/rag-metrics` | Aggregate RAG metrics. |

`POST /api/retrievals` is a convenience for logging a standalone retrieval so it
appears in the **RAG Observatory** (it is wrapped in a thin run + step, since
retrievals hang off agent steps). Accepts the same optional `request_id` /
parent-trace fields as `POST /api/agent-runs`.

**Ingest example**

```bash
curl -X POST http://localhost:8000/api/retrievals \
  -H "Content-Type: application/json" \
  -d '{"query": "password reset", "retrieval_time_ms": 18,
       "documents": [{"document_name": "Reset guide", "source": "kb",
                      "score": 0.9, "chunk_text": "Go to settings...", "selected": true}],
       "embedding": {"model": "text-embedding-3-small", "dimension": 1536}}'
```

## OpenTelemetry ingest (OTLP/HTTP JSON)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| POST | `/api/otel/v1/traces` | Ingest OTLP/HTTP JSON traces; GenAI spans become agent runs. |

Any OpenTelemetry-instrumented app can push GenAI traces to AgentScope over the
standard **OTLP/HTTP JSON** protocol — no AgentScope SDK required. It understands
the common conventions: **OTel GenAI semconv** (`gen_ai.*`), **OpenLLMetry**
(`gen_ai.*` / `llm.*` / `traceloop.span.kind`), and **OpenInference**
(`*.value` / `llm.token_count.*` / `openinference.span.kind`).

Each OTLP trace becomes one **agent run**; each span becomes a step, classified
as `llm` (with model, prompt, completion, token usage and priced cost), `tool`,
`retrieval`, or a generic step. Point your exporter at the endpoint:

```bash
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:8000/api/otel/v1/traces
OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/json
```

It returns HTTP 200 with an OTLP-style `{"partialSuccess": {}}` object (so
standard OTLP clients are satisfied) plus an accept summary
(`accepted_spans`, `accepted_traces`, `runs`). Rate-limited like other ingest
endpoints; server-side redaction (`INGEST_REDACT`) applies here too.

## Multi-agent workflows (v0.4)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/api/workflows` | List workflow definitions. |
| GET | `/api/workflows/:id` | Workflow detail: nodes, edges, execution history. |
| GET | `/api/conversations` | List conversation runs. |
| GET | `/api/conversations/:id` | Conversation detail: agent tree, messages, timeline, steps. |
| GET | `/api/messages` | List messages (filter by sender, receiver, conversation, search). |
| GET | `/api/dashboard/workflow-metrics` | Aggregate multi-agent metrics. |

## Replay, evaluation & comparison (v0.5)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/api/replays` | List replay runs. |
| POST | `/api/replays` | Replay a conversation under new model/params. |
| GET | `/api/replays/:id` | Replay run detail. |
| GET | `/api/evaluations` | List evaluation runs. |
| POST | `/api/evaluations` | Run an evaluation over a conversation. |
| GET | `/api/evaluations/:id` | Evaluation run detail (with metrics). |
| GET | `/api/comparisons` | List model comparisons. |
| POST | `/api/comparisons` | Compare a conversation across multiple models. |
| GET | `/api/prompt-versions` | List auto-captured prompt versions (filter by `agent_run_id`). |
| GET | `/api/prompt-versions/:id` | Single prompt version. |
| GET | `/api/prompt-diff?a=&b=` | Word-level diff of two prompt versions. |
| GET | `/api/trace-diff?a=&b=` | Diff two traced conversations. |
| GET | `/api/dashboard/evaluation-metrics` | Aggregate evaluation metrics. |
| GET | `/api/dashboard/evaluation-analytics` | Daily time-series analytics + headline rates. |

## Streaming (v0.6)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/api/stream` | Server-Sent Events stream of live events. |
| GET | `/api/stream/info` | Stream/connection metadata. |
| WS  | `/api/ws` | WebSocket stream (when `flask-sock` is installed). |

The SSE stream supports the `Last-Event-ID` header for automatic reconnect and
topic filtering via query parameters. Event types:

```
trace.started  trace.updated  trace.finished
agent.started  agent.finished  step.started  step.finished
tool.started   tool.finished   retriever.started  retriever.finished
memory.started memory.finished workflow.updated  evaluation.finished
heartbeat
```

**Subscribe**

```bash
curl -N http://localhost:8000/api/stream
```

## Plugins (v0.6)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/api/plugins` | List installed plugins. |
| GET | `/api/plugins/extensions` | List contributed extensions. |
| GET | `/api/plugins/:name` | Plugin detail. |
| POST | `/api/plugins/:name/enable` | Enable a plugin (cascades to dependents). |
| POST | `/api/plugins/:name/disable` | Disable a plugin (cascades to dependents). |
| POST | `/api/plugins/:name/reload` | Reload a plugin. |
| DELETE | `/api/plugins/:name` | Uninstall a plugin. |

## Providers (v0.6)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/api/providers` | List providers with info. |
| GET | `/api/providers/capabilities` | Capability matrix across providers. |
| GET | `/api/providers/:name` | One provider's info. |
| GET | `/api/providers/:name/health` | Provider health/reachability. |

## Export / Import (v0.6)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/api/export/formats` | Supported export formats. |
| GET | `/api/export/kinds` | Exportable entity kinds. |
| GET | `/api/export/analytics` | Export analytics data. |
| GET | `/api/export/:kind/:id` | Export a conversation/workflow/replay/evaluation. |
| POST | `/api/import` | Import a bundle into the database. |
| POST | `/api/import/inspect` | Inspect a bundle without importing. |
| POST | `/api/import/replay` | Replay directly from an imported bundle. |

Formats include OpenTelemetry (OTLP/JSON, GenAI semantic conventions), JSON, CSV,
SQLite, PostgreSQL, Zip archive and the canonical Trace Bundle.

## Authentication & tenancy (v1.0)

Authentication endpoints are always available; global enforcement on the data
routes above is opt-in via `AUTH_ENABLED`. Authenticate with
`Authorization: Bearer <jwt>` or `X-API-Key: <key>`.

**Tenant isolation (phase 1).** When auth is enabled and a request is made with
an **org-bound API key**, ingested requests/conversations are stamped with that
key's organization, and the traces and conversations list/detail endpoints
return only that organization's data. JWT/dashboard users are not tenant-scoped
(a user may belong to several organizations). Data written without an org-bound
key (or with auth disabled) has no organization and is visible to unscoped
callers, preserving single-tenant behavior.

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| POST | `/api/auth/register` | Create a user + first organization (admin). |
| POST | `/api/auth/login` | Exchange email/password for tokens. |
| POST | `/api/auth/refresh` | Exchange a refresh token for a new pair. |
| GET | `/api/auth/me` | Current principal + memberships. |
| POST | `/api/auth/change-password` | Change the current user's password. |
| GET | `/api/organizations` | List organizations you belong to. |
| POST | `/api/organizations` | Create an organization. |
| GET | `/api/organizations/:id` | Organization detail. |
| GET/POST | `/api/organizations/:id/members` | List / add members (admin). |
| PATCH/DELETE | `/api/organizations/:id/members/:user_id` | Change role / remove (admin). |
| GET/POST | `/api/organizations/:id/projects` | List / create projects. |
| GET | `/api/projects/:id` | Project detail. |
| GET/POST | `/api/organizations/:id/api-keys` | List / create API keys. |
| DELETE | `/api/organizations/:id/api-keys/:key_id` | Revoke an API key (admin). |
| GET | `/api/organizations/:id/audit-logs` | Audit log (admin). |

**Roles:** `admin` > `developer` > `viewer`. Auth endpoints are rate limited; see
the [Deployment](../deployment.md#authentication--multi-tenancy) guide.

**Register example**

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@acme.test","password":"password123","organization_name":"Acme"}'
```

See the runnable [`examples/09_auth_api_keys.py`](../../examples/09_auth_api_keys.py).
