"""Tests for OpenTelemetry (OTLP/HTTP JSON) trace ingest.

Covers the span→agent-run mapping across the GenAI/OpenLLMetry/OpenInference
attribute conventions (via a captured payload, no DB) and the end-to-end
``POST /api/otel/v1/traces`` path (real DB through the shared client fixture).
"""
import pytest

from app.services import otel_service


# --- OTLP payload builders --------------------------------------------------


def _kv(key, value):
    if isinstance(value, bool):
        v = {"boolValue": value}
    elif isinstance(value, int):
        v = {"intValue": value}
    elif isinstance(value, float):
        v = {"doubleValue": value}
    else:
        v = {"stringValue": str(value)}
    return {"key": key, "value": v}


def _span(name, attrs, *, span_id="s1", parent="", trace_id="t1", start=1_000_000_000, end=1_050_000_000, error=False):
    span = {
        "name": name,
        "spanId": span_id,
        "traceId": trace_id,
        "startTimeUnixNano": start,
        "endTimeUnixNano": end,
        "attributes": [_kv(k, v) for k, v in attrs.items()],
    }
    if parent:
        span["parentSpanId"] = parent
    if error:
        span["status"] = {"code": 2}
    return span


def _otlp(spans, resource=None):
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_kv(k, v) for k, v in (resource or {}).items()]},
                "scopeSpans": [{"spans": spans}],
            }
        ]
    }


class _FakeRun:
    def __init__(self, run_id):
        self.id = run_id


@pytest.fixture
def captured(monkeypatch):
    """Capture the agent-run dict handed to ingest_service (bypasses the DB)."""
    seen = []

    def _fake(data):
        seen.append(data)
        return _FakeRun(len(seen))

    monkeypatch.setattr(otel_service.ingest_service, "ingest_agent_run", _fake)
    return seen


# --- mapping tests (no DB) --------------------------------------------------


def test_genai_llm_span_maps_to_run_with_tokens_and_cost(captured):
    payload = _otlp(
        [
            _span(
                "chat gpt-4o",
                {
                    "gen_ai.system": "openai",
                    "gen_ai.request.model": "gpt-4o",
                    "gen_ai.usage.input_tokens": 12,
                    "gen_ai.usage.output_tokens": 4,
                    "gen_ai.prompt": "hello there",
                    "gen_ai.completion": "hi!",
                },
            )
        ]
    )
    result = otel_service.ingest_otlp(payload)
    assert result["accepted_spans"] == 1 and result["accepted_traces"] == 1

    run = captured[0]
    assert run["agent_type"] == "otel"
    assert run["model_name"] == "gpt-4o"
    assert run["user_prompt"] == "hello there"
    assert run["final_response"] == "hi!"
    assert run["input_tokens"] == 12 and run["output_tokens"] == 4 and run["total_tokens"] == 16
    assert run["estimated_cost"] == pytest.approx(12 / 1000 * 0.0025 + 4 / 1000 * 0.01)
    assert run["latency_ms"] == pytest.approx(50.0)
    assert run["metadata"]["source"] == "otel"

    step = run["steps"][0]
    assert step["step_type"] == "llm"
    assert step["token_usage"] == {"input": 12, "output": 4, "total": 16}
    assert step["metadata"]["gen_ai_system"] == "openai"


def test_openinference_conventions_are_understood(captured):
    payload = _otlp(
        [
            _span(
                "LLM",
                {
                    "openinference.span.kind": "LLM",
                    "llm.model_name": "gpt-4o-mini",
                    "llm.token_count.prompt": 8,
                    "llm.token_count.completion": 2,
                    "input.value": "q",
                    "output.value": "a",
                },
            )
        ]
    )
    otel_service.ingest_otlp(payload)
    step = captured[0]["steps"][0]
    assert step["step_type"] == "llm"
    assert step["input"] == "q" and step["output"] == "a"
    assert step["token_usage"] == {"input": 8, "output": 2, "total": 10}
    assert step["metadata"]["model"] == "gpt-4o-mini"
    assert step["cost"] == pytest.approx(8 / 1000 * 0.00015 + 2 / 1000 * 0.0006)


def test_tool_and_retriever_spans_become_steps(captured):
    spans = [
        _span(
            "AgentExecutor",
            {"traceloop.span.kind": "agent"},
            span_id="root",
        ),
        _span(
            "search",
            {"traceloop.span.kind": "tool", "gen_ai.tool.name": "web_search", "output.value": "found it"},
            span_id="t", parent="root", start=1_010_000_000, end=1_020_000_000,
        ),
        _span(
            "retrieve",
            {
                "openinference.span.kind": "RETRIEVER",
                "input.value": "who is x",
                "retrieval.documents.0.document.content": "doc-a",
                "retrieval.documents.0.document.score": 0.9,
                "retrieval.documents.1.document.content": "doc-b",
            },
            span_id="r", parent="root", start=1_020_000_000, end=1_030_000_000,
        ),
    ]
    otel_service.ingest_otlp(_otlp(spans))
    run = captured[0]
    assert run["agent_name"] == "AgentExecutor"  # root span (no/absent parent)

    tool_step = next(s for s in run["steps"] if s["step_type"] == "action")
    assert tool_step["tool_calls"][0]["tool_name"] == "web_search"
    assert tool_step["tool_calls"][0]["result"] == "found it"

    ret_step = next(s for s in run["steps"] if s["step_type"] == "retrieval")
    retrieval = ret_step["retrievals"][0]
    assert retrieval["query"] == "who is x"
    assert retrieval["num_documents"] == 2
    assert retrieval["documents"][0] == {"chunk_text": "doc-a", "similarity_score": 0.9}
    assert retrieval["documents"][1] == {"chunk_text": "doc-b"}


def test_error_status_marks_run_and_step_failed(captured):
    payload = _otlp([_span("chat", {"gen_ai.request.model": "gpt-4o"}, error=True)])
    otel_service.ingest_otlp(payload)
    run = captured[0]
    assert run["status"] == "failed"
    assert run["steps"][0]["status"] == "failed"


def test_unknown_model_records_tokens_but_no_cost(captured):
    payload = _otlp(
        [_span("chat", {"gen_ai.request.model": "mystery-1", "gen_ai.usage.input_tokens": 5, "gen_ai.usage.output_tokens": 5})]
    )
    otel_service.ingest_otlp(payload)
    step = captured[0]["steps"][0]
    assert step["token_usage"]["total"] == 10
    assert step["cost"] is None


def test_intvalue_as_string_is_decoded(captured):
    span = _span("chat", {"gen_ai.request.model": "gpt-4o"})
    # OTLP/JSON frequently encodes 64-bit ints as strings.
    span["attributes"].append({"key": "gen_ai.usage.input_tokens", "value": {"intValue": "20"}})
    otel_service.ingest_otlp(_otlp([span]))
    assert captured[0]["steps"][0]["token_usage"]["input"] == 20


def test_multiple_traces_produce_multiple_runs(captured):
    spans = [
        _span("a", {"gen_ai.request.model": "gpt-4o"}, span_id="a", trace_id="t1"),
        _span("b", {"gen_ai.request.model": "gpt-4o"}, span_id="b", trace_id="t2"),
    ]
    result = otel_service.ingest_otlp(_otlp(spans))
    assert result["accepted_traces"] == 2
    assert len(captured) == 2


def test_empty_payload_is_accepted(captured):
    assert otel_service.ingest_otlp({}) == {"accepted_spans": 0, "runs": []}
    assert captured == []


def test_non_object_body_raises():
    from app.utils.validation import ValidationError

    with pytest.raises(ValidationError):
        otel_service.ingest_otlp([1, 2, 3])


# --- end-to-end through the API + DB ----------------------------------------


def test_post_otel_traces_creates_agent_run(client):
    payload = _otlp(
        [
            _span(
                "chat gpt-4o",
                {
                    "gen_ai.request.model": "gpt-4o",
                    "gen_ai.usage.input_tokens": 30,
                    "gen_ai.usage.output_tokens": 10,
                    "gen_ai.prompt": "summarize this",
                    "gen_ai.completion": "summary",
                },
            )
        ],
        resource={"service.name": "my-otel-app"},
    )
    res = client.post("/api/otel/v1/traces", json=payload)
    assert res.status_code == 200
    body = res.get_json()
    assert "partialSuccess" in body
    assert body["accepted_spans"] == 1
    assert len(body["runs"]) == 1

    runs = client.get("/api/agent-runs").get_json()
    assert runs["pagination"]["total"] >= 1
    assert any(r.get("agent_type") == "otel" for r in runs["data"])


def test_post_otel_traces_versioned_alias(client):
    payload = _otlp([_span("chat", {"gen_ai.request.model": "gpt-4o"})])
    res = client.post("/api/v1/otel/v1/traces", json=payload)
    assert res.status_code == 200
