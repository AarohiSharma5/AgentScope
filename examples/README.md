# Examples

Runnable example programs for AgentScope. See the [documentation](../docs/README.md)
for full guides.

| File | What it shows | Needs a server? |
| ---- | ------------- | --------------- |
| [`01_quickstart_trace.py`](01_quickstart_trace.py) | Trace three ways with the SDK; inspect locally. | No |
| [`02_agent_tool_workflow.py`](02_agent_tool_workflow.py) | `Agent`, `Tool`, `Workflow` (sequential + parallel). | No |
| [`03_http_export.py`](03_http_export.py) | Ship SDK traces to the server. | Yes |
| [`04_rest_ingest_trace.py`](04_rest_ingest_trace.py) | Ingest & query a trace over raw REST. | Yes |
| [`05_replay_evaluate.py`](05_replay_evaluate.py) | Replay, evaluate and compare over REST. | Yes |
| [`06_workflow_engine.py`](06_workflow_engine.py) | Run a JSON workflow with `WorkflowEngine`. | Backend env |
| [`07_custom_plugin.py`](07_custom_plugin.py) | Author a plugin that contributes a tool. | Backend env |
| [`08_custom_provider.py`](08_custom_provider.py) | Add a provider without changing core code. | Backend env |
| [`09_auth_api_keys.py`](09_auth_api_keys.py) | Register, create a project + API key, authenticate. | Yes |
| [`workflow_spec.json`](workflow_spec.json) | Sample workflow definition used by example 06. | — |

## Running the SDK examples (no server)

Examples 01–02 run standalone. From the repo root:

```bash
python examples/01_quickstart_trace.py
python examples/02_agent_tool_workflow.py
```

They add the local `sdk/` folder to `sys.path` so they work without installing.
With `pip install agentscope-lite`, drop that shim and just `import agentscope`.

## Running the REST examples (server required)

Start the stack, then run:

```bash
docker compose up -d --build
docker compose exec backend python seed.py     # optional sample data
python examples/04_rest_ingest_trace.py
python examples/05_replay_evaluate.py 1
python examples/09_auth_api_keys.py
```

Override the server URL with `AGENTSCOPE_ENDPOINT` (default
`http://localhost:8000`).

## Running the backend examples

Examples 06–08 import the backend `app` package, so run them from the backend
environment:

```bash
cd backend && source .venv/bin/activate
python ../examples/06_workflow_engine.py
python ../examples/07_custom_plugin.py
python ../examples/08_custom_provider.py
```
