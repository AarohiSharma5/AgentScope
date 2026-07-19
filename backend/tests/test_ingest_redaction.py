"""Tests for server-side PII redaction at ingest (INGEST_REDACT)."""
import json

from flask import current_app

from app.redaction import Redactor, build_ingest_redactor
from app.services import ingest_service, trace_service


def _enable_redaction():
    current_app.config["INGEST_REDACT"] = True
    current_app.extensions.pop("_ingest_redactor", None)  # rebuild with new config


# -- unit ------------------------------------------------------------------


def test_redactor_scrubs_nested_but_preserves_safe_keys():
    from app.redaction import _BUILTIN_PATTERNS

    r = Redactor(list(_BUILTIN_PATTERNS))
    payload = {
        "model_name": "gpt-4o",
        "user_prompt": "email jane@x.com",
        "steps": [{"input": "call 415-555-0100", "step_type": "llm"}],
    }
    out = r.scrub_value(payload)
    assert out["model_name"] == "gpt-4o"          # safe key untouched
    assert out["steps"][0]["step_type"] == "llm"  # safe key untouched
    assert "[REDACTED_EMAIL]" in out["user_prompt"]
    assert "[REDACTED_PHONE]" in out["steps"][0]["input"]


def test_build_ingest_redactor_disabled_returns_none(app_ctx):
    current_app.config["INGEST_REDACT"] = False
    assert build_ingest_redactor(current_app.config) is None


# -- integration through the service layer ---------------------------------


def test_create_trace_redacts_when_enabled(app_ctx):
    _enable_redaction()
    trace = trace_service.create_trace(
        {
            "model_name": "gpt-4o",
            "user_prompt": "reach me at jane@x.com or 415-555-0100",
            "system_prompt": "you are helpful",
            "final_response": "sure, jane@x.com",
        }
    )
    assert "jane@x.com" not in trace.user_prompt
    assert "[REDACTED_EMAIL]" in trace.user_prompt
    assert "[REDACTED_PHONE]" in trace.user_prompt
    assert "[REDACTED_EMAIL]" in trace.final_response
    assert trace.model_name == "gpt-4o"  # safe key preserved


def test_create_trace_does_not_redact_by_default(app_ctx):
    trace = trace_service.create_trace(
        {"model_name": "gpt-4o", "user_prompt": "jane@x.com"}
    )
    assert trace.user_prompt == "jane@x.com"


def test_ingest_agent_run_redacts_nested_text(app_ctx):
    _enable_redaction()
    run = ingest_service.ingest_agent_run(
        {
            "agent_name": "Support",
            "agent_type": "chatbot",
            "user_prompt": "my email is bob@corp.com",
            "model_name": "gpt-4o",
            "steps": [
                {
                    "step_type": "llm",
                    "input": "contact bob@corp.com",
                    "output": "done",
                    "tool_calls": [
                        {
                            "tool_name": "lookup",
                            "arguments": {"email": "bob@corp.com"},
                            "result": "ok",
                        }
                    ],
                }
            ],
        }
    )

    parent = trace_service.get_trace(run.request_id)
    assert "[REDACTED_EMAIL]" in parent.user_prompt

    step = run.steps[0]
    assert "[REDACTED_EMAIL]" in step.input
    tool = step.tool_executions[0]
    assert tool.tool_name == "lookup"  # safe key preserved
    assert "bob@corp.com" not in json.dumps(tool.arguments)
