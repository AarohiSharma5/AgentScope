"""Model-layer tests for v0.4 multi-agent workflow orchestration.

Exercises the ORM relationships, recursive AgentNode tree, two-FK AgentMessage,
cascade deletes and the AgentRun cross-link (SET NULL). No API/service layer
exists yet for v0.4, so these operate directly against the models.
"""
import pytest

from app.extensions import db
from app.models.agent_trace import AgentStatus
from app.models.workflow_trace import (
    AgentMessage,
    AgentNode,
    ConversationRun,
    WorkflowDefinition,
    WorkflowExecution,
)
from app.services import trace_service


@pytest.fixture()
def conversation(request_trace):
    """A ConversationRun tied to a request trace."""
    conv = ConversationRun(
        request_trace_id=request_trace.id,
        conversation_name="Planning session",
        status=AgentStatus.RUNNING,
        conversation_metadata={"topic": "demo"},
    )
    db.session.add(conv)
    db.session.commit()
    return conv


def test_metadata_maps_to_reserved_column(conversation):
    # The Python attribute is prefixed but persists to a column named "metadata".
    assert conversation.conversation_metadata == {"topic": "demo"}
    row = db.session.execute(
        db.text("SELECT metadata FROM conversation_runs WHERE id = :id"),
        {"id": conversation.id},
    ).scalar()
    assert row is not None


def test_recursive_agent_nodes(conversation):
    root = AgentNode(
        conversation_run_id=conversation.id,
        agent_role="orchestrator",
        display_name="Root",
        execution_order=0,
        status=AgentStatus.RUNNING,
    )
    db.session.add(root)
    db.session.commit()

    child_a = AgentNode(
        conversation_run_id=conversation.id,
        parent_node_id=root.id,
        agent_role="researcher",
        execution_order=1,
        parallel_group="g1",
    )
    child_b = AgentNode(
        conversation_run_id=conversation.id,
        parent_node_id=root.id,
        agent_role="writer",
        execution_order=2,
        parallel_group="g1",
    )
    db.session.add_all([child_a, child_b])
    db.session.commit()

    db.session.refresh(root)
    assert {c.agent_role for c in root.children} == {"researcher", "writer"}
    assert child_a.parent.id == root.id
    # Conversation sees all nodes (root + nested), ordered by execution_order.
    assert [n.execution_order for n in conversation.nodes] == [0, 1, 2]


def test_agent_message_sender_receiver(conversation):
    a = AgentNode(conversation_run_id=conversation.id, agent_role="a", execution_order=0)
    b = AgentNode(conversation_run_id=conversation.id, agent_role="b", execution_order=1)
    db.session.add_all([a, b])
    db.session.commit()

    msg = AgentMessage(
        sender_node_id=a.id,
        receiver_node_id=b.id,
        message_type="handoff",
        content="over to you",
        token_usage={"total": 5},
        latency_ms=12.0,
    )
    db.session.add(msg)
    db.session.commit()

    assert msg.sender.id == a.id and msg.receiver.id == b.id
    assert a.sent_messages[0].id == msg.id
    assert b.received_messages[0].id == msg.id


def test_deleting_conversation_cascades(conversation):
    node = AgentNode(conversation_run_id=conversation.id, agent_role="a", execution_order=0)
    db.session.add(node)
    db.session.commit()
    db.session.add(
        AgentMessage(sender_node_id=node.id, message_type="note", content="hi")
    )
    db.session.commit()

    conv_id, node_id = conversation.id, node.id
    db.session.delete(conversation)
    db.session.commit()

    assert db.session.get(ConversationRun, conv_id) is None
    assert db.session.get(AgentNode, node_id) is None
    assert AgentMessage.query.filter_by(sender_node_id=node_id).count() == 0


def test_deleting_parent_node_cascades_children(conversation):
    root = AgentNode(conversation_run_id=conversation.id, agent_role="root", execution_order=0)
    db.session.add(root)
    db.session.commit()
    child = AgentNode(
        conversation_run_id=conversation.id,
        parent_node_id=root.id,
        agent_role="child",
        execution_order=1,
    )
    db.session.add(child)
    db.session.commit()
    child_id = child.id

    db.session.delete(root)
    db.session.commit()
    assert db.session.get(AgentNode, child_id) is None


def test_agent_run_crosslink_set_null_on_trace_delete(conversation, request_trace):
    run = trace_service.create_agent_run(
        request_id=request_trace.id, agent_name="Worker", status=AgentStatus.SUCCESS
    )
    node = AgentNode(
        conversation_run_id=conversation.id,
        agent_run_id=run.id,
        agent_role="worker",
        execution_order=0,
    )
    db.session.add(node)
    db.session.commit()
    assert node.agent_run.id == run.id

    # Deleting the cross-linked run nulls the link but keeps the node.
    node_id = node.id
    db.session.delete(run)
    db.session.commit()
    db.session.expire_all()
    refreshed = db.session.get(AgentNode, node_id)
    assert refreshed is not None
    assert refreshed.agent_run_id is None


def test_workflow_definition_execution_relationship(conversation):
    wf = WorkflowDefinition(
        workflow_name="research-pipeline",
        description="two-agent research + write",
        version="1.0",
        workflow_json={"nodes": ["researcher", "writer"]},
    )
    db.session.add(wf)
    db.session.commit()

    execution = WorkflowExecution(
        workflow_definition_id=wf.id,
        conversation_run_id=conversation.id,
        status=AgentStatus.RUNNING,
        execution_metadata={"trigger": "manual"},
    )
    db.session.add(execution)
    db.session.commit()

    assert wf.executions[0].id == execution.id
    # One-to-one back from the conversation.
    assert conversation.workflow_execution.id == execution.id

    # Deleting the definition cascades to its executions.
    exec_id = execution.id
    db.session.delete(wf)
    db.session.commit()
    assert db.session.get(WorkflowExecution, exec_id) is None
