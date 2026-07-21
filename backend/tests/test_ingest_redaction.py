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


def test_expanded_builtin_secret_patterns():
    import pytest

    from app.redaction import _BUILTIN_PATTERNS

    r = Redactor(list(_BUILTIN_PATTERNS))
    cases = {
        "token eyJhbGciOi.J9payload.sigABC here": "[REDACTED_JWT]",
        "key AKIAIOSFODNN7EXAMPLE done": "[REDACTED_AWS_KEY]",
        "gh ghp_" + "a" * 36: "[REDACTED_GITHUB_TOKEN]",
        "slack xoxb-123456789012-abcdef done": "[REDACTED_SLACK_TOKEN]",
        "iban DE89370400440532013000 ok": "[REDACTED_IBAN]",
        "mac 01:23:45:67:89:ab up": "[REDACTED_MAC]",
    }
    for text, marker in cases.items():
        assert marker in r.scrub_text(text), text


def test_labelled_secret_keeps_label_scrubs_value():
    from app.redaction import _BUILTIN_PATTERNS

    r = Redactor(list(_BUILTIN_PATTERNS))
    out = r.scrub_text('config: password=hunter2 and api_key: abcd1234efgh')
    assert "hunter2" not in out and "abcd1234efgh" not in out
    assert "password" in out and "api_key" in out  # labels preserved
    assert out.count("[REDACTED_SECRET]") == 2


# -- pluggable detectors ---------------------------------------------------


def test_pluggable_detector_runs_and_is_configurable(app_ctx):
    from app import redaction

    redaction.register_detector("upper_names", lambda t: t.replace("Alice", "[NAME]"))
    try:
        current_app.config["INGEST_REDACT"] = True
        current_app.config["INGEST_REDACT_DETECTORS"] = ["upper_names"]
        current_app.extensions.pop("_ingest_redactor", None)

        redactor = build_ingest_redactor(current_app.config)
        out = redactor.scrub_text("Alice emailed jane@x.com")
        assert "[NAME]" in out and "[REDACTED_EMAIL]" in out  # detector + regex both ran
    finally:
        redaction.clear_detectors()
        current_app.config["INGEST_REDACT_DETECTORS"] = []


def test_unknown_detector_name_is_ignored(app_ctx):
    current_app.config["INGEST_REDACT"] = True
    current_app.config["INGEST_REDACT_DETECTORS"] = ["does_not_exist"]
    current_app.extensions.pop("_ingest_redactor", None)
    redactor = build_ingest_redactor(current_app.config)
    # No crash; regex layer still works.
    assert "[REDACTED_EMAIL]" in redactor.scrub_text("jane@x.com")
    current_app.config["INGEST_REDACT_DETECTORS"] = []


def test_failing_detector_does_not_break_redaction(app_ctx):
    from app import redaction

    def boom(_text):
        raise RuntimeError("detector down")

    redaction.register_detector("boom", boom)
    try:
        r = Redactor([], detectors=[boom])
        # Detector raises internally but scrub_text swallows and returns text.
        assert r.scrub_text("hello") == "hello"
    finally:
        redaction.clear_detectors()


def test_register_detector_rejects_non_callable():
    import pytest

    from app import redaction

    with pytest.raises(TypeError):
        redaction.register_detector("bad", "not callable")


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
