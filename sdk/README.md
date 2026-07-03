# agentscope-lite

A lightweight, **dependency-free** tracing SDK for AI agents, tools and workflows —
the official Python client for the [AgentScope](https://github.com/AarohiSharma5/AgentScope)
observability platform.

Instrument your app with a **decorator**, a **context manager**, or **manual**
calls, and stream traces to a running AgentScope server (or just inspect them
locally). The SDK uses only the Python standard library, so it drops into any
project without pulling in a heavy dependency tree.

## Install

```bash
pip install agentscope-lite
```

The import name is `agentscope`:

```python
from agentscope import trace, Agent, Workflow, Tool
```

## Configure

Configuration is optional — without it, traces are kept in memory. Point the SDK
at a running AgentScope server to ship traces there.

```python
import agentscope

agentscope.configure(
    service_name="my-rag-app",
    endpoint="http://localhost:5001",  # AgentScope server (enables HTTP export)
    api_key="sk-...",                   # sent as Authorization: Bearer
    console=True,                        # also pretty-print each finished trace
)
```

Every option can also be set via environment variables: `AGENTSCOPE_ENDPOINT`,
`AGENTSCOPE_API_KEY`, `AGENTSCOPE_SERVICE_NAME`, `AGENTSCOPE_CONSOLE`,
`AGENTSCOPE_LOG`, `AGENTSCOPE_ENABLED`, `AGENTSCOPE_DEFAULT_MODEL`.

## Trace anything — three styles

```python
from agentscope import trace

# 1) Decorator — every call is traced automatically
@trace
def plan(question): ...

@trace("generate", kind="llm", model="gpt-4o")
def generate(prompt): ...

# 2) Context manager — scope an arbitrary block
with trace("retrieval", kind="retriever") as span:
    docs = search(q)
    span.set_output(docs)

# 3) Manual — full control
span = trace.start("generation", kind="llm", model="gpt-4o")
span.set_output(text).set_tokens(input=12, output=40).set_cost(0.001)
trace.end(span)
```

Exceptions inside a traced scope mark the span **failed** (recording the error)
and are re-raised unchanged.

## Agents, Tools and Workflows

```python
from agentscope import Agent, Tool, Workflow

search = Tool(lambda q: [f"doc:{q}"], name="search")

planner = Agent("Planner", role="planner", model="gpt-4o")

@planner
def plan(question):
    return search(question)     # nested tool span, automatically

# Compose a pipeline; output of each step feeds the next.
wf = Workflow("rag-pipeline")
wf.add(plan).add(lambda docs: f"answer from {docs}")

# Fan-out in parallel (runs concurrently, spans stay correctly nested).
wf.parallel(Tool(a), Tool(b), Tool(c))

answer = wf.run("What is AgentScope?")
```

## Inspect locally

```python
for t in trace.finished():
    print(t.name, t.status, t.latency_ms, t.total_tokens(), t.total_cost())
```

## Custom exporters

Implement `Exporter.export(trace)` and register it:

```python
from agentscope.exporters import Exporter

class MyExporter(Exporter):
    def export(self, trace):
        ...

trace.add_exporter(MyExporter())
```

Built-in exporters: `ConsoleExporter`, `LoggingExporter`, `MemoryExporter`,
`HTTPExporter` (ships to the AgentScope server).

## Compatibility

The public API — `trace`, `Agent`, `Workflow`, `Tool`, `configure` — is stable
across the `1.x` line.

## License

MIT © Aarohi Sharma
