"""Verify v0.5 replay & evaluation queries run correctly against PostgreSQL.

Builds an original multi-agent conversation, replays it under a different model,
and records a comparison — all against the docker-compose Postgres.

    DATABASE_URL=postgresql://agentscope:agentscope@localhost:5432/agentscope \\
        PYTHONPATH=$PWD python scripts/check_pg_v05.py
"""
import os
import sys

os.environ.setdefault(
    "DATABASE_URL", "postgresql://agentscope:agentscope@localhost:5432/agentscope"
)

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.orchestration import AgentOrchestrator, ReplayEngine  # noqa: E402
from app.services import replay_service  # noqa: E402

_SPEC = {
    "name": "pg-replay-flow",
    "version": "1.0",
    "entry": "planner",
    "nodes": {
        "planner": {"type": "task", "role": "planner", "next": "done"},
        "done": {"type": "end"},
    },
}


def _build_original() -> int:
    orch = AgentOrchestrator(
        conversation_name="pg-orig", workflow_name="pg-replay-flow",
        workflow_version="1.0", workflow_json=_SPEC,
    )
    planner = orch.create_agent("Planner", role="planner")

    def work():
        rec, run = orch.recorder, planner.run
        rec.record_prompt_assembly(run, system_prompt="sys", user_prompt="do it")
        step = rec.add_step(run, step_type="llm", name="LLM", input="do it")
        rec.record_tool(step, tool_name="search", arguments={"q": "x"}, result="found")
        rec.finish_step(step, output="done",
                        token_usage={"input": 100, "output": 50, "total": 150}, cost=0.01)
        return "done"

    planner.execute(work=work)
    orch.finish()
    return orch.conversation.id


def main() -> int:
    app = create_app()
    with app.app_context():
        assert db.engine.dialect.name == "postgresql", db.engine.dialect.name
        db.create_all()

        original_id = _build_original()

        engine = ReplayEngine()
        result = engine.replay(original_id, model="gpt-4o", temperature=0.5)
        assert result.ok, "replay failed"
        assert result.replay_conversation_run_id != original_id
        assert result.totals["cost"] == round(0.00075, 6), result.totals

        stored = replay_service.get_replay_run(result.replay_run.id)
        assert stored is not None and stored.replayed_model == "gpt-4o"

        comparison = engine.compare(original_id, result, model_a="multi-agent", model_b="gpt-4o")
        assert comparison.winner == "gpt-4o", comparison.winner
        assert comparison.token_difference == 0

        items, total = replay_service.list_replay_runs(original_conversation_run_id=original_id)
        assert total == 1

        print("PostgreSQL v0.5 compatibility: OK")
        print(f"  original={original_id} replay_conv={result.replay_conversation_run_id}")
        print(f"  replay_cost={result.totals['cost']} comparison_winner={comparison.winner}")

        # cleanup this run's original conversation (cascades to replay-produced rows
        # only where FK-linked; replay conversation is standalone, remove explicitly).
        from app.models.workflow_trace import ConversationRun
        for cid in (result.replay_conversation_run_id, original_id):
            conv = db.session.get(ConversationRun, cid)
            if conv is not None:
                db.session.delete(conv)
        db.session.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
