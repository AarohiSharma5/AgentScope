"""Tests for the v0.6 export / import subsystem.

Covers bundle collection, every export format, round-trip import (JSON + Trace
Bundle), replay-from-export, OpenTelemetry conversion, format extensibility and
the REST surface.
"""
import io
import json
import zipfile

import pytest

from app.exporting import (
    BundleKind,
    ExportFormat,
    exporter_registry,
    export_entity,
    import_data,
    inspect_data,
    list_formats,
    list_kinds,
    parse,
    replay_from_export,
    verify_checksum,
)
from app.exporting import collect
from app.exporting.exporters import Exporter, register_exporter
from app.models.agent_trace import AgentStatus
from app.orchestration import AgentOrchestrator
from app.services import evaluation_service, replay_service, workflow_service


_SPEC = {
    "name": "export-flow",
    "version": "1.0",
    "entry": "planner",
    "nodes": {
        "planner": {"type": "task", "role": "planner", "next": "researcher"},
        "researcher": {"type": "task", "role": "researcher", "next": "done"},
        "done": {"type": "end"},
    },
}


def _build_conversation() -> int:
    """Create a rich conversation with prompt, steps, tool/memory/retriever + a message."""
    orch = AgentOrchestrator(
        conversation_name="orig",
        workflow_name="export-flow",
        workflow_version="1.0",
        workflow_json=_SPEC,
    )
    planner = orch.create_agent("Planner", role="planner")
    researcher = orch.create_agent("Researcher", role="researcher", parent=planner)

    def planner_work():
        rec, run = orch.recorder, planner.run
        rec.record_prompt_assembly(
            run, system_prompt="You are a planner.", user_prompt="Plan it.",
            memory_context="prior", retrieved_context="ctx",
        )
        step = rec.add_step(run, step_type="llm", name="LLM", input="Plan it.")
        rec.record_tool(step, tool_name="search", arguments={"q": "x"}, result="found")
        rec.record_memory(step, memory_type="vector", query="x", retrieved_text="m", used=True)
        rt = rec.record_retriever(step, query="x", retrieved_documents=[{"id": "d1"}], num_documents=1)
        rec.record_retrieved_document(rt, document_id="d1", chunk_text="hello", similarity_score=0.9, selected=True)
        rec.finish_step(step, output="planned", token_usage={"input": 100, "output": 50, "total": 150}, cost=0.01)
        return "planned"

    def researcher_work():
        rec, run = orch.recorder, researcher.run
        step = rec.add_step(run, step_type="llm", name="LLM", input="research")
        rec.finish_step(step, output="researched", token_usage={"input": 200, "output": 100, "total": 300}, cost=0.02)
        return "researched"

    planner.execute(work=planner_work)
    researcher.execute(work=researcher_work)
    # A message between the two agents so the messages table is exercised.
    workflow_service.create_agent_message(
        sender_node_id=planner.node.id, receiver_node_id=researcher.node.id,
        message_type="instruction", content="go research", conversation_run_id=orch.conversation.id,
    )
    orch.finish()
    return orch.conversation.id


@pytest.fixture()
def conversation_id(app_ctx) -> int:
    return _build_conversation()


# -- Collection -------------------------------------------------------------


def test_collect_conversation_bundle(conversation_id):
    bundle = collect.collect(BundleKind.CONVERSATION, conversation_id)
    assert bundle["manifest"]["kind"] == BundleKind.CONVERSATION
    assert bundle["manifest"]["entity_id"] == conversation_id
    assert verify_checksum(bundle) is True
    roles = [n["role"] for n in bundle["payload"]["snapshot"]["nodes"]]
    assert roles == ["planner", "researcher"]
    assert len(bundle["payload"]["messages"]) == 1


def test_checksum_detects_tampering(conversation_id):
    bundle = collect.collect(BundleKind.CONVERSATION, conversation_id)
    bundle["payload"]["conversation"]["conversation_name"] = "tampered"
    assert verify_checksum(bundle) is False


def test_collect_missing_conversation_raises(app_ctx):
    from app.exporting import BundleError

    with pytest.raises(BundleError):
        collect.collect(BundleKind.CONVERSATION, 999999)


# -- Every export format ----------------------------------------------------


def test_export_json(conversation_id):
    result = export_entity(BundleKind.CONVERSATION, conversation_id, ExportFormat.JSON)
    parsed = json.loads(result.content)
    assert parsed["manifest"]["kind"] == BundleKind.CONVERSATION
    assert result.content_type == "application/json"
    assert result.filename.endswith(".json")


def test_export_csv(conversation_id):
    result = export_entity(BundleKind.CONVERSATION, conversation_id, ExportFormat.CSV)
    text = result.content.decode("utf-8")
    assert "step_type" in text  # primary table for conversations is "steps"
    assert result.content_type == "text/csv"


def test_export_otel_semantic_conventions(conversation_id):
    result = export_entity(BundleKind.CONVERSATION, conversation_id, ExportFormat.OTEL)
    doc = json.loads(result.content)
    spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert spans, "expected at least one span"
    keys = {a["key"] for span in spans for a in span["attributes"]}
    assert "gen_ai.operation.name" in keys
    assert "gen_ai.tool.name" in keys  # the planner made a tool call
    # A conversation root span with children (parent links present).
    assert any("parentSpanId" in span for span in spans)


def test_export_sqlite_is_a_real_database(conversation_id):
    result = export_entity(BundleKind.CONVERSATION, conversation_id, ExportFormat.SQLITE)
    assert result.content[:15] == b"SQLite format 3"
    import sqlite3
    import tempfile
    import os

    handle, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(handle)
    try:
        with open(path, "wb") as fh:
            fh.write(result.content)
        conn = sqlite3.connect(path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
    finally:
        os.unlink(path)
    assert "_manifest" in tables and "steps" in tables


def test_export_postgres_sql(conversation_id):
    result = export_entity(BundleKind.CONVERSATION, conversation_id, ExportFormat.POSTGRES)
    sql = result.content.decode("utf-8")
    assert "CREATE TABLE" in sql and "INSERT INTO" in sql
    assert sql.strip().endswith("COMMIT;")


def test_export_zip_contains_bundle(conversation_id):
    result = export_entity(BundleKind.CONVERSATION, conversation_id, ExportFormat.ZIP)
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert "bundle.json" in archive.namelist()


def test_export_trace_bundle_is_self_describing(conversation_id):
    result = export_entity(BundleKind.CONVERSATION, conversation_id, ExportFormat.BUNDLE)
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        names = archive.namelist()
    assert "bundle.json" in names
    assert "data.sqlite" in names
    assert "trace.otel.json" in names
    assert any(n.startswith("tables/") for n in names)


# -- Round-trip import ------------------------------------------------------


def test_json_round_trip_import(conversation_id):
    exported = export_entity(BundleKind.CONVERSATION, conversation_id, ExportFormat.JSON)
    summary = import_data(exported.content)["imported"]
    new_id = summary["entity_id"]
    assert new_id != conversation_id
    snap = replay_service.build_snapshot(new_id)
    assert [n["role"] for n in snap["nodes"]] == ["planner", "researcher"]
    # Sub-records survived the round trip.
    planner = snap["nodes"][0]
    assert planner["steps"][0]["tools"][0]["tool_name"] == "search"
    assert planner["prompt"]["system_prompt"] == "You are a planner."


def test_trace_bundle_round_trip(conversation_id):
    exported = export_entity(BundleKind.CONVERSATION, conversation_id, ExportFormat.BUNDLE)
    bundle = parse(exported.content)  # auto-detects zip
    assert bundle["manifest"]["kind"] == BundleKind.CONVERSATION
    summary = import_data(exported.content)["imported"]
    assert workflow_service.get_conversation(summary["entity_id"]) is not None


def test_imported_conversation_preserves_messages(conversation_id):
    exported = export_entity(BundleKind.CONVERSATION, conversation_id, ExportFormat.JSON)
    new_id = import_data(exported.content)["imported"]["entity_id"]
    conv = workflow_service.get_conversation(new_id)
    assert len(conv.messages) == 1
    assert conv.messages[0].content == "go research"


# -- Replay from exported traces --------------------------------------------


def test_replay_from_export(conversation_id):
    exported = export_entity(BundleKind.CONVERSATION, conversation_id, ExportFormat.JSON)
    result = replay_from_export(exported.content, model="gpt-4o", temperature=0.2)
    assert result["status"] == AgentStatus.SUCCESS
    assert result["replay_run_id"] is not None
    assert result["imported_conversation_run_id"] != conversation_id
    # The replay produced its own new traced conversation.
    assert result["replay_conversation_run_id"] not in (None, conversation_id)


def test_replay_from_export_rejects_non_conversation(conversation_id):
    from app.exporting import BundleError

    evaluation = evaluation_service.create_evaluation_run(conversation_id, evaluation_type="quality")
    evaluation_service.finish_evaluation_run(evaluation, overall_score=0.8)
    exported = export_entity(BundleKind.EVALUATION, evaluation.id, ExportFormat.JSON)
    with pytest.raises(BundleError):
        replay_from_export(exported.content)


# -- Workflow / evaluation / replay / analytics -----------------------------


def test_workflow_export_import_round_trip(conversation_id):
    workflow = workflow_service.list_workflows()[0][0]
    exported = export_entity(BundleKind.WORKFLOW, workflow.id, ExportFormat.JSON)
    new_id = import_data(exported.content)["imported"]["entity_id"]
    recreated = workflow_service.get_workflow(new_id)
    assert recreated.workflow_json["name"] == "export-flow"


def test_evaluation_export(conversation_id):
    evaluation = evaluation_service.create_evaluation_run(conversation_id, evaluation_type="quality")
    evaluation_service.add_metric(evaluation.id, "correctness", 0.9, weight=1.0)
    evaluation_service.finish_evaluation_run(evaluation, overall_score=0.9)
    bundle = collect.collect(BundleKind.EVALUATION, evaluation.id)
    assert bundle["payload"]["evaluation"]["metrics"][0]["metric_name"] == "correctness"


def test_replay_export(conversation_id):
    from app.orchestration import ReplayEngine

    replay = ReplayEngine().replay(conversation_id, model="gpt-4o-mini")
    bundle = collect.collect(BundleKind.REPLAY, replay.replay_run.id)
    assert bundle["payload"]["replay"]["replayed_model"] == "gpt-4o-mini"


def test_analytics_export(conversation_id):
    result = export_entity(BundleKind.ANALYTICS, None, ExportFormat.JSON)
    payload = json.loads(result.content)["payload"]
    assert "evaluation_analytics" in payload
    assert "request_metrics" in payload


# -- Discovery & extensibility ----------------------------------------------


def test_list_formats_and_kinds():
    formats = {f["format"] for f in list_formats()}
    assert ExportFormat.ALL <= formats
    kinds = list_kinds()
    assert BundleKind.CONVERSATION in kinds["exportable"]
    assert BundleKind.CONVERSATION in kinds["importable"]


def test_can_add_export_format_without_core_changes(conversation_id):
    class YamlishExporter(Exporter):
        format = "yamlish"
        content_type = "text/plain"
        extension = "yaml"
        description = "test-only format"

        def export(self, bundle):
            return f"kind: {bundle['manifest']['kind']}".encode("utf-8")

    register_exporter(YamlishExporter())
    try:
        assert "yamlish" in exporter_registry.formats()
        result = export_entity(BundleKind.CONVERSATION, conversation_id, "yamlish")
        assert result.content == b"kind: conversation"
    finally:
        exporter_registry._exporters.pop("yamlish", None)


def test_unknown_format_raises(conversation_id):
    from app.exporting import ExporterError

    with pytest.raises(ExporterError):
        export_entity(BundleKind.CONVERSATION, conversation_id, "nope")


def test_inspect_without_writing(conversation_id):
    exported = export_entity(BundleKind.CONVERSATION, conversation_id, ExportFormat.JSON)
    info = inspect_data(exported.content)
    assert info["manifest"]["kind"] == BundleKind.CONVERSATION
    assert info["checksum_valid"] is True


# -- REST -------------------------------------------------------------------


def test_api_export_formats(client):
    resp = client.get("/api/export/formats")
    assert resp.status_code == 200
    assert {f["format"] for f in resp.get_json()["formats"]} >= ExportFormat.ALL


def test_api_export_download(client, conversation_id):
    resp = client.get(f"/api/export/conversation/{conversation_id}?format=json")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["Content-Disposition"]
    assert json.loads(resp.data)["manifest"]["kind"] == "conversation"


def test_api_export_unknown_kind(client, conversation_id):
    assert client.get(f"/api/export/bogus/{conversation_id}").status_code == 400


def test_api_export_missing_entity(client, app_ctx):
    assert client.get("/api/export/conversation/999999?format=json").status_code == 404


def test_api_import_round_trip(client, conversation_id):
    exported = client.get(f"/api/export/conversation/{conversation_id}?format=json").data
    resp = client.post("/api/import", data=exported, content_type="application/json")
    assert resp.status_code == 201
    assert resp.get_json()["imported"]["kind"] == "conversation"


def test_api_import_replay(client, conversation_id):
    exported = client.get(f"/api/export/conversation/{conversation_id}?format=json").data
    resp = client.post("/api/import/replay?model=gpt-4o", data=exported, content_type="application/json")
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["replay_run_id"] is not None


def test_api_import_empty_body(client, app_ctx):
    assert client.post("/api/import", data=b"").status_code == 400
