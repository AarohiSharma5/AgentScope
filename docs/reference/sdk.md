# Python SDK Reference — `agentscope-lite`

`agentscope-lite` is a **dependency-free** tracing SDK (Python standard library
only). Instrument your app with a decorator, a context manager or manual calls,
and either inspect traces locally or ship them to a running AgentScope server.

```bash
pip install agentscope-lite
```

```python
from agentscope import trace, Agent, Workflow, Tool
```

The public API — `trace`, `Agent`, `Workflow`, `Tool`, `configure` — is stable
across the `1.x` line.

## Configuration

Configuration is optional; without it, traces are kept in memory.

```python
import agentscope

agentscope.configure(
    service_name="my-rag-app",
    endpoint="http://localhost:8000",  # enables HTTP export to the server
    api_key="sk-...",                   # sent as Authorization: Bearer
    console=True,                        # also pretty-print each finished trace
)
```

| Option | Env var | Default | Meaning |
| ------ | ------- | ------- | ------- |
| `enabled` | `AGENTSCOPE_ENABLED` | `True` | Master on/off switch. |
| `service_name` | `AGENTSCOPE_SERVICE_NAME` | `"agentscope"` | Logical service name. |
| `endpoint` | `AGENTSCOPE_ENDPOINT` | *(none)* | Server URL; enables `HTTPExporter`. |
| `api_key` | `AGENTSCOPE_API_KEY` | *(none)* | Bearer token for the server. |
| `console` | `AGENTSCOPE_CONSOLE` | `False` | Pretty-print finished traces. |
| `log` | `AGENTSCOPE_LOG` | `False` | Emit traces as structured logs. |
| `default_model` | `AGENTSCOPE_DEFAULT_MODEL` | *(none)* | Default model attribute. |

## `trace` — three styles

```python
from agentscope import trace

# 1) Decorator — every call is traced automatically.
@trace
def plan(question): ...

@trace("generate", kind="llm", model="gpt-4o")
def generate(prompt): ...

# 2) Context manager — scope an arbitrary block.
with trace("retrieval", kind="retriever") as span:
    docs = search(q)
    span.set_output(docs)

# 3) Manual — full control.
span = trace.start("generation", kind="llm", model="gpt-4o")
span.set_output(text).set_tokens(input=12, output=40).set_cost(0.001)
trace.end(span)
```

Typed shortcuts: `trace.agent(...)`, `trace.tool(...)`, `trace.llm(...)`.

Exceptions inside a traced scope mark the span **failed** (recording the error)
and are re-raised unchanged. Decorators work on both sync and async functions.

### Span

A `Span` is the atomic unit, with fluent mutators:

| Attribute / method | Purpose |
| ------------------ | ------- |
| `name`, `kind`, `trace_id`, `span_id`, `parent_id` | Identity & hierarchy. |
| `status` | `RUNNING` / `SUCCESS` / `FAILED`. |
| `set_input(...)`, `set_output(...)` | Attach I/O. |
| `set_tokens(input=, output=)` | Record token usage. |
| `set_cost(...)` | Record cost. |
| `set_attributes(**kw)` / `set_error(...)` | Arbitrary attributes / errors. |

`SpanKind`: `TRACE`, `AGENT`, `WORKFLOW`, `STEP`, `TOOL`, `LLM`, `RETRIEVER`,
`MEMORY`. Span context is tracked with `contextvars`, so tracing is thread-safe
and async-safe.

## `Tool`

A traced, callable wrapper around a function.

```python
from agentscope import Tool

search = Tool(lambda q: [f"doc:{q}"], name="search")
docs = search("agentscope")     # recorded as a TOOL span

@Tool
def calculator(a, b): return a + b
```

## `Agent`

A named, traced unit of work that can own tools.

```python
from agentscope import Agent

planner = Agent("Planner", role="planner", model="gpt-4o")

@planner                        # decorate a function as the agent body
def plan(question):
    return search(question)     # nested tool span, automatically

# Or run inline / scope a session:
planner.run(plan, "question")
with planner.session():
    ...
```

## `Workflow`

Compose steps into a single traced execution; each step's output feeds the next.

```python
from agentscope import Workflow, Tool

wf = Workflow("rag-pipeline")
wf.add(plan).add(lambda docs: f"answer from {docs}")

# Fan-out in parallel (runs concurrently; spans stay correctly nested via
# contextvars.copy_context).
wf.parallel(Tool(a), Tool(b), Tool(c))

answer = wf.run("What is AgentScope?")

# Or register steps with a decorator:
@wf.step
def review(answer): ...
```

## Inspect locally

```python
for t in trace.finished():
    print(t.name, t.status, t.latency_ms, t.total_tokens(), t.total_cost())
```

## Exporters

Built-in: `ConsoleExporter`, `LoggingExporter`, `MemoryExporter` (bounded ring
buffer), `HTTPExporter` (ships to the server's `POST /api/traces`).

Write your own by implementing `Exporter.export(trace)`:

```python
from agentscope.exporters import Exporter

class MyExporter(Exporter):
    def export(self, trace):
        ...

trace.add_exporter(MyExporter())
```

## See also

- [Tracing guide](../guides/tracing.md) — concepts and the backend recorder.
- [CLI](cli.md) — the bundled `agentscope` command.
- Runnable examples: [`01_quickstart_trace.py`](../../examples/01_quickstart_trace.py),
  [`02_agent_tool_workflow.py`](../../examples/02_agent_tool_workflow.py),
  [`03_http_export.py`](../../examples/03_http_export.py).
