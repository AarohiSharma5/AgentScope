"""Verify v0.4 multi-agent queries run correctly against PostgreSQL.

Complements the SQLite-based pytest suite. Exercises the ORM constructs that
differ across backends (``ilike``, ``cast``, ``func`` aggregates,
``selectinload`` eager loading) via the real service/SDK layer.

Run against the docker-compose Postgres:

    DATABASE_URL=postgresql://agentscope:agentscope@localhost:5432/agentscope \\
        python scripts/check_pg_v04.py
"""
import os
import sys

os.environ.setdefault(
    "DATABASE_URL", "postgresql://agentscope:agentscope@localhost:5432/agentscope"
)

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.orchestration import AgentOrchestrator, WorkflowEngine  # noqa: E402
from app.services import trace_service, workflow_service  # noqa: E402
from app.services.message_service import message_service  # noqa: E402

_SPEC = {
    "name": "pg-compat-flow",
    "version": "1.0",
    "entry": "planner",
    "nodes": {
        "planner": {"type": "task", "role": "planner", "next": "reviewer"},
        "reviewer": {"type": "task", "role": "reviewer", "next": "done"},
        "done": {"type": "end"},
    },
}


def main() -> int:
    app = create_app()
    with app.app_context():
        assert db.engine.dialect.name == "postgresql", (
            f"expected postgresql, got {db.engine.dialect.name}"
        )
        db.create_all()

        engine = WorkflowEngine()
        definition = engine.register(_SPEC, name="pg-compat-flow", version="1.0")

        orch = AgentOrchestrator(
            conversation_name="pg-compat", workflow_definition_id=definition.id
        )
        planner = orch.create_agent("Planner", role="planner")
        researcher = orch.create_agent("Researcher", role="researcher", parent=planner)
        planner.execute()
        researcher.execute()
        trace_service.create_agent_step(
            agent_run_id=planner.run.id, step_type="reasoning", name="think", cost=0.02
        )
        q = planner.ask(researcher, "What is LangSmith?")
        researcher.reply(q, "An observability platform.")
        planner.broadcast("kickoff")
        orch.finish()

        # -- workflow queries: search (ilike), sort, pagination -----------------
        workflows, total = workflow_service.list_workflows(q="pg-compat", sort="-created_at")
        assert total >= 1 and workflows, "workflow search/sort failed"
        detail = workflow_service.get_workflow(definition.id)
        assert detail is not None and detail.executions, "workflow detail failed"

        # -- conversation queries: filter + eager tree -------------------------
        convs, ctotal = workflow_service.list_conversations(status="success")
        assert ctotal >= 1, "conversation status filter failed"
        conv = workflow_service.get_conversation(orch.conversation.id)
        assert conv is not None and conv.nodes, "conversation detail failed"

        # -- message layer: history, search, timeline --------------------------
        history = message_service.conversation_history(orch.conversation.id)
        assert history, "conversation history empty"
        found = message_service.search(
            text="LangSmith", conversation_run_id=orch.conversation.id
        )
        assert found, "message text search (ilike) failed"
        timeline = message_service.timeline(orch.conversation.id)
        assert timeline, "message timeline failed"

        # -- dashboard metrics: func aggregates over multiple tables ------------
        metrics = workflow_service.get_workflow_metrics()
        assert metrics["total_workflows"] >= 1, "workflow metrics failed"
        assert metrics["total_agents"] >= 2, "agent count metric failed"

        print("PostgreSQL v0.4 compatibility: OK")
        print(f"  workflows={total} conversations={ctotal} messages={len(history)}")
        print(f"  metrics={metrics}")

        # cleanup: drop the compat conversation/definition to keep the db tidy
        db.session.delete(conv)
        db.session.delete(detail)
        db.session.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
