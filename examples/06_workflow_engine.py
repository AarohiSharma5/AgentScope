"""Run a JSON-defined workflow with the backend WorkflowEngine.

Handlers supply the business logic and read/write a shared `context` to pass data
between nodes. This example must run inside the backend environment (it imports
`app` and needs a Flask app context), e.g.:

    cd backend && source .venv/bin/activate
    python ../examples/06_workflow_engine.py
"""
import json
import os
import sys

# Make the backend package importable when run from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

SPEC_PATH = os.path.join(os.path.dirname(__file__), "workflow_spec.json")


def main() -> None:
    from app import create_app
    from app.orchestration import WorkflowEngine

    with open(SPEC_PATH) as fh:
        spec = json.load(fh)

    # Handlers receive the shared AgentContext (ctx.get / ctx.set) and return a
    # result. They are keyed by node id or "role".
    def planner(ctx):
        ctx.set("plan", ["search", "summarize"])
        return "planned"

    def researcher(ctx):
        return "researched"

    def merger(ctx):
        ctx.set("confidence", 0.9)   # high enough to skip the critic loop
        return "merged"

    def critic(ctx):
        ctx.set("confidence", 0.95)
        return "critiqued"

    handlers = {"planner": planner, "researcher": researcher,
                "merger": merger, "critic": critic}

    app = create_app()
    with app.app_context():
        engine = WorkflowEngine(handlers=handlers)
        result = engine.run(spec, context={"question": "What is AgentScope?"},
                            timeout_ms=30_000)
        print("status: ", result.status)
        print("visited:", result.visited)
        print("outputs:", result.outputs)


if __name__ == "__main__":
    main()
