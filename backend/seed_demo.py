"""Seed a rich, interlinked demo dataset covering every navbar tab.

Run from the ``backend`` directory:

    python3 seed_demo.py

This is **append-only** (it does not drop existing data), so your own captured
traces are preserved. It drives the real engines/SDK — TraceRecorder,
AgentOrchestrator, WorkflowEngine, ReplayEngine, EvaluationEngine and
ModelComparisonEngine — so the seeded data is identical in shape to what the
platform produces in production and is fully consistent across views:

    Requests        <- flat LLM request traces + the parents of every run below
    Agent Runs      <- multi-step agent runs (steps / tools / memory / retrieval)
    RAG Observatory <- retriever traces with documents + embeddings
    Workflows       <- workflow definitions + executions
    Conversations   <- multi-agent conversations with messages
    Replays         <- replays of conversations under alternate models
    Evaluations     <- rule-based evaluations (spread across days)
    Comparisons     <- one conversation run against several models
    Diffs           <- multiple prompt versions on a run (+ two runs to diff)
    Analytics       <- derived from the evaluations above (daily time series)
    Live            <- real-time only; emits as new activity happens

Use ``--reset`` to wipe first for a pristine demo dataset.
"""
import random
import sys
from datetime import timedelta

from app import create_app
from app.comparison import ModelComparisonEngine
from app.evaluation import EvaluationEngine
from app.extensions import db
from app.models.agent_trace import AgentRun, AgentStatus, AgentStep
from app.models.trace import Trace, TraceStatus
from app.models.workflow_trace import ConversationRun
from app.orchestration import AgentOrchestrator, ReplayEngine, WorkflowEngine
from app.services import evaluation_service, prompt_service, trace_service
from app.utils.timeutils import utcnow

# Deterministic output so repeated runs look the same.
random.seed(1234)

SYSTEM_PROMPT = "You are AgentScope, a precise and concise research assistant."

# Standalone request traces (the "Requests" tab). Models here all exist in the
# backend price table, so cost is populated too.
STANDALONE = [
    ("gpt-4o", "Summarize the Q3 2026 earnings call in three bullets."),
    ("gpt-4o-mini", "Write a Python function to deduplicate a list preserving order."),
    ("claude-3-5-sonnet", "Explain the CAP theorem to a new backend engineer."),
    ("gpt-4o", "Draft a polite follow-up email to a client who went quiet."),
    ("gpt-3.5-turbo", "What are the trade-offs of microservices vs a monolith?"),
    ("claude-3-haiku", "Give me three unit-test ideas for a rate limiter."),
    ("gpt-4o-mini", "Convert this cron expression to plain English: */15 9-17 * * 1-5."),
    ("gpt-4-turbo", "Outline a migration plan from SQLite to PostgreSQL."),
    ("gpt-4o", "What changed between HTTP/1.1 and HTTP/2 for latency?"),
    ("claude-3-5-sonnet", "Review this SQL for N+1 query risks and suggest indexes."),
]

# Rich Q&A scenarios -> each becomes a conversation with a full agent run,
# retrieval (RAG) and messages. (question, answer, context, expected_facts)
SCENARIOS = [
    (
        "What was Q3 revenue and how did it compare to Q2?",
        "Q3 revenue was $4.2M, up 16.7% from Q2's $3.6M — above the ~10% industry average.",
        "Q3 revenue was $4.2M. Q2 revenue was $3.6M.",
        ["Q3 revenue was $4.2M", "Q2 revenue was $3.6M"],
    ),
    (
        "Which regions drove the most growth this quarter?",
        "APAC led with 28% QoQ growth, followed by EMEA at 12%; North America was flat.",
        "APAC grew 28% QoQ. EMEA grew 12% QoQ. North America was flat.",
        ["APAC grew 28%", "EMEA grew 12%"],
    ),
    (
        "Summarize the main risks flagged in the annual report.",
        "The report flags supply-chain concentration, FX exposure in EMEA, and rising cloud costs.",
        "Risks: supply-chain concentration, EMEA FX exposure, rising cloud infrastructure costs.",
        ["supply-chain concentration", "FX exposure", "cloud costs"],
    ),
    (
        "What is our current gross margin and the trend?",
        "Gross margin is 71%, up 3 points year over year, driven by infra efficiency gains.",
        "Gross margin is 71%, up from 68% a year ago.",
        ["gross margin is 71%", "up 3 points"],
    ),
    (
        "How many active customers do we have and the churn rate?",
        "There are 1,240 active customers with a monthly logo churn of 1.8%.",
        "Active customers: 1,240. Monthly churn: 1.8%.",
        ["1,240 active customers", "1.8% churn"],
    ),
    (
        "What's the headcount plan for next quarter?",
        "The plan adds 14 hires: 8 in engineering, 4 in sales, and 2 in support.",
        "Next quarter hiring plan: 8 engineering, 4 sales, 2 support (14 total).",
        ["14 hires", "8 in engineering"],
    ),
]

ALT_MODELS = ["gpt-4o-mini", "claude-3-5-sonnet", "gpt-4-turbo"]


def _seed_standalone_traces():
    """Flat request traces spread over the last ~12 days (the Requests tab)."""
    created = []
    for i, (model, prompt) in enumerate(STANDALONE):
        input_tokens = random.randint(120, 900)
        output_tokens = random.randint(60, 700)
        status = TraceStatus.SUCCESS if random.random() > 0.15 else TraceStatus.FAILED
        trace = trace_service.create_trace(
            {
                "user_prompt": prompt,
                "system_prompt": SYSTEM_PROMPT,
                "model_name": model,
                "latency_ms": round(random.uniform(220, 3800), 2),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "final_response": (
                    "Here is a concise answer based on the request…"
                    if status == TraceStatus.SUCCESS
                    else None
                ),
                "status": status,
                "error_message": None if status == TraceStatus.SUCCESS else "RateLimitError: 429",
            }
        )
        # Backdate across ~12 days so the list and analytics look realistic.
        trace.timestamp = utcnow() - timedelta(
            days=random.randint(0, 12), hours=random.randint(0, 23), minutes=random.randint(0, 59)
        )
        created.append(trace)
    db.session.commit()
    return created


def _build_scenario_conversation(model, question, answer, context, day_offset):
    """A conversation with a full agent run + RAG retrieval + messages.

    Returns (conversation_id, primary_agent_run_id).
    """
    input_tokens = random.randint(200, 500)
    output_tokens = random.randint(120, 400)
    trace = trace_service.create_trace(
        {
            "user_prompt": question,
            "system_prompt": SYSTEM_PROMPT,
            "model_name": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": round(random.uniform(400, 2600), 2),
            "final_response": answer,
        }
    )

    orch = AgentOrchestrator(request_trace_id=trace.id, conversation_name=question[:40])
    planner = orch.create_agent("Planner", role="planner")
    researcher = orch.create_agent("Researcher", role="researcher", parent=planner)

    def research_work():
        rec, run = orch.recorder, researcher.run
        rec.record_prompt_assembly(
            run,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=question,
            retrieved_context=context,
        )
        step = rec.add_step(run, step_type="retrieval", name="Retrieve context", input=question)
        rt = rec.record_retriever(
            step, query=question, retrieval_time_ms=round(random.uniform(40, 160), 1),
            embedding_time_ms=round(random.uniform(6, 22), 1),
        )
        for j, sentence in enumerate(context.split(". ")):
            rec.record_retrieved_document(
                rt,
                document_id=f"doc-{j+1}",
                document_name="FY26 Financials" if j == 0 else "Board Deck",
                document_source=random.choice(["chroma", "pinecone", "pgvector"]),
                chunk_index=j,
                chunk_text=sentence.strip().rstrip(".") + ".",
                similarity_score=round(random.uniform(0.72, 0.96), 3),
                selected=j == 0,
            )
        rec.record_embedding(
            rt, embedding_model="text-embedding-3-small", input=question, embedding_dimension=1536,
        )
        rec.record_memory(
            step, memory_type="vector", query=question,
            retrieved_text=context, similarity_score=0.9, used=True,
            latency_ms=round(random.uniform(20, 60), 1),
        )
        rec.finish_step(step, output=context)

        llm = rec.add_step(run, step_type="llm", name="Compose answer", input=question)
        rec.record_tool(llm, tool_name="calculator", arguments={"expr": "(4.2-3.6)/3.6*100"},
                        result="16.67", latency_ms=round(random.uniform(2, 8), 2))
        rec.finish_step(
            llm, output=answer,
            token_usage={"input": input_tokens, "output": output_tokens,
                         "total": input_tokens + output_tokens},
            cost=trace_service.estimate_cost(model, input_tokens, output_tokens),
        )
        return answer

    planner.execute()
    researcher.execute(work=research_work)

    # A little inter-agent chatter for the Conversations / message viewer.
    q = planner.ask(researcher, f"Please find: {question}")
    researcher.reply(q, answer)
    planner.broadcast("Answer ready — compiling the summary.")

    orch.finish()

    # Backdate the conversation + its request trace for a realistic timeline.
    when = utcnow() - timedelta(days=day_offset, hours=random.randint(0, 12))
    orch.conversation.created_at = when
    orch.conversation.started_at = when
    trace.timestamp = when
    db.session.commit()

    return orch.conversation.id, researcher.run.id


def _seed_workflows():
    """Register two workflow definitions and run an execution of each."""
    engine = WorkflowEngine()

    research_flow = {
        "name": "research-flow",
        "version": "1.0",
        "entry": "planner",
        "nodes": {
            "planner": {"type": "task", "role": "planner", "next": "researcher"},
            "researcher": {"type": "task", "role": "researcher", "next": "writer"},
            "writer": {"type": "task", "role": "writer", "next": "done"},
            "done": {"type": "end"},
        },
    }
    triage_flow = {
        "name": "support-triage",
        "version": "2.1",
        "entry": "classifier",
        "nodes": {
            "classifier": {"type": "task", "role": "classifier", "next": "resolver"},
            "resolver": {"type": "task", "role": "resolver", "next": "done"},
            "done": {"type": "end"},
        },
    }

    definitions = [
        engine.register(research_flow, name="research-flow", version="1.0"),
        engine.register(triage_flow, name="support-triage", version="2.1"),
    ]

    # A concrete execution (conversation) for the first definition.
    orch = AgentOrchestrator(
        conversation_name="Weekly research digest",
        workflow_definition_id=definitions[0].id,
    )
    planner = orch.create_agent("Planner", role="planner")
    researcher = orch.create_agent("Researcher", role="researcher", parent=planner)
    writer = orch.create_agent("Writer", role="writer", parent=planner)
    planner.execute()
    researcher.execute()
    writer.execute()
    q = planner.ask(researcher, "Pull the three biggest changes this week.")
    researcher.reply(q, "Revenue +16.7%, APAC +28%, gross margin 71%.")
    planner.ask(writer, "Draft a two-paragraph digest from those figures.")
    writer.reply(q, "This week the business accelerated…")
    orch.finish()
    return definitions


def _seed_prompt_versions(agent_run_id):
    """Add extra prompt versions so the Diffs (prompt) tab has something to diff."""
    prompt_service.record_prompt_version(
        agent_run_id,
        "You are a research assistant. Answer the user's question using ONLY the "
        "retrieved context. Cite figures exactly.",
    )
    prompt_service.record_prompt_version(
        agent_run_id,
        "You are a senior research analyst. Answer using ONLY the retrieved context, "
        "cite figures exactly, and add a one-line confidence note.",
    )


def _rollup_parent_traces():
    """Make multi-agent parent request rows look like real traffic.

    A multi-agent conversation anchors to a lightweight parent ``Trace`` whose
    token/cost/latency live on the child agent *steps*, so in the Requests feed
    those rows otherwise show ``—``. Here we roll the child totals up onto the
    parent (keeping the honest ``multi-agent`` label), synthesize sensible values
    for runs that have no steps, and spread timestamps over the last ~12 days so
    the feed reads like organic traffic instead of one clustered burst. Idempotent
    and non-destructive: only ``multi-agent`` parents are touched.
    """
    parents = Trace.query.filter(Trace.model_name == "multi-agent").all()
    touched = 0
    for trace in parents:
        steps = (
            AgentStep.query.join(AgentRun, AgentStep.agent_run_id == AgentRun.id)
            .filter(AgentRun.request_id == trace.id)
            .all()
        )
        in_tok = out_tok = tot_tok = 0
        cost = latency = 0.0
        for step in steps:
            usage = step.token_usage or {}
            in_tok += int(usage.get("input") or 0)
            out_tok += int(usage.get("output") or 0)
            tot_tok += int(usage.get("total") or 0)
            cost += float(step.cost or 0.0)
            latency += float(step.latency_ms or 0.0)

        if not tot_tok:  # runs with no steps (e.g. no-work workflow tasks)
            in_tok = random.randint(180, 460)
            out_tok = random.randint(90, 360)
            tot_tok = in_tok + out_tok
            cost = trace_service.estimate_cost("gpt-4o", in_tok, out_tok) or 0.0
            latency = round(random.uniform(600, 2400), 2)

        trace.input_tokens = int(in_tok)
        trace.output_tokens = int(out_tok)
        trace.total_tokens = int(tot_tok) or int(in_tok + out_tok)
        trace.estimated_cost = round(float(cost), 6)
        trace.latency_ms = round(float(latency) or random.uniform(600, 2400), 2)

        # Spread over the last ~12 days (deterministic per-trace via its id).
        jitter = random.Random(trace.id)
        when = utcnow() - timedelta(
            days=jitter.randint(0, 12), hours=jitter.randint(0, 23),
            minutes=jitter.randint(0, 59),
        )
        trace.timestamp = when
        for conv in ConversationRun.query.filter_by(request_trace_id=trace.id).all():
            conv.created_at = when
            conv.started_at = when
        touched += 1

    db.session.commit()
    return touched


def _spread_evaluation_dates(run_ids):
    """Backdate evaluation runs across the last week so Analytics has a series."""
    for offset, run_id in enumerate(run_ids):
        run = evaluation_service.get_evaluation_run(run_id)
        if run is not None:
            run.created_at = utcnow() - timedelta(days=offset)
    db.session.commit()


def seed(reset: bool = False):
    app = create_app()
    with app.app_context():
        if reset:
            db.drop_all()
            db.create_all()

        # 1) Requests — flat traces.
        standalone = _seed_standalone_traces()

        # 2/3/5) Conversations + Agent Runs + RAG Observatory.
        conversations = []  # (conversation_id, agent_run_id)
        for i, (question, answer, context, _facts) in enumerate(SCENARIOS):
            model = ["gpt-4o", "claude-3-5-sonnet", "gpt-4o-mini"][i % 3]
            conversations.append(
                _build_scenario_conversation(model, question, answer, context, day_offset=i)
            )

        # 4) Workflows (+ their executions/conversations).
        definitions = _seed_workflows()

        # 6) Replays — re-run a few conversations under alternate models.
        replay_count = 0
        for (conv_id, _run_id), model in zip(conversations, ALT_MODELS):
            ReplayEngine().replay(conv_id, model=model, temperature=0.3)
            replay_count += 1

        # 7) Evaluations — rule-based scoring of every scenario conversation.
        eval_run_ids = []
        for (conv_id, _run_id), (_q, answer, _ctx, facts) in zip(conversations, SCENARIOS):
            result = EvaluationEngine().evaluate(
                conv_id,
                reference=answer,
                expected_facts=facts,
                cost_budget=1.0,
                latency_budget_ms=5000,
                evaluation_type="quality",
            )
            eval_run_ids.append(result.evaluation_run_id)
        # 10) Analytics — spread the evaluations across the last week.
        _spread_evaluation_dates(eval_run_ids)

        # 8) Comparisons — one conversation vs several models.
        comparison_ids = []
        for (conv_id, _run_id), (_q, answer, _ctx, facts) in zip(conversations[:2], SCENARIOS[:2]):
            cmp_result = ModelComparisonEngine().compare(
                conv_id,
                ["gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet"],
                evaluate=True,
                reference=answer,
                expected_facts=facts,
                cost_budget=1.0,
            )
            comparison_ids.extend(cmp_result.comparison_ids)

        # 9) Diffs — multiple prompt versions on one run; two runs to trace-diff.
        _seed_prompt_versions(conversations[0][1])

        db.session.commit()

        # Roll child token/cost/latency up onto multi-agent parent request rows
        # and spread their timestamps so the Requests feed looks like real traffic.
        _rollup_parent_traces()

        # -- Summary ---------------------------------------------------------
        totals = {
            "traces (Requests)": Trace.query.count(),
            "standalone traces added": len(standalone),
            "scenario conversations": len(conversations),
            "workflow definitions": len(definitions),
            "replays": replay_count,
            "evaluations": len(eval_run_ids),
            "comparisons": len(comparison_ids),
        }
        print("\nSeeded demo dataset (append-only):")
        for label, value in totals.items():
            print(f"  - {label:28} {value}")
        print("\nHandy IDs to explore:")
        print(f"  - Diffs → Prompt tab:  agent run #{conversations[0][1]} (v1, v2, v3)")
        print(
            f"  - Diffs → Trace tab:   compare conversation "
            f"#{conversations[0][0]} vs #{conversations[1][0]}"
        )
        print(
            "  - Live tab is real-time; keep it open and re-run this script "
            "(or send new traces) to watch events stream in.\n"
        )


def fixup():
    """Non-destructive: only tidy existing multi-agent parent request rows.

    Rolls child token/cost/latency totals up onto ``multi-agent`` parent traces
    and spreads their timestamps, without creating any new data. Use this to make
    an already-seeded database look realistic without dropping anything.
    """
    app = create_app()
    with app.app_context():
        touched = _rollup_parent_traces()
        print(f"Tidied {touched} multi-agent parent request rows (no data added).")


if __name__ == "__main__":
    if "--fixup" in sys.argv:
        fixup()
    else:
        seed(reset="--reset" in sys.argv)
