"""Importers: parse a wire format back into a :mod:`bundle`, and reconstruct it.

Two responsibilities:

* **Parsing** — turn uploaded bytes (JSON, zip archive, Trace Bundle, SQLite
  file) back into the canonical bundle envelope. Format is auto-detected from
  magic bytes when not specified.
* **Reconstruction** — rebuild an importable bundle (a conversation or workflow)
  into fresh database rows via the existing services, remapping the original
  ids. A reconstructed conversation is fully traced again and can be replayed,
  which is how "replay from exported traces" works.
"""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import os
import zipfile
from abc import ABC, abstractmethod
from typing import Optional

from ..models.agent_trace import AgentStatus
from ..services import trace_service, workflow_service
from .bundle import BundleError, BundleKind, ExportFormat, validate_bundle


class ImporterError(Exception):
    """Raised when uploaded data cannot be parsed into a bundle."""


# -- Parsing ----------------------------------------------------------------


class Importer(ABC):
    format: str = ""

    @abstractmethod
    def parse(self, data: bytes) -> dict:
        """Parse raw bytes into a validated bundle envelope."""


class JsonImporter(Importer):
    format = ExportFormat.JSON

    def parse(self, data: bytes) -> dict:
        try:
            bundle = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ImporterError(f"invalid JSON bundle: {exc}") from exc
        return validate_bundle(bundle)


class ZipImporter(Importer):
    """Reads ``bundle.json`` out of a zip archive / Trace Bundle."""

    format = ExportFormat.ZIP

    def parse(self, data: bytes) -> dict:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
                if "bundle.json" not in names:
                    raise ImporterError("archive does not contain bundle.json")
                bundle = json.loads(archive.read("bundle.json").decode("utf-8"))
        except zipfile.BadZipFile as exc:
            raise ImporterError(f"invalid zip archive: {exc}") from exc
        return validate_bundle(bundle)


class SqliteImporter(Importer):
    """Reconstructs a bundle from a SQLite export's ``_manifest`` table."""

    format = ExportFormat.SQLITE

    def parse(self, data: bytes) -> dict:
        handle, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(handle)
        try:
            with open(path, "wb") as fh:
                fh.write(data)
            connection = sqlite3.connect(path)
            try:
                rows = connection.execute("SELECT key, value FROM _manifest").fetchall()
            except sqlite3.DatabaseError as exc:
                raise ImporterError(f"invalid SQLite export: {exc}") from exc
            finally:
                connection.close()
        finally:
            os.unlink(path)
        manifest = {k: v for k, v in rows}
        # The SQLite view is tabular-only; a payload cannot be losslessly
        # reconstructed from it, so it is import-for-inspection, not for replay.
        raise ImporterError(
            "SQLite exports are tabular snapshots; import JSON, zip or bundle "
            f"formats to reconstruct (manifest kind={manifest.get('kind')!r})"
        )


_IMPORTERS = {
    ExportFormat.JSON: JsonImporter(),
    ExportFormat.ZIP: ZipImporter(),
    ExportFormat.BUNDLE: ZipImporter(),
    ExportFormat.SQLITE: SqliteImporter(),
}


def detect_format(data: bytes) -> str:
    """Guess the wire format from magic bytes."""
    if data[:4] == b"PK\x03\x04":
        return ExportFormat.ZIP
    if data[:15] == b"SQLite format 3":
        return ExportFormat.SQLITE
    return ExportFormat.JSON


def parse(data: bytes, fmt: Optional[str] = None) -> dict:
    """Parse ``data`` into a bundle, auto-detecting the format when omitted."""
    fmt = fmt or detect_format(data)
    importer = _IMPORTERS.get(fmt)
    if importer is None:
        raise ImporterError(f"no importer for format: {fmt!r}")
    return importer.parse(data)


# -- Reconstruction into the database ---------------------------------------


def import_bundle_to_db(bundle: dict) -> dict:
    """Reconstruct an importable bundle into fresh DB rows.

    Returns a summary including the new entity id. Raises :class:`BundleError`
    for kinds that reference (rather than own) their data and so cannot be
    recreated standalone (replay / evaluation / analytics).
    """
    validate_bundle(bundle)
    kind = bundle["manifest"]["kind"]
    if kind == BundleKind.CONVERSATION:
        return _import_conversation(bundle["payload"])
    if kind == BundleKind.WORKFLOW:
        return _import_workflow(bundle["payload"])
    raise BundleError(
        f"kind '{kind}' is not importable "
        f"(importable: {sorted(BundleKind.IMPORTABLE)})"
    )


def _import_workflow(payload: dict) -> dict:
    """Recreate a workflow definition from its exported spec."""
    definition = workflow_service.create_workflow_definition(
        workflow_name=payload.get("workflow_name") or "imported-workflow",
        description=payload.get("description"),
        version=payload.get("version"),
        workflow_json=payload.get("definition"),
    )
    return {"kind": BundleKind.WORKFLOW, "entity_id": definition.id}


def _import_conversation(payload: dict) -> dict:
    """Recreate a conversation graph (trace, nodes, runs, steps, messages)."""
    snapshot = payload.get("snapshot") or {}
    conversation_info = payload.get("conversation") or {}

    trace = trace_service.create_trace(
        {
            "user_prompt": snapshot.get("user_prompt"),
            "system_prompt": snapshot.get("system_prompt"),
            "model_name": snapshot.get("request_model") or "imported",
        }
    )
    conversation = workflow_service.create_conversation_run(
        request_trace_id=trace.id,
        conversation_name=conversation_info.get("conversation_name"),
        status=AgentStatus.RUNNING,
        metadata={"imported": True, "source_conversation_id": snapshot.get("conversation_run_id")},
    )

    if snapshot.get("workflow_json"):
        definition = workflow_service.create_workflow_definition(
            workflow_name=conversation_info.get("conversation_name") or "imported-workflow",
            workflow_json=snapshot["workflow_json"],
        )
        workflow_service.create_workflow_execution(
            workflow_definition_id=definition.id,
            conversation_run_id=conversation.id,
            status=AgentStatus.SUCCESS,
        )

    node_id_map: dict = {}   # old node id -> new node id
    run_id_map: dict = {}    # old node id -> new agent_run id
    for order, node in enumerate(snapshot.get("nodes", [])):
        _import_node(trace.id, conversation.id, node, order, node_id_map, run_id_map)

    _import_messages(payload.get("messages", []), conversation.id, node_id_map)

    workflow_service.finish_conversation_run(
        conversation,
        status=conversation_info.get("status") or AgentStatus.SUCCESS,
        latency_ms=conversation_info.get("latency_ms"),
    )
    return {
        "kind": BundleKind.CONVERSATION,
        "entity_id": conversation.id,
        "request_trace_id": trace.id,
        "nodes": len(node_id_map),
    }


def _import_node(request_id, conversation_id, node, order, node_id_map, run_id_map) -> None:
    """Recreate one agent node: its run, prompt, steps and sub-records."""
    old_node_id = node.get("node_id")
    parent_run_id = run_id_map.get(node.get("parent_node_id"))

    run = trace_service.create_agent_run(
        request_id=request_id,
        agent_name=node.get("name") or node.get("role") or f"agent-{old_node_id}",
        agent_type=node.get("role"),
        parent_run_id=parent_run_id,
    )

    prompt = node.get("prompt")
    if prompt:
        trace_service.create_prompt_assembly(
            run.id,
            system_prompt=prompt.get("system_prompt"),
            conversation_context=prompt.get("conversation_context"),
            retrieved_context=prompt.get("retrieved_context"),
            memory_context=prompt.get("memory_context"),
            user_prompt=prompt.get("user_prompt"),
            assembled_prompt=prompt.get("assembled_prompt"),
        )

    for step_number, step in enumerate(node.get("steps", []), start=1):
        _import_step(run.id, step_number, step)

    trace_service.finish_agent_run(run, status=AgentStatus.SUCCESS)

    new_node = workflow_service.create_agent_node(
        conversation_run_id=conversation_id,
        agent_run_id=run.id,
        agent_role=node.get("role"),
        display_name=node.get("name"),
        parent_node_id=node_id_map.get(node.get("parent_node_id")),
        execution_order=order,
        parallel_group=node.get("parallel_group"),
        status=AgentStatus.SUCCESS,
    )
    node_id_map[old_node_id] = new_node.id
    run_id_map[old_node_id] = run.id


def _import_step(agent_run_id, step_number, step) -> None:
    """Recreate one step with its tool / memory / retriever sub-records."""
    new_step = trace_service.create_agent_step(
        agent_run_id=agent_run_id,
        step_number=step_number,
        step_type=step.get("step_type"),
        name=step.get("name"),
        input=step.get("input"),
    )

    for tool in step.get("tools", []):
        trace_service.create_tool_execution(
            step_id=new_step.id,
            tool_name=tool.get("tool_name") or "tool",
            arguments=tool.get("arguments"),
            result=tool.get("result"),
            status=tool.get("status") or AgentStatus.SUCCESS,
            latency_ms=tool.get("latency_ms"),
        )
    for mem in step.get("memory", []):
        trace_service.create_memory_access(
            step_id=new_step.id,
            memory_type=mem.get("memory_type"),
            query=mem.get("query"),
            retrieved_text=mem.get("retrieved_text"),
            similarity_score=mem.get("similarity_score"),
            used=mem.get("used"),
            latency_ms=mem.get("latency_ms"),
        )
    for retr in step.get("retrievers", []):
        new_retr = trace_service.create_retriever_trace(
            step_id=new_step.id,
            query=retr.get("query"),
            retrieved_documents=retr.get("retrieved_documents"),
            embedding_time_ms=retr.get("embedding_time_ms"),
            retrieval_time_ms=retr.get("retrieval_time_ms"),
            num_documents=retr.get("num_documents"),
        )
        for doc in retr.get("documents", []):
            trace_service.create_retrieved_document(
                new_retr.id,
                document_id=doc.get("document_id"),
                document_name=doc.get("document_name"),
                document_source=doc.get("document_source"),
                chunk_index=doc.get("chunk_index"),
                chunk_text=doc.get("chunk_text"),
                similarity_score=doc.get("similarity_score"),
                selected=bool(doc.get("selected")),
            )

    trace_service.finish_agent_step(
        new_step,
        output=step.get("output"),
        token_usage=step.get("token_usage"),
        cost=step.get("cost"),
    )


def _import_messages(messages, conversation_id, node_id_map) -> None:
    """Recreate agent messages, remapping sender/receiver to the new node ids."""
    for message in messages:
        sender = node_id_map.get(message.get("sender_node_id"))
        if sender is None:
            continue  # a message with no reconstructable sender is dropped
        workflow_service.create_agent_message(
            sender_node_id=sender,
            receiver_node_id=node_id_map.get(message.get("receiver_node_id")),
            message_type=message.get("message_type"),
            content=message.get("content"),
            token_usage=message.get("token_usage"),
            latency_ms=message.get("latency_ms"),
            metadata=message.get("metadata"),
            conversation_run_id=conversation_id,
        )
