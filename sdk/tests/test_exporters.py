import io
import json
import logging

import agentscope
from agentscope import ConsoleExporter, LoggingExporter, MemoryExporter, trace
from agentscope.exporters.http import HTTPExporter
from agentscope.span import Span, SpanKind, Trace


def _build_trace():
    """A small trace: root LLM span with a tokens/cost + a tool child."""
    root = Span(name="answer", kind=SpanKind.LLM)
    root.set_input("what is 2+2?").set_output("4").set_tokens(input=10, output=2).set_cost(0.002)
    root.attributes["model"] = "gpt-4o"
    root._finalize("success")
    tool = Span(name="calc", kind=SpanKind.TOOL, trace_id=root.trace_id, parent_id=root.span_id)
    tool.set_input({"a": 2, "b": 2}).set_output(4)
    tool._finalize("success")
    return Trace(trace_id=root.trace_id, root=root, spans=[root, tool])


def test_memory_exporter_retains_and_clears():
    exp = MemoryExporter(maxlen=2)
    exp.export(_build_trace())
    exp.export(_build_trace())
    exp.export(_build_trace())
    assert len(exp.traces) == 2  # bounded
    exp.clear()
    assert exp.traces == []


def test_console_exporter_prints_tree():
    buffer = io.StringIO()
    ConsoleExporter(stream=buffer).export(_build_trace())
    out = buffer.getvalue()
    assert "answer" in out
    assert "tool:calc" in out


def test_logging_exporter_emits_json(caplog):
    with caplog.at_level(logging.INFO, logger="agentscope"):
        LoggingExporter().export(_build_trace())
    assert any("agentscope.trace" in r.message for r in caplog.records)


def test_http_exporter_maps_to_request_trace():
    exp = HTTPExporter(endpoint="http://x", default_model="fallback")
    payload = exp._to_request_trace(_build_trace())
    assert payload["model_name"] == "gpt-4o"
    assert payload["user_prompt"] == "what is 2+2?"
    assert payload["final_response"] == "4"
    assert payload["input_tokens"] == 10
    assert payload["total_tokens"] == 12
    assert payload["status"] == "success"
    assert payload["tool_calls"][0]["tool_name"] == "calc"


def test_http_exporter_posts(monkeypatch):
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = req.headers
        captured["body"] = json.loads(req.data.decode())
        return FakeResp()

    monkeypatch.setattr("agentscope.exporters.http.urllib.request.urlopen", fake_urlopen)
    exp = HTTPExporter(endpoint="http://server", api_key="sk-1")
    exp.export(_build_trace())
    assert captured["url"] == "http://server/api/traces"
    # header keys are capitalized by urllib
    assert captured["headers"]["Authorization"] == "Bearer sk-1"
    assert captured["body"]["model_name"] == "gpt-4o"


def test_end_to_end_via_configured_exporter():
    buffer = io.StringIO()
    agentscope.configure(console=False)
    trace.add_exporter(ConsoleExporter(stream=buffer))

    @trace
    def hello(name):
        return f"hi {name}"

    hello("world")
    assert "hello" in buffer.getvalue()
