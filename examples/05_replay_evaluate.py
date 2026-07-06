"""Replay, evaluate and compare a conversation over REST.

Assumes a conversation already exists (e.g. after seeding or tracing a
multi-agent run). Requires a running server:

    docker compose up -d --build
    docker compose exec backend python seed.py   # optional sample data
    python examples/05_replay_evaluate.py 1       # 1 = conversation_run_id
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("AGENTSCOPE_ENDPOINT", "http://localhost:8000").rstrip("/")


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"{}")


def main() -> None:
    conversation_run_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    try:
        replay = post("/api/replays", {
            "conversation_run_id": conversation_run_id,
            "model": "gpt-4o-mini",
            "temperature": 0.2,
        })
        print("Replay:", json.dumps(replay, indent=2)[:400])

        evaluation = post("/api/evaluations", {
            "conversation_run_id": conversation_run_id,
            "reference": "Paris",
            "cost_budget": 1.0,
        })
        print("\nEvaluation:", json.dumps(evaluation, indent=2)[:400])

        comparison = post("/api/comparisons", {
            "conversation_run_id": conversation_run_id,
            "models": ["gpt-4o", "gpt-4o-mini"],
            "evaluate": True,
        })
        print("\nComparison:", json.dumps(comparison, indent=2)[:400])
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode()[:300]}")
        print("Make sure the conversation_run_id exists (try seeding first).")
    except urllib.error.URLError as exc:
        print(f"Could not reach {BASE}: {exc}")


if __name__ == "__main__":
    main()
