# Tracing

Tracing is the foundation of AgentScope. A **trace** is one captured LLM request;
an **agent run** groups the steps, tool calls, memory accesses and retriever
calls behind that request into a tree.

There are two ways to produce traces:

1. **The `agentscope-lite` SDK** — decorate/scope code in your app and ship
   traces to the server. Best for new code. See [SDK](../reference/sdk.md).
2. **The backend `TraceRecorder`** — a server-side recorder used when your
   application runs inside (or alongside) the backend. Best for rich agent/RAG
   trees persisted directly.

## What a trace captures (v0.1)

| Field | Description |
| ----- | ----------- |
| `user_prompt`, `system_prompt` | The prompts sent to the model. |
| `model_name` | The model identifier. |
| `input_tokens`, `output_tokens`, `total_tokens` | Token usage. |
| `estimated_cost` | Per-model cost estimate. |
| `latency_ms` | Request latency (recorded automatically). |
| `retrieved_documents`, `tool_calls` | Optional RAG/tool metadata. |
| `final_response` | The model's answer. |
| `status` | `success` / `failed`. |

## Capturing a request with the SDK

```python
import agentscope
from agentscope import trace

agentscope.configure(service_name="my-app", endpoint="http://localhost:8000")

# Decorator: every call becomes a traced span.
@trace("generate", kind="llm", model="gpt-4o")
def generate(prompt):
    resp = call_model(prompt)
    return resp

# Context manager: scope an arbitrary block and attach data.
with trace("retrieval", kind="retriever") as span:
    docs = search(query)
    span.set_output(docs)

# Manual: full control over lifecycle.
span = trace.start("generation", kind="llm", model="gpt-4o")
span.set_output(text).set_tokens(input=12, output=40).set_cost(0.001)
trace.end(span)
```

Exceptions inside a traced scope mark the span **failed** (recording the error)
and are re-raised unchanged. Full API in the [SDK reference](../reference/sdk.md).

## Capturing with the backend TraceRecorder

```python
from app.middleware.logging import TraceRecorder

with TraceRecorder("gpt-4o", user_prompt=prompt, system_prompt=system) as trace:
    resp = call_your_model(prompt)
    trace.update(
        final_response=resp.text,
        input_tokens=resp.usage.prompt_tokens,
        output_tokens=resp.usage.completion_tokens,
    )
# Latency, status and cost are recorded automatically and persisted.
```

## Agent execution tracing (v0.2)

A single request often runs several steps — planning, memory lookup, retrieval,
tool calls, generation, verification. `TraceRecorder` records this as an
**agent run** with ordered **steps** and typed side effects.

```python
from app.utils.trace_recorder import TraceRecorder

trace = TraceRecorder(request_id)
run = trace.start_agent(name="Planner", type="planner")

step = trace.add_step(run=run, step_type="reasoning", input="...", output="...")
trace.record_tool(step, name="search", arguments={"q": "..."}, result=[...])
trace.record_memory(step, query="user prefs", retrieved_text="...", used=True)
trace.record_retriever(step, query="...", documents=[...])
trace.finish_step(step)

trace.finish_agent(run)
```

Everything is timestamped, latency is computed automatically, status is tracked,
and the recorder is exception-safe. Nested/parent-child runs are supported for
multi-agent trees.

Inspect it via the dashboard (**Agent Runs**) or the API:

- `GET /api/agent-runs` — list runs (pagination, search, sort, filter).
- `GET /api/agent-runs/:id` — steps, tools, memory, retriever, timeline.
- `GET /api/dashboard/agent-metrics` — aggregate metrics.

## RAG Observatory (v0.3)

For retrieval-augmented apps, AgentScope records the whole RAG pipeline:
embeddings, vector search, retrieved documents (with similarity scores and which
were selected), reranking, and the fully **assembled prompt**.

```python
trace.record_embedding(step, model="text-embedding-3-small", text="...", dimensions=1536)
trace.record_retrieved_document(step, content="...", similarity=0.83, selected=True)
trace.record_prompt_assembly(step, system_prompt="...", user_prompt="...",
                             retrieved_context="...", final_prompt="...")
```

Or use the vendor-neutral `RetrievalService`, which records embeddings, vector
search, selected/rejected documents and prompt assembly for you — with adapters
for **Chroma, FAISS, Pinecone and Qdrant**.

API:

- `GET /api/retrievals` / `GET /api/retrievals/:id`
- `GET /api/prompts/:id` — the reconstructed prompt, section by section.
- `GET /api/dashboard/rag-metrics`

## Real-time streaming (v0.6)

Every tracing event is also broadcast live over Server-Sent Events and
WebSockets, powering the **Live** dashboard. Subscribe to `trace.*`, `agent.*`,
`step.*`, `tool.*`, `retriever.*`, `memory.*`, `workflow.updated` and
`evaluation.finished`:

```bash
curl -N http://localhost:8000/api/stream            # SSE stream
curl http://localhost:8000/api/stream/info          # connection info
```

See the [REST API](../reference/rest-api.md#streaming-v06) for stream details.

## Next

- Group agents into [Workflows](workflows.md).
- Re-run captured conversations with [Replay](replay.md).
