"""Ship SDK traces to a running AgentScope server.

Point the SDK at the server via `configure(endpoint=...)`; finished traces are
POSTed to `/api/traces` by the built-in HTTPExporter. Requires a running server:

    docker compose up -d --build
    python examples/03_http_export.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

import agentscope
from agentscope import trace

ENDPOINT = os.environ.get("AGENTSCOPE_ENDPOINT", "http://localhost:5001")
API_KEY = os.environ.get("AGENTSCOPE_API_KEY")  # required only if AUTH_ENABLED


def main() -> None:
    agentscope.configure(
        service_name="http-export-demo",
        endpoint=ENDPOINT,     # enables the HTTPExporter
        api_key=API_KEY,        # sent as Authorization: Bearer, if set
        console=True,
    )

    @trace("generate", kind="llm", model="gpt-4o")
    def generate(prompt: str) -> str:
        return "Hello from the SDK!"

    try:
        generate("Say hi")
        print(f"\nTrace shipped to {ENDPOINT}. Open the dashboard to see it.")
    except Exception as exc:  # noqa: BLE001 - demo resilience
        print(f"\nCould not reach {ENDPOINT}: {exc}")
        print("Start the server with `docker compose up -d --build` and retry.")


if __name__ == "__main__":
    main()
