"""API tests for the HTTP ingestion endpoints.

POST /api/agent-runs and POST /api/retrievals let external services (e.g. a
chatbot) populate the Agent Runs and RAG Observatory views, not just the flat
request-trace list.
"""


def _seed_trace(client, prompt="hello", model="gpt-4o"):
    res = client.post("/api/traces", json={"user_prompt": prompt, "model_name": model})
    assert res.status_code == 201
    return res.get_json()


# -- POST /api/agent-runs --------------------------------------------------


def test_ingest_agent_run_full_payload_linked_to_trace(client):
    trace = _seed_trace(client, "Write a dedupe function", "openai/gpt-oss-20b:free")

    payload = {
        "request_id": trace["id"],
        "agent_name": "Chatbot",
        "agent_type": "chatbot",
        "status": "success",
        "latency_ms": 1234.5,
        "metadata": {"model": "openai/gpt-oss-20b:free"},
        "steps": [
            {
                "step_type": "retrieval",
                "name": "Retriever",
                "input": "dedupe a list",
                "status": "success",
                "latency_ms": 42.0,
                "retrievals": [
                    {
                        "query": "dedupe a list",
                        "retrieval_time_ms": 30.0,
                        "documents": [
                            {"document_name": "Dedupe recipe", "source": "kb",
                             "score": 0.91, "snippet": "seen = set()...", "selected": True},
                            {"title": "List tips", "source": "kb", "score": 0.72},
                        ],
                        "embedding": {"model": "text-embedding-3-small", "dimension": 1536,
                                      "input_tokens": 5},
                    }
                ],
            },
            {
                "step_type": "llm",
                "name": "LLM Generation",
                "output": "Here is a dedupe function...",
                "status": "success",
                "token_usage": {"input": 706, "output": 207, "total": 913},
                "cost": 0.0,
                "tool_calls": [
                    {"tool_name": "search_kb", "arguments": {"q": "dedupe"}, "result": {"hits": 2}},
                ],
                "memory_accesses": [
                    {"memory_type": "vector", "query": "dedupe", "used": True, "similarity_score": 0.8},
                ],
            },
        ],
    }

    res = client.post("/api/agent-runs", json=payload)
    assert res.status_code == 201
    body = res.get_json()

    assert body["request_id"] == trace["id"]
    assert body["agent_name"] == "Chatbot"
    assert body["status"] == "success"
    assert body["latency_ms"] == 1234.5
    assert body["step_count"] == 2
    assert {s["step_type"] for s in body["steps"]} == {"retrieval", "llm"}
    assert body["timeline"]  # non-empty ordered timeline

    # Sub-records were persisted and flattened onto the detail view.
    assert len(body["tool_executions"]) == 1
    assert body["tool_executions"][0]["tool_name"] == "search_kb"
    assert len(body["memory_accesses"]) == 1
    assert len(body["retriever_traces"]) == 1
    assert body["retriever_traces"][0]["num_documents"] == 2

    # It is now discoverable via the GET list + detail + per-request endpoints.
    listed = client.get("/api/agent-runs").get_json()
    assert any(r["id"] == body["id"] for r in listed["data"])
    assert client.get(f"/api/agent-runs/{body['id']}").status_code == 200
    per_req = client.get(f"/api/requests/{trace['id']}/agent-runs").get_json()
    assert any(r["id"] == body["id"] for r in per_req["data"])


def test_ingest_agent_run_without_request_id_creates_trace(client):
    before = client.get("/api/traces").get_json()
    payload = {
        "agent_name": "Chatbot",
        "model_name": "openai/gpt-oss-20b:free",
        "user_prompt": "hi",
        "final_response": "hello!",
        "steps": [{"step_type": "llm", "name": "LLM Generation", "output": "hello!"}],
    }
    res = client.post("/api/agent-runs", json=payload)
    assert res.status_code == 201
    body = res.get_json()
    assert isinstance(body["request_id"], int)

    # A parent request trace was created and is visible in the request list.
    after = client.get("/api/traces").get_json()
    assert len(after) == len(before) + 1
    assert any(t["id"] == body["request_id"] for t in after)


def test_ingest_agent_run_validation(client):
    # agent_name is required
    assert client.post("/api/agent-runs", json={}).status_code == 400
    # steps must be a list
    assert client.post("/api/agent-runs", json={"agent_name": "A", "steps": {}}).status_code == 400
    # unknown request_id is rejected
    bad = client.post("/api/agent-runs", json={"agent_name": "A", "request_id": 999999})
    assert bad.status_code == 400
    # invalid status is rejected
    assert client.post("/api/agent-runs", json={"agent_name": "A", "status": "bogus"}).status_code == 400
    # a tool call must name its tool
    bad_tool = client.post(
        "/api/agent-runs",
        json={"agent_name": "A", "steps": [{"tool_calls": [{"arguments": {}}]}]},
    )
    assert bad_tool.status_code == 400


# -- POST /api/retrievals --------------------------------------------------


def test_ingest_retrieval_appears_in_rag_observatory(client):
    payload = {
        "query": "refund policy",
        "model_name": "openai/gpt-oss-20b:free",
        "retrieval_time_ms": 25.0,
        "documents": [
            {"document_name": "Refund policy", "source": "kb", "score": 0.95,
             "chunk_text": "Refunds within 30 days...", "selected": True},
        ],
        "embedding": {"model": "text-embedding-3-small", "dimension": 1536, "input_tokens": 3},
    }
    res = client.post("/api/retrievals", json=payload)
    assert res.status_code == 201
    body = res.get_json()
    assert body["id"]
    assert body["query"] == "refund policy"

    # Discoverable via the RAG Observatory list + detail.
    listed = client.get("/api/retrievals").get_json()
    assert any(r["id"] == body["id"] for r in listed["data"])
    assert client.get(f"/api/retrievals/{body['id']}").status_code == 200


def test_ingest_retrieval_validation(client):
    # documents must be a list when provided
    bad = client.post("/api/retrievals", json={"query": "x", "documents": "nope"})
    assert bad.status_code == 400
