"""Collect database entities into portable :mod:`bundle` payloads.

This is the *extract* half of export. It reads (never mutates) the ORM and
produces plain dicts, reusing the existing serializers and
``replay_service.build_snapshot`` so the exported shape matches the REST API and
what the replay engine already understands.

It also derives a flat, tabular *projection* of each bundle
(:func:`tables_for`) that the row-oriented exporters (CSV / SQLite / PostgreSQL)
consume, keeping that logic in one place.
"""
from __future__ import annotations

from typing import Optional

from ..serializers.evaluation import (
    serialize_evaluation_run,
    serialize_model_comparison,
    serialize_replay_run,
)
from ..serializers.workflow import (
    serialize_conversation_detail,
    serialize_workflow_detail,
    _workflow_edges,
    _workflow_nodes,
)
from ..services import evaluation_service, replay_service, trace_service, workflow_service
from .bundle import BundleError, BundleKind, make_bundle


# -- Conversation -----------------------------------------------------------


def collect_conversation(conversation_id: int) -> dict:
    """Build a conversation bundle: snapshot, messages and evaluation context."""
    conversation = workflow_service.get_conversation(conversation_id)
    if conversation is None:
        raise BundleError(f"conversation {conversation_id} not found")

    snapshot = replay_service.build_snapshot(conversation_id)
    detail = serialize_conversation_detail(conversation)
    messages = [_message_snapshot(m) for m in conversation.messages]
    evaluations = [serialize_evaluation_run(e) for e in conversation.evaluation_runs]
    replays = [serialize_replay_run(r) for r in conversation.replay_runs]
    comparisons = [serialize_model_comparison(c) for c in conversation.model_comparisons]

    payload = {
        "conversation": {
            "id": detail["id"],
            "conversation_name": detail["conversation_name"],
            "status": detail["status"],
            "started_at": detail["started_at"],
            "finished_at": detail["finished_at"],
            "latency_ms": detail["latency_ms"],
            "metadata": detail.get("metadata"),
        },
        "snapshot": snapshot,
        "messages": messages,
        "evaluations": evaluations,
        "replays": replays,
        "comparisons": comparisons,
    }
    counts = {
        "nodes": len(snapshot.get("nodes", []) if snapshot else []),
        "messages": len(messages),
        "evaluations": len(evaluations),
    }
    return make_bundle(BundleKind.CONVERSATION, payload, entity_id=conversation_id, counts=counts)


def _message_snapshot(message) -> dict:
    """A portable message dict keyed by the *original* node ids (remapped on import)."""
    return {
        "sender_node_id": message.sender_node_id,
        "receiver_node_id": message.receiver_node_id,
        "reply_to_id": message.reply_to_id,
        "message_type": message.message_type,
        "content": message.content,
        "token_usage": message.token_usage,
        "latency_ms": message.latency_ms,
        "metadata": message.message_metadata,
    }


# -- Workflow ---------------------------------------------------------------


def collect_workflow(workflow_id: int) -> dict:
    """Build a workflow bundle: the full definition + execution history."""
    workflow = workflow_service.get_workflow(workflow_id)
    if workflow is None:
        raise BundleError(f"workflow {workflow_id} not found")
    payload = serialize_workflow_detail(workflow)
    counts = {"executions": len(payload.get("execution_history", []))}
    return make_bundle(BundleKind.WORKFLOW, payload, entity_id=workflow_id, counts=counts)


# -- Replay -----------------------------------------------------------------


def collect_replay(replay_id: int) -> dict:
    """Build a replay bundle: the replay run + the snapshot it originated from."""
    replay = replay_service.get_replay_run(replay_id)
    if replay is None:
        raise BundleError(f"replay {replay_id} not found")
    payload = {
        "replay": serialize_replay_run(replay),
        "original_snapshot": replay_service.build_snapshot(
            replay.original_conversation_run_id
        ),
    }
    return make_bundle(BundleKind.REPLAY, payload, entity_id=replay_id)


# -- Evaluation -------------------------------------------------------------


def collect_evaluation(evaluation_id: int) -> dict:
    """Build an evaluation bundle: the run and its metrics."""
    evaluation = evaluation_service.get_evaluation_run(evaluation_id)
    if evaluation is None:
        raise BundleError(f"evaluation {evaluation_id} not found")
    payload = {"evaluation": serialize_evaluation_run(evaluation, include_metrics=True)}
    counts = {"metrics": len(payload["evaluation"].get("metrics", []))}
    return make_bundle(BundleKind.EVALUATION, payload, entity_id=evaluation_id, counts=counts)


# -- Analytics --------------------------------------------------------------


def collect_analytics() -> dict:
    """Build an analytics bundle: every dashboard's aggregate metrics + time series."""
    payload = {
        "request_metrics": trace_service.get_stats(),
        "agent_metrics": trace_service.get_agent_metrics(),
        "rag_metrics": trace_service.get_rag_metrics(),
        "workflow_metrics": workflow_service.get_workflow_metrics(),
        "evaluation_metrics": evaluation_service.get_evaluation_metrics(),
        "evaluation_analytics": evaluation_service.get_evaluation_analytics(),
    }
    return make_bundle(BundleKind.ANALYTICS, payload)


# -- Dispatch ---------------------------------------------------------------

_COLLECTORS = {
    BundleKind.CONVERSATION: collect_conversation,
    BundleKind.WORKFLOW: collect_workflow,
    BundleKind.REPLAY: collect_replay,
    BundleKind.EVALUATION: collect_evaluation,
}


def collect(kind: str, entity_id: Optional[int]) -> dict:
    """Collect a bundle for ``kind`` (analytics ignores ``entity_id``)."""
    if kind == BundleKind.ANALYTICS:
        return collect_analytics()
    collector = _COLLECTORS.get(kind)
    if collector is None:
        raise BundleError(f"cannot collect unknown kind: {kind!r}")
    if entity_id is None:
        raise BundleError(f"kind '{kind}' requires an entity id")
    return collector(entity_id)


# -- Tabular projection (for CSV / SQLite / PostgreSQL) ---------------------


def tables_for(bundle: dict) -> dict[str, list[dict]]:
    """Project a bundle into ``{table_name: [flat rows]}`` for row exporters."""
    kind = bundle["manifest"]["kind"]
    payload = bundle["payload"]
    builder = {
        BundleKind.CONVERSATION: _conversation_tables,
        BundleKind.WORKFLOW: _workflow_tables,
        BundleKind.REPLAY: _replay_tables,
        BundleKind.EVALUATION: _evaluation_tables,
        BundleKind.ANALYTICS: _analytics_tables,
    }[kind]
    return {name: rows for name, rows in builder(payload).items() if rows}


#: The most useful single table per kind (what a plain CSV export contains).
PRIMARY_TABLE = {
    BundleKind.CONVERSATION: "steps",
    BundleKind.WORKFLOW: "executions",
    BundleKind.REPLAY: "replays",
    BundleKind.EVALUATION: "metrics",
    BundleKind.ANALYTICS: "daily",
}


def _conversation_tables(payload: dict) -> dict[str, list[dict]]:
    snapshot = payload.get("snapshot") or {}
    nodes, steps, tools, memory, retrievers = [], [], [], [], []
    for node in snapshot.get("nodes", []):
        nodes.append(
            {
                "node_id": node.get("node_id"),
                "role": node.get("role"),
                "name": node.get("name"),
                "parent_node_id": node.get("parent_node_id"),
                "parallel_group": node.get("parallel_group"),
                "output": node.get("output"),
            }
        )
        for index, step in enumerate(node.get("steps", [])):
            usage = step.get("token_usage") or {}
            steps.append(
                {
                    "node_id": node.get("node_id"),
                    "step_index": index,
                    "step_type": step.get("step_type"),
                    "name": step.get("name"),
                    "input": step.get("input"),
                    "output": step.get("output"),
                    "cost": step.get("cost"),
                    "input_tokens": usage.get("input"),
                    "output_tokens": usage.get("output"),
                    "total_tokens": usage.get("total"),
                }
            )
            for tool in step.get("tools", []):
                tools.append({"node_id": node.get("node_id"), "step_index": index, **tool})
            for mem in step.get("memory", []):
                memory.append({"node_id": node.get("node_id"), "step_index": index, **mem})
            for retr in step.get("retrievers", []):
                retrievers.append(
                    {
                        "node_id": node.get("node_id"),
                        "step_index": index,
                        "query": retr.get("query"),
                        "num_documents": retr.get("num_documents"),
                        "embedding_time_ms": retr.get("embedding_time_ms"),
                        "retrieval_time_ms": retr.get("retrieval_time_ms"),
                    }
                )
    return {
        "conversation": [payload.get("conversation", {})],
        "nodes": nodes,
        "steps": steps,
        "tools": tools,
        "memory": memory,
        "retrievers": retrievers,
        "messages": payload.get("messages", []),
    }


def _workflow_tables(payload: dict) -> dict[str, list[dict]]:
    spec = payload.get("definition") or {}
    return {
        "workflow": [
            {
                "id": payload.get("id"),
                "workflow_name": payload.get("workflow_name"),
                "version": payload.get("version"),
                "description": payload.get("description"),
                "entry": payload.get("entry"),
            }
        ],
        "nodes": _workflow_nodes(spec),
        "edges": _workflow_edges(spec),
        "executions": payload.get("execution_history", []),
    }


def _replay_tables(payload: dict) -> dict[str, list[dict]]:
    return {"replays": [payload.get("replay", {})]}


def _evaluation_tables(payload: dict) -> dict[str, list[dict]]:
    evaluation = payload.get("evaluation", {})
    row = {k: v for k, v in evaluation.items() if k != "metrics"}
    return {"evaluation": [row], "metrics": evaluation.get("metrics", [])}


def _analytics_tables(payload: dict) -> dict[str, list[dict]]:
    analytics = payload.get("evaluation_analytics") or {}
    summary = {
        f"{group}.{key}": value
        for group in ("request_metrics", "agent_metrics", "rag_metrics",
                      "workflow_metrics", "evaluation_metrics")
        for key, value in (payload.get(group) or {}).items()
    }
    return {"daily": analytics.get("daily", []), "summary": [summary] if summary else []}
