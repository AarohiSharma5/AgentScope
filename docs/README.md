# AgentScope Documentation

**Chrome DevTools for AI applications.** AgentScope is an open-source platform for
observing, debugging, replaying and evaluating LLM-powered apps — from a single
request all the way up to multi-agent workflows.

This is the complete documentation. If you are new, start with
[Getting Started](getting-started.md) → [Installation](installation.md) →
[Quick Start](quickstart.md).

## Contents

### Getting started
- [Getting Started](getting-started.md) — what AgentScope is and how the pieces fit together.
- [Installation](installation.md) — every install path: Docker, backend, frontend, SDK, CLI.
- [Quick Start](quickstart.md) — capture your first trace in five minutes.

### Guides
- [Tracing](guides/tracing.md) — requests, agent runs, steps, tools, memory, RAG.
- [Workflows](guides/workflows.md) — orchestrate agents and run JSON-defined graphs.
- [Replay](guides/replay.md) — re-run any conversation under new models/params.
- [Evaluation](guides/evaluation.md) — score conversations with pluggable evaluators.
- [Providers](guides/providers.md) — vendor-neutral LLM/embedding/retriever/memory/tool providers.
- [Plugins](guides/plugins.md) — extend the platform without touching core code.

### Reference
- [REST API](reference/rest-api.md) — every endpoint, request/response envelope.
- [Python SDK](reference/sdk.md) — `agentscope-lite` (`trace`, `Agent`, `Workflow`, `Tool`).
- [CLI](reference/cli.md) — the `agentscope` command.
- [Architecture](reference/architecture.md) — diagrams of the whole system.

### Operations
- [Deployment](deployment.md) — production deployment, config, auth, scaling.
- [Docker](docker.md) — the containerized stack in depth.
- [CI/CD](ci-cd.md) — GitHub Actions pipelines: tests, lint, security, releases.

### Help
- [Examples](../examples/README.md) — runnable example programs.
- [FAQ](faq.md) — frequently asked questions.
- [Troubleshooting](troubleshooting.md) — fixes for common problems.

## The layers of observability

AgentScope grew in layers; every layer shares one `TraceRecorder` SDK, one
service layer and one dashboard.

| Version | Capability |
| ------- | ---------- |
| **v0.1** | Request tracing — prompts, tokens, cost, latency, status. |
| **v0.2** | Agent execution tracing — run trees, steps, tools, memory, retrievers. |
| **v0.3** | RAG Observatory — embeddings, vector search, retrieved docs, prompt assembly. |
| **v0.4** | Multi-agent workflows — orchestrator, workflow engine, agent messaging. |
| **v0.5** | Replay, evaluation & comparison — plus prompt/trace diffs and analytics. |
| **v0.6** | Real-time streaming, plugin system, provider abstraction, export/import, live dashboard. |
| **v1.0** | `agentscope-lite` Python SDK, `agentscope` CLI, authentication & multi-tenancy. |

## The three ways to use AgentScope

1. **Instrument your app with the SDK** (`pip install agentscope-lite`) and ship
   traces to the server — see [SDK](reference/sdk.md).
2. **Call the REST API directly** from any language — see [REST API](reference/rest-api.md).
3. **Drive everything from the CLI** (`agentscope`) — see [CLI](reference/cli.md).

Everything is backward compatible: newer layers never break older ones, and
authentication is opt-in.
