# Evaluation

`EvaluationEngine` scores a conversation with pluggable evaluators and persists
an `EvaluationRun` with one `EvaluationMetric` per evaluator plus a weighted
overall score. It supports rule-based evaluators, an LLM-as-a-Judge, and your own
custom evaluators — and can run synchronously or on a worker thread.

## Built-in metrics

Ten rule-based evaluators ship built-in:

| Metric | What it measures |
| ------ | ---------------- |
| `correctness`        | Token-overlap F1 between the answer and a supplied reference. |
| `groundedness`       | Fraction of the answer supported by the retrieved context. |
| `faithfulness`       | Answer support by context **or** question (1 − hallucination). |
| `context_precision`  | Fraction of retrieved documents that were selected/used. |
| `context_recall`     | Fraction of expected facts present in the retrieved context. |
| `answer_relevance`   | Fraction of the question's terms addressed by the answer. |
| `tool_success`       | Fraction of tool executions that succeeded. |
| `memory_usage`       | Fraction of memory accesses whose result was used. |
| `latency_score`      | `max(0, 1 − latency / budget)`. |
| `cost_score`         | `max(0, 1 − cost / budget)`. |

Each returns `None` (with a note) when not applicable, so every metric is always
persisted. The overall score is the weighted average of the non-null values;
per-metric `weights` can be overridden per run.

## Evaluate with the engine

```python
from app.evaluation import EvaluationEngine, CustomEvaluator

# Rule-based (default), plus a custom evaluator and an LLM-as-a-Judge.
engine = EvaluationEngine(judge=lambda prompt: {"score": 0.8, "notes": "ok"})
engine.register(CustomEvaluator("brand_safety", lambda ctx: 1.0, weight=2.0))

result = engine.evaluate(conversation_run_id, reference="…", cost_budget=1.0)
print(result.overall_score, result.score("correctness"))

# Asynchronous execution on a worker thread:
future = engine.evaluate_async(conversation_run_id)
```

### Evaluator types

- **Rule-based** — the ten built-ins above; deterministic, no external calls.
- **LLM-as-a-Judge** — pass any `judge(prompt)` callable returning a float or
  `{"score", "notes"}`. There is **no hard dependency** on any provider — you
  supply the judge, so you choose the model.
- **Custom** — subclass or wrap a function with `CustomEvaluator(name, fn, weight)`.
- **Constraints / validity** — deterministic **hard-requirement** checks (below).

## Constraints (validity checks)

Lexical metrics like `correctness` and `faithfulness` measure *resemblance*, so
they can score green even when the answer breaks a real requirement — it returned
jobs needing "0-4 years" when the ask was "0-3", or drifted to the wrong sector.
Those are **validity** problems, and validity is deterministic. Pass declarative
`constraints` (JSON-friendly dicts, no custom function needed) and the engine adds
a `constraint_validity` metric:

```python
result = engine.evaluate(conversation_run_id, constraints=[
    # never promise more years of experience than asked
    {"type": "numeric_range", "pattern": r"(\d+)\s*-\s*(\d+)\s*years",
     "max": 3, "name": "experience_ceiling"},
    # stay on the requested sector (any of these terms present)
    {"type": "contains", "values": ["tech", "software"], "mode": "any"},
    # never leak an internal tool name
    {"type": "not_contains", "values": ["__debug__"]},
    # structured output must have the required shape
    {"type": "json_keys", "required": ["title", "url"], "target": "answer"},
])
print(result.score("constraint_validity"))
```

Constraint types: `contains` / `not_contains`, `regex`, `numeric_range` (with an
optional extraction `pattern`), `allowed_values`, `length` (chars/words),
`json_keys` (required keys + types), and `custom` (any `fn(ctx)`). Each targets
`answer` by default; set `target` to `user_prompt`, `retrieved_context`,
`reference`, or `extra.<key>`.

A **hard** failure (the default `severity`) gates the metric to `0.0` so a genuine
violation can't be averaged away by other passing checks; use `severity: "soft"`
for advisory checks that only lower the fraction. The metric is weighted heavily
(`2.0`) by default so it dominates the overall score.

## Evaluate over REST

REST evaluations use the built-in rule-based set (an LLM judge needs an
in-process callable):

```bash
curl -X POST http://localhost:8000/api/evaluations \
  -H "Content-Type: application/json" \
  -d '{"conversation_run_id": 1, "reference": "Paris", "cost_budget": 1.0}'
```

- `GET /api/evaluations` — list evaluation runs.
- `GET /api/evaluations/:id` — run detail with per-metric values.
- `GET /api/dashboard/evaluation-metrics` — aggregate metrics.
- `GET /api/dashboard/evaluation-analytics` — daily time-series + headline rates.

The **Evaluation** dashboard shows the overall score, metric cards, a radar chart
and score history.

## Comparing models

`ModelComparisonEngine` runs one traced workflow against many models — by
replaying the base conversation under each model and (optionally) evaluating it —
then stores pairwise `ModelComparison` records and produces a ranking summary and
a side-by-side matrix (output, latency, tokens, cost, evaluation score, tool
success, memory usage, retriever performance). Model names are opaque strings, so
the design is fully provider-agnostic.

```python
from app.comparison import ModelComparisonEngine

result = ModelComparisonEngine().compare(
    conversation_run_id,
    ["gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "gemini-2.5", "llama-3"],
    evaluate=True, reference="…", cost_budget=1.0,
)
print(result.winner, result.summary["best_by"])   # e.g. cheapest / fastest / best-scored
```

```bash
curl -X POST http://localhost:8000/api/comparisons \
  -H "Content-Type: application/json" \
  -d '{"conversation_run_id": 1, "models": ["gpt-4o", "gpt-4o-mini"], "evaluate": true}'
```

The **Comparison** dashboard renders Model A vs Model B side by side with a
declared winner.

## From the CLI

```bash
agentscope evaluate run --conversation 5 --reference "42"
agentscope compare run --conversation 5 --model gpt-4o --model claude-3-5-sonnet
```

## Next

- Wire real providers with the [Providers](providers.md) abstraction.
- Add your own evaluators as a [Plugin](plugins.md).
