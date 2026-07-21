"""Tests for optional PII/secret redaction (agentscope.configure(redact=...))."""
import agentscope
from agentscope import SpanKind, trace


def _last():
    traces = trace.finished()
    assert traces, "expected a finished trace"
    return traces[-1]


def test_redaction_off_by_default_keeps_payload():
    with trace("op") as span:
        span.set_input("email me at jane.doe@example.com")
        span.set_output("sure, jane.doe@example.com")
    root = _last().root
    assert "jane.doe@example.com" in root.input
    assert "jane.doe@example.com" in root.output


def test_redaction_scrubs_common_pii_when_enabled():
    agentscope.configure(redact=True)
    with trace("op") as span:
        span.set_input("contact jane.doe@example.com or call 415-555-0100")
        span.set_output("card 4111 1111 1111 1111, ssn 123-45-6789")
    root = _last().root
    assert "jane.doe@example.com" not in root.input
    assert "[REDACTED_EMAIL]" in root.input
    assert "[REDACTED_PHONE]" in root.input
    assert "[REDACTED_CC]" in root.output
    assert "[REDACTED_SSN]" in root.output


def test_redaction_scrubs_api_keys_and_bearer_tokens():
    agentscope.configure(redact=True)
    with trace("op") as span:
        span.set_input("key sk-abcdef0123456789ABCDEF and Bearer abc.def-123_XYZ")
    text = _last().root.input
    assert "[REDACTED_API_KEY]" in text
    assert "[REDACTED_TOKEN]" in text
    assert "sk-abcdef0123456789ABCDEF" not in text


def test_redaction_scrubs_expanded_secret_formats():
    agentscope.configure(redact=True)
    with trace("op") as span:
        span.set_input(
            "jwt eyJhbGciOi.J9body.sigZ aws AKIAIOSFODNN7EXAMPLE "
            "gh ghp_" + "a" * 36 + " iban DE89370400440532013000"
        )
        span.set_output("password=hunter2 done")
    root = _last().root
    assert "[REDACTED_JWT]" in root.input
    assert "[REDACTED_AWS_KEY]" in root.input
    assert "[REDACTED_GITHUB_TOKEN]" in root.input
    assert "[REDACTED_IBAN]" in root.input
    # labelled secret keeps the label, scrubs the value
    assert "hunter2" not in root.output and "[REDACTED_SECRET]" in root.output
    assert "password" in root.output


def test_redaction_preserves_model_attribute():
    agentscope.configure(redact=True)
    with trace.llm("gen", model="gpt-4o", system_prompt="email boss@corp.com") as span:
        span.set_output("ok")
    root = _last().root
    assert root.attributes["model"] == "gpt-4o"  # safe key survives
    assert "[REDACTED_EMAIL]" in root.attributes["system_prompt"]  # other attrs scrubbed


def test_redaction_recurses_into_nested_structures():
    agentscope.configure(redact=True)
    with trace("op") as span:
        span.set_input([{"role": "user", "content": "mail a@b.com"}])
    scrubbed = _last().root.input
    assert scrubbed[0]["content"] == "mail [REDACTED_EMAIL]"


def test_custom_patterns_extend_builtins():
    agentscope.configure(redact=True, redact_patterns=[(r"ACME-\d+", "[ACCOUNT]")])
    with trace("op") as span:
        span.set_input("account ACME-4477 for jane@x.com")
    text = _last().root.input
    assert "[ACCOUNT]" in text
    assert "[REDACTED_EMAIL]" in text  # built-ins still apply


def test_custom_redactor_overrides_builtins():
    agentscope.configure(redact=True, redactor=lambda s: s.replace("secret", "***"))
    with trace("op") as span:
        span.set_input("this is secret, email jane@x.com")
    text = _last().root.input
    assert "***" in text
    # Full override => built-in email pattern is NOT applied.
    assert "jane@x.com" in text


def test_scrubbed_before_export(monkeypatch):
    """Redaction happens before exporters see the trace."""
    from agentscope.exporters.memory import MemoryExporter

    captured = MemoryExporter(10)
    agentscope.configure(redact=True)
    trace.add_exporter(captured)
    with trace("op") as span:
        span.set_output("reach me: jane@x.com")
    exported = captured.traces[-1]
    assert "[REDACTED_EMAIL]" in exported.root.output
