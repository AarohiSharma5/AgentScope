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
    endpoint="http://localhost:8000",  # AgentScope server (enables HTTP export)
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

## Auto-instrument LLM SDKs

Wrap your provider client once and every completion is traced automatically —
prompt, response text, token usage and estimated cost — including **streaming**
and **async** calls. No decorators or context managers needed.

```python
import agentscope

# OpenAI (openai>=1.0) — sync OpenAI or async AsyncOpenAI
from openai import OpenAI
client = agentscope.instrument_openai(OpenAI())

# Anthropic (anthropic>=0.20) — sync Anthropic or async AsyncAnthropic
from anthropic import Anthropic
claude = agentscope.instrument_anthropic(Anthropic())

# Gemini (google-generativeai) — instrument the model instance
import google.generativeai as genai
model = agentscope.instrument_gemini(genai.GenerativeModel("gemini-1.5-pro"))
```

Each returns the same client (patched in place) and is **idempotent** — calling
it twice is a no-op, so it's safe at import time.

### Local & OpenAI-compatible providers (Ollama, vLLM, Groq, Together, …)

Anything that speaks the OpenAI Chat Completions API is covered by
`instrument_openai` — just point the OpenAI client at its `base_url`:

```python
from openai import OpenAI

# Ollama (local)
ollama = agentscope.instrument_openai(
    OpenAI(base_url="http://localhost:11434/v1", api_key="ollama"),
    prices={"llama3.2": (0, 0)},          # local = free; avoids "unpriced"
)

# vLLM (self-hosted OpenAI server)
vllm = agentscope.instrument_openai(
    OpenAI(base_url="http://localhost:8000/v1", api_key="x"),
    prices={"my-finetune": (0.0002, 0.0006)},
)

# Groq
groq = agentscope.instrument_openai(
    OpenAI(base_url="https://api.groq.com/openai/v1", api_key="gsk_..."),
    prices={"llama-3.1-70b-versatile": (0.00059, 0.00079)},
)
```

The optional `prices` argument (USD per 1K tokens as `{model: (input, output)}`)
extends the built-in price table so your own/self-hosted/local models are costed
too. Models with no known price still record token counts — cost is simply shown
as **unpriced** rather than a misleading `$0`.

## Framework integrations (LangChain & LlamaIndex)

If you build on a framework, you don't call the LLM SDK directly — the framework
runs the agent loop for you. Register one callback handler and the whole run
(chains/queries, LLM calls, tools, retrievers) is captured as a single nested
trace, rebuilt from the framework's own run/event ids (so it's correct across
threads and async). Both frameworks are **optional** extras — `import
agentscope` never requires them; the handler imports its framework lazily and
only when you use it. LLM steps are costed with the same price tables as the
auto-instrumentation above.

**LangChain:**

```bash
pip install "agentscope-lite[langchain]"
```

```python
from agentscope.integrations.langchain import AgentScopeCallbackHandler

handler = AgentScopeCallbackHandler()
agent.invoke({"input": "book me a flight"}, config={"callbacks": [handler]})
```

**LlamaIndex:**

```bash
pip install "agentscope-lite[llamaindex]"
```

```python
from llama_index.core import Settings
from llama_index.core.callbacks import CallbackManager
from agentscope.integrations.llamaindex import AgentScopeCallbackHandler

Settings.callback_manager = CallbackManager([AgentScopeCallbackHandler()])
# every query / chat / agent run is now traced automatically
```

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

## Command-line interface

Installing the package also provides the `agentscope` command (and
`python -m agentscope`):

```bash
agentscope init                     # interactive configuration wizard
agentscope doctor                   # check environment + connectivity
agentscope status                   # live platform metrics
agentscope trace list --limit 20    # recent request traces
agentscope replay create --conversation 5 --model gpt-4o
agentscope evaluate run --conversation 5 --reference "42"
agentscope compare run --conversation 5 --model gpt-4o --model claude-3
agentscope plugins list
agentscope providers health openai
agentscope export conversation 5 --format otel --out trace.json
agentscope import bundle.json --replay --model gpt-4o
agentscope start                    # launch the platform via docker compose
agentscope                          # interactive shell
```

Commands: `init`, `start`, `trace`, `replay`, `evaluate`, `compare`, `plugins`,
`providers`, `export`, `import`, `config`, `doctor`, `status`, `version`.
Global flags include `--endpoint`, `--api-key`, `--json`, `--timeout`,
`--color/--no-color`. Colored output is automatic on TTYs (respecting
`NO_COLOR`) and works cross-platform. Run `agentscope <command> -h` for details.

## Compatibility

The public API — `trace`, `Agent`, `Workflow`, `Tool`, `configure` — is stable
across the `1.x` line.

## License

MIT © Aarohi Sharma
