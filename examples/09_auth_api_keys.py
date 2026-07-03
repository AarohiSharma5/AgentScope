"""End-to-end auth flow over REST: register, project, API key, and use it.

Demonstrates the v1.0 authentication & multi-tenancy API using only the stdlib.
Requires a running server:

    docker compose up -d --build
    python examples/09_auth_api_keys.py
"""
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("AGENTSCOPE_ENDPOINT", "http://localhost:5001").rstrip("/")


def call(method: str, path: str, body: dict | None = None, token: str | None = None,
         api_key: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if api_key:
        headers["X-API-Key"] = api_key
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read() or b"{}")


def main() -> None:
    import uuid
    email = f"admin-{uuid.uuid4().hex[:8]}@acme.test"

    try:
        # 1) Register a user + first organization (the user becomes admin).
        reg = call("POST", "/api/auth/register", {
            "email": email, "password": "password123",
            "name": "Admin", "organization_name": "Acme",
        })
        token = reg["tokens"]["access_token"]
        org_id = reg["organization"]["id"]
        print(f"Registered {email} in org {org_id}")

        # 2) Create a project.
        project = call("POST", f"/api/organizations/{org_id}/projects",
                       {"name": "Search"}, token=token)
        print("Created project:", project["id"])

        # 3) Mint an API key scoped to that project (secret shown once).
        key = call("POST", f"/api/organizations/{org_id}/api-keys",
                   {"name": "ci", "role": "developer", "project_id": project["id"]},
                   token=token)
        raw = key["key"]
        print("Created API key:", key["prefix"], "...")

        # 4) Authenticate a request using the API key.
        me = call("GET", "/api/auth/me", api_key=raw)
        print("Authenticated as:", me["identity"]["auth_type"],
              "org", me["identity"]["organization_id"])
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode()[:300]}")
    except urllib.error.URLError as exc:
        print(f"Could not reach {BASE}: {exc}")


if __name__ == "__main__":
    main()
