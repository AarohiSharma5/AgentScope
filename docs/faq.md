# FAQ

### What is AgentScope?

An open-source observability platform for AI applications — "Chrome DevTools for
AI apps". It captures prompts, tokens, cost, latency, tool calls, retrieved
documents and agent hand-offs, and lets you inspect, replay and evaluate them.
See [Getting Started](getting-started.md).

### Do I need to seed sample data to use it?

No. Seeding is only for exploring the dashboard before you have real data. Point
the SDK (or a raw `POST /api/traces`) at a running server and your real requests
appear immediately.

### Does it require PostgreSQL?

No. The backend defaults to a local SQLite file with zero configuration, which is
great for development. Use PostgreSQL (`DATABASE_URL`) for production. Both are
fully supported.

### Is the SDK tied to a specific LLM provider?

No. The SDK (`agentscope-lite`) is dependency-free and vendor-neutral — model
names are opaque strings. The server's [provider abstraction](guides/providers.md)
ships adapters for nine providers, and you can add more without touching core
code.

### What's the difference between the SDK and the backend `TraceRecorder`?

- **`agentscope-lite`** is the client library you install in your app
  (`pip install agentscope-lite`) to trace and ship data to the server.
- **`TraceRecorder`** is the server-side recorder used when your code runs inside
  (or alongside) the backend and persists rich agent/RAG trees directly.

Both produce the same kind of traces. See [Tracing](guides/tracing.md).

### How do replays work if I don't want to call a real model?

Replays run in **mock** mode by default: original outputs and tool results are
replayed as-is and cost is re-estimated for the new model — fast, deterministic
and free. Pass `live=True` with handlers to invoke fresh logic. See
[Replay](guides/replay.md).

### Which evaluation metrics are built in?

Ten rule-based metrics (correctness, groundedness, faithfulness, context
precision/recall, answer relevance, tool success, memory usage, latency and cost
scores), plus LLM-as-a-Judge and custom evaluators. See
[Evaluation](guides/evaluation.md).

### Is LLM-as-a-Judge locked to a provider?

No. You supply any `judge(prompt)` callable, so you choose the model. There is no
hard dependency on any provider.

### How do I extend the platform?

Write a [plugin](guides/plugins.md) (custom tools, evaluators, memories,
retrievers, LLM providers or UI extensions) or add a
[provider adapter](guides/providers.md). Both self-register — no core changes.

### Is authentication required?

No. Auth is **opt-in and backward compatible**. The auth endpoints are always
available, but global enforcement on the data routes is off until you set
`AUTH_ENABLED=true`. See [Deployment](deployment.md#authentication--multi-tenancy).

### What are the roles?

`admin` > `developer` > `viewer`, scoped per organization. Organizations and
projects are isolated from each other. See the
[REST API auth section](reference/rest-api.md#authentication--tenancy-v10).

### How do I stream traces live?

Subscribe to `/api/stream` (Server-Sent Events) or `/api/ws` (WebSocket). The
**Live** dashboard uses these. See [Tracing](guides/tracing.md#real-time-streaming-v06).

### Can I export my data?

Yes — to OpenTelemetry (GenAI semantic conventions), JSON, CSV, SQLite,
PostgreSQL, Zip or a canonical Trace Bundle, and import it back (including replay
from an export). See the [REST API](reference/rest-api.md#export--import-v06).

### Is it backward compatible across versions?

Yes. Every layer (v0.1 → v1.0) is additive; newer features never break older
APIs, and both SQLite and PostgreSQL remain supported.

### Where do I report issues?

On the [GitHub repository](https://github.com/AarohiSharma5/AgentScope).
