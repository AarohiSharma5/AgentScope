# Replay

Replay re-runs any traced conversation, faithfully reusing its workflow, agent
sequence, prompts, memory, retrieved documents and tool calls — while letting you
override the model, temperature, `top_p`, system prompt, memory or tools. Every
replay produces a brand-new (fully traced) conversation plus a `ReplayRun`
linked back to the original.

Use it to answer *"what would this conversation look like under a different
model or prompt?"* without re-running your whole application.

## Replay with the engine

```python
from app.orchestration import ReplayEngine

engine = ReplayEngine()
result = engine.replay(
    conversation_run_id,
    model="gpt-4o-mini",          # re-estimates cost for the new model
    temperature=0.2,
    system_prompt="Be concise.",  # optional overrides
)
print(result.replay_conversation_run_id, result.totals)

# Compare the original against the replay (records a ModelComparison):
comparison = engine.compare(conversation_run_id, result, model_a="gpt-4o", model_b="gpt-4o-mini")
```

### Mock vs. live

Replays run in **mock** mode by default: original outputs and tool results are
replayed as-is, and cost is re-estimated for the new model. This is fast,
deterministic and free.

Pass `live=True` with `agent_handlers` / `tool_handlers` (role/name → callable)
to actually invoke fresh logic:

```python
result = engine.replay(
    conversation_run_id,
    model="gpt-4o-mini",
    live=True,
    agent_handlers={"planner": my_planner},
    tool_handlers={"search": my_search},
)
```

## Replay over REST

REST replays run in mock mode (live handlers are Python callables, only
available through the SDK):

```bash
curl -X POST http://localhost:8000/api/replays \
  -H "Content-Type: application/json" \
  -d '{"conversation_run_id": 1, "model": "gpt-4o-mini", "temperature": 0.2}'
```

- `GET /api/replays` — list replay runs (pagination, search, sort, filter).
- `GET /api/replays/:id` — replay run detail.

## What you can override

| Field | Effect |
| ----- | ------ |
| `model` | Re-estimate cost; use a different model (live mode). |
| `temperature`, `top_p` | Sampling parameters for the replay. |
| `system_prompt` | Replace the system prompt across the run. |
| `memory` | Swap the memory snapshot. |
| `tools` | Provide different tool handlers (live mode). |

## Prompt & trace diffs

Replays pair naturally with diffs. Every assembled prompt is **auto-versioned**
(hashed, de-duplicated) as a `PromptVersion`, so you can compare any two versions
word by word, or diff two whole conversations on their step/tool/memory/retriever
counts and latency/cost/token totals:

```bash
curl "http://localhost:8000/api/prompt-diff?a=12&b=8"    # word-level prompt diff
curl "http://localhost:8000/api/trace-diff?a=1&b=2"      # full trace diff
```

Both power the side-by-side **Diffs** dashboard.

## From the CLI

```bash
agentscope replay create --conversation 5 --model gpt-4o-mini --temperature 0.2
agentscope replay list
```

## Next

- [Evaluate](evaluation.md) originals and replays with pluggable scorers.
- Compare many models at once with the Comparison engine (see
  [Evaluation](evaluation.md#comparing-models)).
