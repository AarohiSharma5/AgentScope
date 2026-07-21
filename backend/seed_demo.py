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
from app.models.agent_trace import AgentRun, AgentStep
from app.models.trace import Trace, TraceStatus
from app.models.workflow_trace import ConversationRun
from app.orchestration import AgentOrchestrator, ReplayEngine, WorkflowEngine
from app.services import evaluation_service, prompt_service, trace_service
from app.utils.timeutils import utcnow

# Deterministic output so repeated runs look the same.
random.seed(1234)

# Applications / areas of concern. In a real company many surfaces share one
# model, so teams organize by *area* — each with its own system prompt. These
# make the "Application" filter on the Requests tab meaningful and demonstrable.
AREAS = {
    "revenue-analytics": (
        "You are a financial research analyst. Answer using ONLY the retrieved "
        "financial context and cite figures exactly."
    ),
    "code-assistant": (
        "You are a senior software engineer. Write correct, idiomatic code and "
        "briefly explain the trade-offs."
    ),
    "eng-education": (
        "You are a patient staff engineer mentoring teammates. Explain concepts "
        "clearly with practical examples."
    ),
    "customer-support": (
        "You are a helpful, empathetic customer-support agent. Be concise, "
        "professional and never make up account details."
    ),
    "data-insights": (
        "You are a data analyst. Answer with concrete numbers from the provided "
        "tables, state assumptions, and never invent figures."
    ),
    "product-search": (
        "You are a shopping assistant. Recommend only in-catalog products that "
        "match the user's stated constraints; never fabricate SKUs or prices."
    ),
}

# A pool of realistic prompts per application, used to generate a high volume of
# request traffic (the Requests tab / Analytics) that looks organic rather than
# like a handful of hand-written rows.
AREA_PROMPTS = {
    "revenue-analytics": [
        "Summarize the Q3 2026 earnings call in three bullets.",
        "What was net revenue retention last quarter?",
        "Break down revenue by region for the last two quarters.",
        "How did gross margin trend over the last year?",
        "Which product line grew fastest this quarter?",
        "Compare CAC and LTV for the enterprise segment.",
        "What drove the change in operating expenses?",
    ],
    "code-assistant": [
        "Write a Python function to deduplicate a list preserving order.",
        "Refactor this nested loop to reduce time complexity.",
        "Explain why this async function never resolves.",
        "Add type hints and a docstring to this function.",
        "Suggest three unit tests for a token-bucket rate limiter.",
        "Convert this callback-based code to async/await.",
        "Find the off-by-one bug in this binary search.",
        "Write a SQL migration to add a nullable column with an index.",
    ],
    "eng-education": [
        "Explain the CAP theorem to a new backend engineer.",
        "What are the trade-offs of microservices vs a monolith?",
        "How does a bloom filter work and when should I use one?",
        "Explain database isolation levels with examples.",
        "What changed between HTTP/1.1 and HTTP/2 for latency?",
        "Describe how consistent hashing balances load.",
        "When would you pick a message queue over direct RPC?",
    ],
    "customer-support": [
        "Draft a polite follow-up email to a client who went quiet.",
        "Customer can't reset their password — outline the next steps.",
        "Write an apology for a delayed shipment with a discount offer.",
        "Summarize this angry ticket and suggest a calm reply.",
        "Explain our refund policy to a confused customer.",
        "Draft a churn-risk save email for a downgrading account.",
    ],
    "data-insights": [
        "Which cohort has the best 90-day retention?",
        "What's the weekly active user trend this month?",
        "Segment revenue by plan tier and show the split.",
        "Find the top 5 features by adoption in the last 30 days.",
        "Is there a correlation between onboarding time and churn?",
        "Summarize funnel drop-off from signup to activation.",
    ],
    "product-search": [
        "Find a waterproof hiking backpack under $120.",
        "Recommend a quiet mechanical keyboard for an office.",
        "I need running shoes for flat feet, size 10.",
        "Show noise-cancelling headphones with 30h+ battery.",
        "Suggest a birthday gift for a coffee lover under $50.",
        "Find a 4K monitor with USB-C power delivery.",
    ],
}

# Candidate models per application (realistic: teams mix a workhorse model with a
# cheaper/faster one). All exist in the price table so cost is populated.
AREA_MODELS = {
    "revenue-analytics": ["gpt-4o", "claude-3-5-sonnet", "gpt-4-turbo"],
    "code-assistant": ["gpt-4o-mini", "claude-3-5-sonnet", "gpt-4o"],
    "eng-education": ["gpt-4o", "gpt-4-turbo", "claude-3-haiku"],
    "customer-support": ["gpt-4o-mini", "gpt-3.5-turbo", "claude-3-haiku"],
    "data-insights": ["gpt-4o", "gpt-4o-mini"],
    "product-search": ["gpt-4o-mini", "claude-3-haiku", "gpt-3.5-turbo"],
}

# The scenario Q&A below are all financial research, so they belong to one area.
SCENARIO_PROJECT = "revenue-analytics"
SYSTEM_PROMPT = AREAS[SCENARIO_PROJECT]

# Standalone request traces (the "Requests" tab): (model, prompt, project). Models
# here all exist in the backend price table, so cost is populated too, and each is
# tagged with the application it belongs to.
STANDALONE = [
    ("gpt-4o", "Summarize the Q3 2026 earnings call in three bullets.", "revenue-analytics"),
    ("gpt-4o-mini", "Write a Python function to deduplicate a list preserving order.", "code-assistant"),
    ("claude-3-5-sonnet", "Explain the CAP theorem to a new backend engineer.", "eng-education"),
    ("gpt-4o", "Draft a polite follow-up email to a client who went quiet.", "customer-support"),
    ("gpt-3.5-turbo", "What are the trade-offs of microservices vs a monolith?", "eng-education"),
    ("claude-3-haiku", "Give me three unit-test ideas for a rate limiter.", "code-assistant"),
    ("gpt-4o-mini", "Convert this cron expression to plain English: */15 9-17 * * 1-5.", "code-assistant"),
    ("gpt-4-turbo", "Outline a migration plan from SQLite to PostgreSQL.", "eng-education"),
    ("gpt-4o", "What changed between HTTP/1.1 and HTTP/2 for latency?", "eng-education"),
    ("claude-3-5-sonnet", "Review this SQL for N+1 query risks and suggest indexes.", "code-assistant"),
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
    (
        "What is our net revenue retention and how is it trending?",
        "Net revenue retention is 118%, up from 112% last quarter on strong upsells.",
        "NRR is 118%, up from 112% QoQ.",
        ["net revenue retention is 118%", "up from 112%"],
    ),
    (
        "How much cash runway do we have at the current burn?",
        "At $650K monthly net burn and $18.2M cash, runway is about 28 months.",
        "Cash: $18.2M. Net burn: $650K/mo. Runway ~28 months.",
        ["$18.2M cash", "28 months"],
    ),
]

ALT_MODELS = ["gpt-4o-mini", "claude-3-5-sonnet", "gpt-4-turbo", "gpt-4o", "claude-3-haiku"]

# Multi-step agent runs that live in applications *other* than revenue-analytics,
# so the Agent Runs tab is segmentable by application too (not just one area).
# (project, model, question, answer)
AGENT_RUN_SCENARIOS = [
    (
        "code-assistant",
        "gpt-4o-mini",
        "Refactor this O(n^2) lookup to be linear.",
        "Build a set once, then membership tests are O(1) — overall O(n).",
    ),
    (
        "code-assistant",
        "claude-3-5-sonnet",
        "Find the race condition in this counter increment.",
        "The read-modify-write on `count` isn't atomic; guard it with a lock.",
    ),
    (
        "customer-support",
        "gpt-4o",
        "Customer can't reset their password — outline the next steps.",
        "1) Verify identity, 2) trigger a reset email, 3) confirm inbox receipt.",
    ),
    (
        "code-assistant",
        "gpt-4o",
        "Add pagination to this list endpoint without breaking clients.",
        "Introduce optional page/limit params with a backwards-compatible default.",
    ),
    (
        "eng-education",
        "gpt-4-turbo",
        "Walk me through designing a rate limiter for an API gateway.",
        "Token-bucket per key in Redis; INCR+EXPIRE, return remaining + reset.",
    ),
    (
        "eng-education",
        "claude-3-haiku",
        "Explain eventual consistency with a shopping-cart example.",
        "Writes converge over time; the cart may briefly differ across replicas.",
    ),
    (
        "customer-support",
        "gpt-4o-mini",
        "A user was double-charged — how do I resolve and reassure them?",
        "Confirm the duplicate, issue a refund, apologize, and share the timeline.",
    ),
    (
        "data-insights",
        "gpt-4o",
        "Which onboarding step loses the most users?",
        "Step 3 (workspace setup) drops 22%; simplifying it should lift activation.",
    ),
    (
        "data-insights",
        "gpt-4o-mini",
        "Summarize this week's active-user movement.",
        "WAU up 6% WoW to 8,410, driven by returning users on the new dashboard.",
    ),
    (
        "product-search",
        "gpt-4o-mini",
        "Find a quiet mechanical keyboard under $100 for an office.",
        "Two in-catalog picks with silent switches under $100, with links.",
    ),
    (
        "product-search",
        "claude-3-haiku",
        "Recommend noise-cancelling headphones with 30h+ battery.",
        "Three catalog matches with 30h+ battery and active noise cancelling.",
    ),
]


def _seed_standalone_traces():
    """Flat request traces spread over the last ~12 days (the Requests tab)."""
    created = []
    for i, (model, prompt, project) in enumerate(STANDALONE):
        input_tokens = random.randint(120, 900)
        output_tokens = random.randint(60, 700)
        status = TraceStatus.SUCCESS if random.random() > 0.15 else TraceStatus.FAILED
        trace = trace_service.create_trace(
            {
                "project": project,
                "user_prompt": prompt,
                "system_prompt": AREAS[project],
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
        # Backdate across ~30 days so the list and analytics look realistic.
        trace.timestamp = _recent_when(30)
        created.append(trace)
    db.session.commit()
    return created


# Diurnal weighting (index = hour): traffic peaks during working hours and dips
# overnight, so the Requests feed and Analytics look like real usage.
_HOUR_WEIGHTS = [
    1, 1, 1, 1, 1, 1, 2, 4, 7, 9, 10, 10,
    9, 9, 10, 10, 9, 7, 5, 4, 3, 2, 1, 1,
]


def _recent_when(max_days: int = 30):
    """A backdated timestamp within the last ``max_days`` with a diurnal shape."""
    day = random.randint(0, max_days - 1)
    hour = random.choices(range(24), weights=_HOUR_WEIGHTS, k=1)[0]
    base = utcnow() - timedelta(days=day)
    return base.replace(
        hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59), microsecond=0
    )


_ERRORS = ["RateLimitError: 429", "APIConnectionError: connection reset", "Timeout after 30s"]


def _seed_request_volume(count: int = 160):
    """Generate a realistic volume of flat request traces across all applications.

    Spreads ``count`` requests over the last 30 days with a diurnal shape, a mix
    of models per application, varied token/latency profiles and a small error
    rate — so Requests, the model/application filters and Analytics all look like
    weeks of organic traffic rather than a handful of rows.
    """
    areas = list(AREA_PROMPTS.keys())
    for _ in range(count):
        project = random.choice(areas)
        model = random.choice(AREA_MODELS[project])
        prompt = random.choice(AREA_PROMPTS[project])
        input_tokens = random.randint(80, 1600)
        output_tokens = random.randint(40, 1200)
        failed = random.random() < 0.06
        trace = trace_service.create_trace(
            {
                "project": project,
                "user_prompt": prompt,
                "system_prompt": AREAS[project],
                "model_name": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": round(random.uniform(180, 5200), 2),
                "final_response": None if failed else "Answer generated from the request.",
                "status": TraceStatus.FAILED if failed else TraceStatus.SUCCESS,
                "error_message": random.choice(_ERRORS) if failed else None,
            }
        )
        trace.timestamp = _recent_when(30)
    db.session.commit()
    return count


def _build_scenario_conversation(model, question, answer, context, day_offset):
    """A conversation with a full agent run + RAG retrieval + messages.

    Returns (conversation_id, primary_agent_run_id).
    """
    input_tokens = random.randint(200, 500)
    output_tokens = random.randint(120, 400)
    trace = trace_service.create_trace(
        {
            "project": SCENARIO_PROJECT,
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


def _build_area_agent_run(project, model, question, answer):
    """A small multi-step agent run in a given application (idempotent).

    Creates the parent request trace (tagged with ``project`` and its system
    prompt) plus a two-step agent run (reasoning + answer) so the Agent Runs tab
    has runs spread across several applications. Skips creation if a trace with
    the same project + prompt already exists, so ``--agent-areas`` can be re-run.
    """
    existing = Trace.query.filter_by(project=project, user_prompt=question).first()
    if existing is not None:
        return False

    input_tokens = random.randint(160, 420)
    output_tokens = random.randint(80, 320)
    trace = trace_service.create_trace(
        {
            "project": project,
            "user_prompt": question,
            "system_prompt": AREAS[project],
            "model_name": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": round(random.uniform(300, 2200), 2),
            "final_response": answer,
        }
    )

    orch = AgentOrchestrator(request_trace_id=trace.id, conversation_name=question[:40])
    agent = orch.create_agent("Assistant", role=project)

    def work():
        rec, run = orch.recorder, agent.run
        rec.record_prompt_assembly(
            run, system_prompt=AREAS[project], user_prompt=question
        )
        plan = rec.add_step(run, step_type="reasoning", name="Analyze request", input=question)
        rec.finish_step(plan, output="Identified the approach and constraints.")
        llm = rec.add_step(run, step_type="llm", name="Compose answer", input=question)
        rec.finish_step(
            llm,
            output=answer,
            token_usage={
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            },
            cost=trace_service.estimate_cost(model, input_tokens, output_tokens),
        )
        return answer

    agent.execute(work=work)
    orch.finish()

    when = utcnow() - timedelta(days=random.randint(0, 10), hours=random.randint(0, 23))
    orch.conversation.created_at = when
    orch.conversation.started_at = when
    trace.timestamp = when
    db.session.commit()
    return True


def _seed_area_agent_runs():
    """Create agent runs across non-analytics applications (idempotent)."""
    created = 0
    for project, model, question, answer in AGENT_RUN_SCENARIOS:
        if _build_area_agent_run(project, model, question, answer):
            created += 1
    return created


def _seed_workflows():
    """Register three workflow definitions and run several executions of each."""
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
    review_flow = {
        "name": "code-review",
        "version": "1.2",
        "entry": "reviewer",
        "nodes": {
            "reviewer": {"type": "task", "role": "reviewer", "next": "tester"},
            "tester": {"type": "task", "role": "tester", "next": "done"},
            "done": {"type": "end"},
        },
    }

    definitions = [
        engine.register(research_flow, name="research-flow", version="1.0"),
        engine.register(triage_flow, name="support-triage", version="2.1"),
        engine.register(review_flow, name="code-review", version="1.2"),
    ]

    # A few concrete executions per definition so the Workflows tab shows a
    # definition with a run history rather than a single execution.
    for run_idx in range(3):
        orch = AgentOrchestrator(
            conversation_name=f"Weekly research digest #{run_idx + 1}",
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

    for run_idx in range(2):
        orch = AgentOrchestrator(
            conversation_name=f"Support triage batch #{run_idx + 1}",
            workflow_definition_id=definitions[1].id,
        )
        classifier = orch.create_agent("Classifier", role="classifier")
        resolver = orch.create_agent("Resolver", role="resolver", parent=classifier)
        classifier.execute()
        resolver.execute()
        q = classifier.ask(resolver, "Billing issue, high priority — resolve it.")
        resolver.reply(q, "Refund issued and confirmation email sent.")
        orch.finish()

    orch = AgentOrchestrator(
        conversation_name="PR #482 review",
        workflow_definition_id=definitions[2].id,
    )
    reviewer = orch.create_agent("Reviewer", role="reviewer")
    tester = orch.create_agent("Tester", role="tester", parent=reviewer)
    reviewer.execute()
    tester.execute()
    q = reviewer.ask(tester, "Run the suite against the new pagination logic.")
    tester.reply(q, "All 42 tests pass; added 3 for the edge cases.")
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

        # Spread over the last ~30 days (deterministic per-trace via its id).
        jitter = random.Random(trace.id)
        when = utcnow() - timedelta(
            days=jitter.randint(0, 29), hours=jitter.randint(0, 23),
            minutes=jitter.randint(0, 59),
        )
        trace.timestamp = when
        for conv in ConversationRun.query.filter_by(request_trace_id=trace.id).all():
            conv.created_at = when
            conv.started_at = when
        touched += 1

    db.session.commit()
    return touched


def _backfill_projects():
    """Tag request traces with an application/area + its system prompt (idempotent).

    New seeded traces are tagged at creation, but replay/workflow parents and any
    previously seeded rows have no ``project``. Infer one from the prompt so the
    "Application" filter is populated across all existing data: exact match on a
    known standalone prompt, or a scenario question appearing in the prompt (which
    also catches "replay of <question>" parents).

    Because an area is really "an application *and the system prompt behind it*",
    for every trace mapped to a known :data:`AREAS` application we also align its
    ``system_prompt`` to that application's prompt — so each application shows a
    distinct prompt instead of one generic default. Only rows classified into a
    known area are touched; a user's own captured traces (unknown prompts) are
    left untouched and fall back to system-prompt grouping in the UI.
    """
    std_map = {prompt: project for (_m, prompt, project) in STANDALONE}
    # Match on the 40-char conversation-name prefix, because replay parents store
    # a truncated "replay of <question[:40]>" prompt — the full question is never
    # a substring of it. This is what previously left replay rows untagged.
    scenario_prefixes = [q[:40] for (q, *_rest) in SCENARIOS]
    touched = 0
    for trace in Trace.query.all():
        project = trace.project
        if project is None:
            prompt = trace.user_prompt or ""
            project = std_map.get(prompt)
            if project is None and any(pref in prompt for pref in scenario_prefixes):
                project = SCENARIO_PROJECT
            # Remaining multi-agent parents (replays / the research-digest
            # workflow execution) are all research/analytics work in this demo,
            # and — like any agent run — are driven by a system prompt, so give
            # them the analytics area rather than leaving them prompt-less.
            if project is None and trace.model_name == "multi-agent":
                project = SCENARIO_PROJECT
        if not project or project not in AREAS:
            continue
        changed = False
        if trace.project != project:
            trace.project = project
            changed = True
        if trace.system_prompt != AREAS[project]:
            trace.system_prompt = AREAS[project]
            changed = True
        if changed:
            touched += 1
    db.session.commit()
    return touched


def _spread_evaluation_dates(run_ids):
    """Backdate evaluation runs across the last ~4 weeks so Analytics has a series."""
    for offset, run_id in enumerate(run_ids):
        run = evaluation_service.get_evaluation_run(run_id)
        if run is not None:
            run.created_at = utcnow() - timedelta(
                days=offset, hours=random.randint(0, 12)
            )
    db.session.commit()


def _seed_eval_timeseries(conversations, days: int = 28):
    """Densify the Evaluations/Analytics time series.

    Re-scores existing scenario conversations repeatedly and backdates each run
    across the last ``days`` days, so the Analytics charts show a continuous
    daily trend (quality/cost/latency) instead of a handful of points. Every run
    is a real ``EvaluationRun`` with metrics — identical in shape to production.
    """
    engine = EvaluationEngine()
    run_ids = []
    for offset in range(days):
        (conv_id, _run_id) = random.choice(conversations)
        (_q, answer, _ctx, facts) = random.choice(SCENARIOS)
        result = engine.evaluate(
            conv_id,
            reference=answer,
            expected_facts=facts,
            cost_budget=1.0,
            latency_budget_ms=5000,
            evaluation_type="quality",
        )
        run = evaluation_service.get_evaluation_run(result.evaluation_run_id)
        if run is not None:
            run.created_at = utcnow() - timedelta(
                days=offset, hours=random.randint(0, 20), minutes=random.randint(0, 59)
            )
            run_ids.append(result.evaluation_run_id)
    db.session.commit()
    return len(run_ids)


def seed(reset: bool = False):
    app = create_app()
    with app.app_context():
        if reset:
            db.drop_all()
            db.create_all()

        # 1) Requests — a handful of hand-written flat traces…
        standalone = _seed_standalone_traces()
        # …plus a high volume of generated traffic across every application so
        # the Requests feed, filters and Analytics look like weeks of real use.
        volume = _seed_request_volume(160)

        # 2/3/5) Conversations + Agent Runs + RAG Observatory.
        conversations = []  # (conversation_id, agent_run_id)
        for i, (question, answer, context, _facts) in enumerate(SCENARIOS):
            model = ["gpt-4o", "claude-3-5-sonnet", "gpt-4o-mini"][i % 3]
            conversations.append(
                _build_scenario_conversation(model, question, answer, context, day_offset=i * 3)
            )

        # 2b) Agent runs in other applications so Agent Runs spans >1 area.
        area_runs = _seed_area_agent_runs()

        # 4) Workflows (+ their executions/conversations).
        definitions = _seed_workflows()

        # 6) Replays — re-run several conversations under alternate models.
        replay_count = 0
        for (conv_id, _run_id), model in zip(conversations, ALT_MODELS):
            ReplayEngine().replay(conv_id, model=model, temperature=0.3)
            replay_count += 1

        # 7) Evaluations — rule-based scoring of every scenario conversation…
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
        # 10) Analytics — spread the core evaluations, then densify into a
        # continuous ~4-week daily series so the charts read like real trends.
        _spread_evaluation_dates(eval_run_ids)
        timeseries_evals = _seed_eval_timeseries(conversations, days=28)

        # 8) Comparisons — several conversations each run against multiple models.
        comparison_ids = []
        for (conv_id, _run_id), (_q, answer, _ctx, facts) in zip(conversations[:3], SCENARIOS[:3]):
            cmp_result = ModelComparisonEngine().compare(
                conv_id,
                ["gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet"],
                evaluate=True,
                reference=answer,
                expected_facts=facts,
                cost_budget=1.0,
            )
            comparison_ids.extend(cmp_result.comparison_ids)

        # 9) Diffs — multiple prompt versions on two runs; two runs to trace-diff.
        _seed_prompt_versions(conversations[0][1])
        _seed_prompt_versions(conversations[1][1])

        db.session.commit()

        # Roll child token/cost/latency up onto multi-agent parent request rows
        # and spread their timestamps so the Requests feed looks like real traffic.
        _rollup_parent_traces()

        # Tag any untagged parents (replays/workflows) with their application so
        # the Requests "Application" filter is populated across everything.
        _backfill_projects()

        # -- Summary ---------------------------------------------------------
        totals = {
            "traces (Requests)": Trace.query.count(),
            "hand-written standalone": len(standalone),
            "generated request volume": volume,
            "area agent runs added": area_runs,
            "scenario conversations": len(conversations),
            "workflow definitions": len(definitions),
            "replays": replay_count,
            "core evaluations": len(eval_run_ids),
            "timeseries evaluations": timeseries_evals,
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
        tagged = _backfill_projects()
        print(
            f"Tidied {touched} multi-agent parent request rows and tagged "
            f"{tagged} traces with an application (no data added)."
        )


def agent_areas():
    """Non-destructive: append agent runs across non-analytics applications.

    Use this to give an already-seeded database agent runs in more than one
    application (so the Agent Runs "Application" filter is demonstrable) without
    dropping anything. Idempotent — re-running adds nothing new.
    """
    app = create_app()
    with app.app_context():
        created = _seed_area_agent_runs()
        print(f"Added {created} agent run(s) across non-analytics applications.")


if __name__ == "__main__":
    if "--fixup" in sys.argv:
        fixup()
    elif "--agent-areas" in sys.argv:
        agent_areas()
    else:
        seed(reset="--reset" in sys.argv)
