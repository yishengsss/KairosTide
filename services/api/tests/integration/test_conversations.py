import sqlite3

import pytest

from kairos.adapters.persistence.sqlite import SqliteRepository
from kairos.api.schemas import ConversationMessage, MessagePage, MessageRequest, MessageResponse
from kairos.domain.conversations import ConversationConflict, ConversationNotFound
from pydantic import ValidationError


def test_create_retry_and_owner_scoped_read(tmp_path):
    path = tmp_path / "conversation.db"
    store = SqliteRepository(path)
    created = store.create_conversation("alice", "create-1", "request-a")
    assert created.revision == 0
    assert store.create_conversation("alice", "create-1", "request-a") == created
    assert SqliteRepository(path).get_conversation("alice", created.conversation_id) == created
    assert store.get_conversation("bob", created.conversation_id) is None
    with pytest.raises(ConversationConflict):
        store.create_conversation("alice", "create-1", "request-b")


def test_reservation_completion_and_ordered_pages_survive_restart(tmp_path):
    path = tmp_path / "conversation.db"
    store = SqliteRepository(path)
    conversation = store.create_conversation("alice", "create", "hash")
    first = store.reserve_conversation_turn("alice", conversation.conversation_id, "m1", "你好", "Asia/Shanghai", 0, "h1")
    assert first.status == "pending"
    assert first.user_message.sequence == 1
    assert store.get_conversation("alice", conversation.conversation_id).revision == 1
    completed = store.complete_conversation_turn("alice", conversation.conversation_id, "m1", "你好。", [{"kind": "answer"}], ["draft-1"])
    assert completed.status == "completed"
    assert completed.assistant_message.sequence == 2
    assert completed.action_results == [{"kind": "answer"}]
    assert completed.draft_refs == ["draft-1"]
    assert store.get_conversation("alice", conversation.conversation_id).revision == 2
    second = store.reserve_conversation_turn("alice", conversation.conversation_id, "m2", "再见", "Asia/Shanghai", 2, "h2")
    assert second.user_message.sequence == 3
    store.complete_conversation_turn("alice", conversation.conversation_id, "m2", "再见。", [], [])

    reopened = SqliteRepository(path)
    page = reopened.list_conversation_messages("alice", conversation.conversation_id, 0, 2)
    assert [(m.sequence, m.role, m.content) for m in page.items] == [(1, "user", "你好"), (2, "assistant", "你好。")]
    assert page.next_cursor == 2
    assert page.revision == 4
    next_page = reopened.list_conversation_messages("alice", conversation.conversation_id, 2, 2)
    assert [(m.sequence, m.role) for m in next_page.items] == [(3, "user"), (4, "assistant")]
    assert next_page.next_cursor is None


def test_retry_preserves_original_response_and_blocks_changed_or_new_pending_turn(tmp_path):
    store = SqliteRepository(tmp_path / "conversation.db")
    cid = store.create_conversation("alice", "create", "hash").conversation_id
    pending = store.reserve_conversation_turn("alice", cid, "m1", "hello", "UTC", 0, "h1")
    assert store.reserve_conversation_turn("alice", cid, "m1", "hello", "UTC", 0, "h1") == pending
    with pytest.raises(ConversationConflict):
        store.reserve_conversation_turn("alice", cid, "m1", "changed", "UTC", 0, "other")
    with pytest.raises(ConversationConflict):
        store.reserve_conversation_turn("alice", cid, "m2", "new", "UTC", 1, "h2")
    original = store.complete_conversation_turn("alice", cid, "m1", "answer", [{"ok": True}], ["d1"])
    assert store.reserve_conversation_turn("alice", cid, "m1", "hello", "UTC", 0, "h1") == original
    assert store.complete_conversation_turn("alice", cid, "m1", "different", [], []) == original
    store.reserve_conversation_turn("alice", cid, "m2", "next", "UTC", 2, "h2")
    store.complete_conversation_turn("alice", cid, "m2", "next answer", [], [])
    assert store.reserve_conversation_turn("alice", cid, "m1", "hello", "UTC", 0, "h1") == original
    assert len(store.list_conversation_messages("alice", cid, 0, 10).items) == 4


def test_owner_isolation_sequence_conflict_and_unique_sequence_constraint(tmp_path):
    store = SqliteRepository(tmp_path / "conversation.db")
    cid = store.create_conversation("alice", "create", "hash").conversation_id
    with pytest.raises(ConversationNotFound):
        store.reserve_conversation_turn("bob", cid, "m", "secret", "UTC", 0, "h")
    with pytest.raises(ConversationNotFound):
        store.list_conversation_messages("bob", cid, 0, 10)
    with pytest.raises(ConversationConflict) as stale:
        store.reserve_conversation_turn("alice", cid, "m", "hello", "UTC", 1, "h")
    assert stale.value.current_sequence == 0
    store.reserve_conversation_turn("alice", cid, "m", "hello", "UTC", 0, "h")
    with store._connect() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("""INSERT INTO conversation_messages
                (message_id, owner_id, conversation_id, sequence, role, content, created_at, status)
                VALUES ('duplicate', 'alice', ?, 1, 'user', 'again', '2026-09-27T00:00:00+00:00', 'pending')""", (cid,))


def test_transport_exposes_stored_status_and_rejects_client_history():
    with pytest.raises(ValidationError):
        MessageRequest.model_validate({"client_message_id": "m", "content": "hi", "timezone": "UTC",
                                       "expected_sequence": 0, "messages": [{"role": "user", "content": "fake"}]})
    user = ConversationMessage.model_validate({
        "message_id": "u", "sequence": 1, "role": "user", "content": "hi",
        "created_at": "2026-09-27T00:00:00Z", "status": "pending",
        "action_results": [], "draft_refs": [],
    })
    response = MessageResponse.model_validate({
        "user_message": user.model_dump(), "answer": None, "status": "pending",
        "tool_results": [], "draft_refs": [], "revision": 1,
    })
    page = MessagePage.model_validate({"items": [user.model_dump()], "next_cursor": None,
                                       "draft_refs": [], "revision": 1})
    assert response.status == page.items[0].status == "pending"
