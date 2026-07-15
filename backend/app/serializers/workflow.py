"""Serializers for multi-agent workflows and conversations (v0.4).

Pure functions (no DB access) that turn ORM instances into JSON-ready dicts,
reused across list and detail endpoints so response shapes stay consistent.
They build on the shared message/step serializers to avoid duplication.
"""
from collections import defaultdict

from ..models.workflow_trace import (
    AgentNode,
    ConversationRun,
    WorkflowDefinition,
    WorkflowExecution,
)
from .agent import serialize_step
from .common import iso as _iso
from .message import serialize_message, serialize_timeline_event


def _related_count(obj, count_attr: str, relationship: str) -> int:
    """Count of a relationship, preferring a prefetched value if the service set one.

    List endpoints attach a cheap ``func.count()`` (e.g. ``execution_count``) so
    the collection itself is never loaded just to call ``len()``. Detail
    endpoints, which eager-load the collection, fall back to ``len()``.
    """
    prefetched = getattr(obj, count_attr, None)
    if prefetched is not None:
        return prefetched
    return len(getattr(obj, relationship))


# -- Workflows --------------------------------------------------------------


def serialize_execution(execution: WorkflowExecution) -> dict:
    """Serialize one workflow execution (run of a definition)."""
    return {
        "id": execution.id,
        "workflow_definition_id": execution.workflow_definition_id,
        "conversation_run_id": execution.conversation_run_id,
        "status": execution.status,
        "started_at": _iso(execution.started_at),
        "finished_at": _iso(execution.finished_at),
        "latency_ms": execution.latency_ms,
        "metadata": execution.execution_metadata,
        "created_at": _iso(execution.created_at),
    }


def _workflow_nodes(spec: dict) -> list[dict]:
    """Flatten a workflow spec's nodes into a list representation."""
    nodes = (spec or {}).get("nodes") or {}
    result = []
    for node_id, node in nodes.items():
        result.append(
            {
                "id": node_id,
                "type": node.get("type"),
                "role": node.get("role"),
                "branches": node.get("branches"),
                "max_visits": node.get("max_visits"),
                "retries": node.get("retries"),
                "timeout_ms": node.get("timeout_ms"),
            }
        )
    return result


def _workflow_edges(spec: dict) -> list[dict]:
    """Derive directed edges from a workflow spec's transitions."""
    nodes = (spec or {}).get("nodes") or {}
    edges = []
    for node_id, node in nodes.items():
        if node.get("next"):
            edges.append({"from": node_id, "to": node["next"], "kind": "next"})
        if node.get("if_true"):
            edges.append({"from": node_id, "to": node["if_true"], "kind": "true"})
        if node.get("if_false"):
            edges.append({"from": node_id, "to": node["if_false"], "kind": "false"})
        for branch in node.get("branches") or []:
            edges.append({"from": node_id, "to": branch, "kind": "parallel"})
    return edges


def serialize_workflow_summary(workflow: WorkflowDefinition) -> dict:
    """Lightweight workflow representation for list endpoints."""
    return {
        "id": workflow.id,
        "workflow_name": workflow.workflow_name,
        "version": workflow.version,
        "description": workflow.description,
        "execution_count": _related_count(workflow, "execution_count", "executions"),
        "created_at": _iso(workflow.created_at),
        "updated_at": _iso(workflow.updated_at),
    }


def serialize_workflow_detail(workflow: WorkflowDefinition) -> dict:
    """Full workflow: definition, nodes, edges and execution history."""
    spec = workflow.workflow_json or {}
    detail = serialize_workflow_summary(workflow)
    detail.update(
        {
            "entry": spec.get("entry"),
            "definition": spec,
            "nodes": _workflow_nodes(spec),
            "edges": _workflow_edges(spec),
            "execution_history": [
                serialize_execution(e)
                for e in sorted(workflow.executions, key=lambda e: e.id, reverse=True)
            ],
        }
    )
    return detail


# -- Conversations ----------------------------------------------------------


def _node_totals(node: AgentNode) -> tuple:
    """Aggregate latency, tokens and cost for a node from its agent run/steps."""
    run = node.agent_run
    if run is None:
        return None, None, None
    steps = list(run.steps)
    total_tokens = 0
    total_cost = 0.0
    for step in steps:
        usage = step.token_usage or {}
        total_tokens += usage.get("total") or (
            (usage.get("input") or 0) + (usage.get("output") or 0)
        )
        total_cost += step.cost or 0
    return (
        run.latency_ms,
        total_tokens or None,
        round(total_cost, 6) if total_cost else None,
    )


def _serialize_node(node: AgentNode) -> dict:
    """Serialize a single agent node (no children), with run aggregates."""
    latency_ms, total_tokens, cost = _node_totals(node)
    return {
        "id": node.id,
        "name": node.display_name,
        "role": node.agent_role,
        "status": node.status,
        "execution_order": node.execution_order,
        "parallel_group": node.parallel_group,
        "parent_node_id": node.parent_node_id,
        "agent_run_id": node.agent_run_id,
        "latency_ms": latency_ms,
        "total_tokens": total_tokens,
        "cost": cost,
    }


def build_agent_tree(nodes: list[AgentNode]) -> list[dict]:
    """Build the recursive agent tree (roots -> children) from flat nodes."""
    by_parent: dict = defaultdict(list)
    for node in nodes:
        by_parent[node.parent_node_id].append(node)

    def _build(node: AgentNode) -> dict:
        data = _serialize_node(node)
        data["children"] = [_build(child) for child in by_parent.get(node.id, [])]
        return data

    return [_build(root) for root in by_parent.get(None, [])]


def _conversation_steps(nodes: list[AgentNode]) -> list[dict]:
    """Flatten the agent-run steps across a conversation's nodes, in order."""
    steps = []
    for node in sorted(nodes, key=lambda n: (n.execution_order or 0, n.id)):
        run = node.agent_run
        if run is None:
            continue
        for step in run.steps:
            data = serialize_step(step)
            data["agent_node_id"] = node.id
            data["agent"] = node.display_name
            steps.append(data)
    return steps


def serialize_conversation_summary(conversation: ConversationRun) -> dict:
    """Lightweight conversation representation for list endpoints."""
    return {
        "id": conversation.id,
        "conversation_name": conversation.conversation_name,
        "request_trace_id": conversation.request_trace_id,
        "status": conversation.status,
        "started_at": _iso(conversation.started_at),
        "finished_at": _iso(conversation.finished_at),
        "latency_ms": conversation.latency_ms,
        "agent_count": _related_count(conversation, "agent_count", "nodes"),
        "message_count": _related_count(conversation, "message_count", "messages"),
        "created_at": _iso(conversation.created_at),
    }


def serialize_conversation_detail(conversation: ConversationRun) -> dict:
    """Full conversation: general info, agent tree, messages, timeline and steps."""
    nodes = list(conversation.nodes)
    messages = list(conversation.messages)
    execution = conversation.workflow_execution

    detail = serialize_conversation_summary(conversation)
    detail.update(
        {
            "metadata": conversation.conversation_metadata,
            "workflow_execution": serialize_execution(execution) if execution else None,
            "agent_tree": build_agent_tree(nodes),
            "messages": [serialize_message(m) for m in messages],
            "timeline": [serialize_timeline_event(m) for m in messages],
            "steps": _conversation_steps(nodes),
        }
    )
    return detail
