"""Tests for the v0.4 agent communication layer (MessageService + SDK helpers)."""
import pytest

from app.models.workflow_trace import AgentMessage, MessageType
from app.orchestration import AgentOrchestrator
from app.serializers.message import serialize_message, serialize_timeline_event
from app.services.message_service import MessageService, message_service


@pytest.fixture()
def team(app_ctx):
    """A conversation with three agents; returns (orchestrator, planner, a, b)."""
    orch = AgentOrchestrator(conversation_name="team")
    planner = orch.create_agent(name="Planner", role="planner")
    a = orch.create_agent(name="ResearcherA", role="researcher")
    b = orch.create_agent(name="ResearcherB", role="researcher")
    return orch, planner, a, b


# -- Message types + direct send -------------------------------------------


def test_send_records_all_required_fields(team):
    _, planner, a, _ = team
    msg = message_service.send(
        sender=planner.node,
        receiver=a.node,
        message_type=MessageType.INSTRUCTION,
        content="Research LangSmith.",
        token_usage={"input": 10, "output": 0, "total": 10},
        latency_ms=12.5,
        metadata={"priority": "high"},
    )
    assert msg.id is not None
    assert msg.sender_node_id == planner.node.id
    assert msg.receiver_node_id == a.node.id
    assert msg.message_type == MessageType.INSTRUCTION
    assert msg.created_at is not None            # timestamp
    assert msg.latency_ms == 12.5                # latency
    assert msg.token_usage["total"] == 10        # token usage
    assert msg.message_metadata["priority"] == "high"  # metadata
    # Conversation inferred from the sender node.
    assert msg.conversation_run_id == planner.node.conversation_run_id


def test_unknown_message_type_rejected(team):
    _, planner, a, _ = team
    with pytest.raises(ValueError, match="unknown message_type"):
        message_service.send(planner.node, a.node, message_type="gossip", content="x")


def test_all_message_types_supported(team):
    _, planner, a, _ = team
    for mtype in MessageType.ALL:
        msg = message_service.send(planner.node, a.node, message_type=mtype, content="c")
        assert msg.message_type == mtype


# -- Broadcast --------------------------------------------------------------


def test_broadcast_to_all_other_participants(team):
    orch, planner, a, b = team
    messages = planner.broadcast("Kickoff.", message_type=MessageType.INSTRUCTION)

    # Planner broadcasts to A and B (not itself).
    assert len(messages) == 2
    assert {m.receiver_node_id for m in messages} == {a.node.id, b.node.id}
    # All rows share one broadcast_id.
    broadcast_ids = {m.message_metadata["broadcast_id"] for m in messages}
    assert len(broadcast_ids) == 1


def test_broadcast_to_explicit_receivers(team):
    _, planner, a, b = team
    messages = message_service.broadcast(
        sender=planner.node,
        message_type=MessageType.OBSERVATION,
        content="fyi",
        receivers=[a.node],
    )
    assert len(messages) == 1
    assert messages[0].receiver_node_id == a.node.id


# -- Reply threading --------------------------------------------------------


def test_reply_threads_back_to_sender(team):
    _, planner, a, _ = team
    question = planner.ask(a, "What is LangSmith?")
    answer = a.reply(question, "An LLM observability platform.")

    assert answer.reply_to_id == question.id
    assert answer.receiver_node_id == planner.node.id   # addressed back to asker
    assert answer.message_type == MessageType.ANSWER
    assert question.message_type == MessageType.QUESTION

    thread = message_service.thread(question)
    assert [m.id for m in thread] == [question.id, answer.id]


# -- Conversation history + timeline ---------------------------------------


def test_conversation_history_is_ordered(team):
    orch, planner, a, b = team
    planner.instruct(a, "step 1")
    a.observe("did step 1", receiver=planner)
    b.answer(planner, "step 2 done")

    history = message_service.conversation_history(orch.conversation.id)
    assert len(history) == 3
    contents = [m.content for m in history]
    assert contents == ["step 1", "did step 1", "step 2 done"]

    # Descending order flips it.
    desc = message_service.conversation_history(orch.conversation.id, ascending=False)
    assert [m.content for m in desc] == list(reversed(contents))


def test_timeline_events_serialize(team):
    orch, planner, a, _ = team
    planner.ask(a, "ping", latency_ms=3.0)

    events = [serialize_timeline_event(m) for m in message_service.timeline(orch.conversation.id)]
    assert events[0]["from"] == "Planner"
    assert events[0]["to"] == "ResearcherA"
    assert events[0]["message_type"] == MessageType.QUESTION
    assert events[0]["latency_ms"] == 3.0


def test_broadcast_appears_in_history_per_receiver(team):
    orch, planner, a, b = team
    planner.broadcast("hello all")
    history = message_service.conversation_history(orch.conversation.id)
    assert len(history) == 2  # one row per receiver


# -- Search -----------------------------------------------------------------


def test_search_by_text_and_type(team):
    orch, planner, a, b = team
    planner.instruct(a, "Investigate pricing")
    planner.ask(b, "What is the pricing model?")
    a.answer(planner, "Pricing is usage based")

    # Full-text (case-insensitive) on content.
    hits, total = message_service.search(text="pricing", conversation_run_id=orch.conversation.id)
    assert total == 3
    assert all("pricing" in m.content.lower() for m in hits)

    # Filter by type.
    answers, total = message_service.search(
        conversation_run_id=orch.conversation.id, message_type=MessageType.ANSWER
    )
    assert total == 1
    assert answers[0].message_type == MessageType.ANSWER

    # Filter by sender.
    from_planner, total = message_service.search(
        conversation_run_id=orch.conversation.id, sender_node_id=planner.node.id
    )
    assert total == 2


def test_search_pagination(team):
    orch, planner, a, _ = team
    for i in range(5):
        planner.instruct(a, f"task {i}")

    page1, total = message_service.search(conversation_run_id=orch.conversation.id, limit=2, offset=0)
    assert total == 5 and len(page1) == 2


# -- Serialization ----------------------------------------------------------


def test_serialize_message_shape(team):
    _, planner, a, _ = team
    msg = planner.instruct(a, "go", token_usage={"total": 5})
    data = serialize_message(msg)
    assert data["sender"] == "Planner"
    assert data["receiver"] == "ResearcherA"
    assert data["sender_role"] == "planner"
    assert data["message_type"] == MessageType.INSTRUCTION
    assert data["token_usage"] == {"total": 5}
    assert data["timestamp"] is not None
    assert set(data) >= {
        "sender", "receiver", "timestamp", "latency_ms", "token_usage", "metadata",
    }


def test_search_no_n_plus_1_on_participants(team):
    orch, planner, a, b = team
    from sqlalchemy import event

    from app.extensions import db

    def _count_queries():
        counter = {"n": 0}

        def _bump(conn, cursor, statement, params, context, executemany):
            counter["n"] += 1

        event.listen(db.engine, "before_cursor_execute", _bump)
        try:
            db.session.expire_all()
            items, _ = message_service.search(conversation_run_id=orch.conversation.id)
            _ = [serialize_message(m) for m in items]
        finally:
            event.remove(db.engine, "before_cursor_execute", _bump)
        return counter["n"]

    for i in range(3):
        planner.instruct(a, f"m{i}")
    small = _count_queries()

    for i in range(10):
        planner.instruct(a, f"n{i}")
    large = _count_queries()

    # Query count is constant (eager-loaded), not proportional to message count.
    assert small == large


def test_shared_instance_is_message_service_class():
    assert isinstance(message_service, MessageService)
