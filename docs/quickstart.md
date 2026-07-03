# Quick Start

This gets you from zero to a visible trace in a few minutes. It assumes the
server is running (see [Installation](installation.md)).

## 1. Start the server

```bash
docker compose up -d --build
# Dashboard: http://localhost:8080   API: http://localhost:5001/api
```

Confirm it is healthy:

```bash
curl http://localhost:5001/api/health
# {"status": "ok", "service": "agentscope"}
```

## 2A. Capture a trace with the SDK

```bash
pip install agentscope-lite
```

```python
import agentscope
from agentscope import trace

# Ship finished traces to the running server.
agentscope.configure(service_name="quickstart", endpoint="http://localhost:5001")

@trace("generate", kind="llm", model="gpt-4o")
def generate(prompt: str) -> str:
    # ... call your real model here ...
    return "Hello from AgentScope!"

generate("Say hi")
```

Open the dashboard at http://localhost:8080 — your request appears in the trace
table. Full details in [SDK](reference/sdk.md).

## 2B. Or POST a trace directly

Any language can ingest a trace over HTTP:

```bash
curl -X POST http://localhost:5001/api/traces \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "gpt-4o",
    "user_prompt": "Hi",
    "input_tokens": 10,
    "output_tokens": 20,
    "final_response": "Hello!",
    "latency_ms": 420
  }'
```

## 3. Query it back

```bash
curl http://localhost:5001/api/traces          # recent traces
curl http://localhost:5001/api/stats           # aggregate dashboard metrics
```

## 4. Explore with the CLI

```bash
agentscope config set endpoint http://localhost:5001
agentscope status              # live platform metrics
agentscope trace list --limit 10
```

## 5. Go deeper

- Trace agents, tools, memory and RAG → [Tracing](guides/tracing.md).
- Orchestrate multiple agents and run graphs → [Workflows](guides/workflows.md).
- Re-run a past conversation under a new model → [Replay](guides/replay.md).
- Score answer quality automatically → [Evaluation](guides/evaluation.md).

## Try the runnable examples

The [`examples/`](../examples/README.md) folder contains complete, runnable
programs:

```bash
python examples/01_quickstart_trace.py       # SDK basics (no server needed)
python examples/02_agent_tool_workflow.py    # Agent + Tool + Workflow
python examples/04_rest_ingest_trace.py       # POST a trace over REST
```
