"""Ingest and query a trace over the REST API — no SDK, just the stdlib.

Any language can POST traces to AgentScope. This shows the raw HTTP calls.
Requires a running server:

    docker compose up -d --build
    python examples/04_rest_ingest_trace.py
"""
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("AGENTSCOPE_ENDPOINT", "http://localhost:8000").rstrip("/")


def _request(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read() or b"{}")


def main() -> None:
    try:
        created = _request("POST", "/api/traces", {
            "model_name": "gpt-4o",
            "user_prompt": "Hi",
            "system_prompt": "You are helpful.",
            "input_tokens": 10,
            "output_tokens": 20,
            "final_response": "Hello!",
            "latency_ms": 420,
        })
        print("Created trace:", json.dumps(created, indent=2)[:400])

        stats = _request("GET", "/api/stats")
        print("\nDashboard stats:", json.dumps(stats, indent=2)[:400])
    except urllib.error.URLError as exc:
        print(f"Could not reach {BASE}: {exc}")
        print("Start the server with `docker compose up -d --build` and retry.")


if __name__ == "__main__":
    main()
