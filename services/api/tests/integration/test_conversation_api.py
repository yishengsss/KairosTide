from datetime import UTC, datetime

from fastapi.testclient import TestClient

from kairos.adapters.persistence.sqlite import SqliteRepository
from kairos.application.assistant_tasks import ModelTurn
from kairos.domain.drafts import Candidate, make_draft
from kairos.main import create_app


class FixedClock:
    def now(self):
        return datetime(2026, 9, 27, 9, 40, tzinfo=UTC)


class RecordingModel:
    def __init__(self, answer="收到"):
        self.answer = answer
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append((messages, tools))
        return ModelTurn(self.answer)


def create(client):
    response = client.post("/api/v1/conversations", headers={"Idempotency-Key": "create-1"})
    assert response.status_code == 200
    return response.json()["conversation_id"]


def send(client, conversation_id, message_id, content, sequence):
    return client.post(f"/api/v1/conversations/{conversation_id}/messages",
        headers={"Idempotency-Key": message_id}, json={
            "client_message_id": message_id, "content": content,
            "timezone": "Asia/Shanghai", "expected_sequence": sequence,
        })


def test_create_append_read_and_owner_scope(tmp_path):
    db = tmp_path / "conversation-api.sqlite3"
    model = RecordingModel()
    with TestClient(create_app(str(db), owner_id="owner-a", clock=FixedClock(),
                               assistant_task_model=model)) as client:
        conversation_id = create(client)
        response = send(client, conversation_id, "msg-1", "十分钟后有个会议", 0)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["user_message"]["content"] == "十分钟后有个会议"
        assert body["answer"]["content"] == "收到"
        page = client.get(f"/api/v1/conversations/{conversation_id}/messages")
        assert page.status_code == 200
        assert [item["content"] for item in page.json()["items"]] == ["十分钟后有个会议", "收到"]

    with TestClient(create_app(str(db), owner_id="owner-b", clock=FixedClock(),
                               assistant_task_model=RecordingModel())) as foreign:
        assert foreign.get(f"/api/v1/conversations/{conversation_id}/messages").status_code == 404
        assert send(foreign, conversation_id, "foreign-message", "查询", 0).status_code == 404


def test_thirteenth_turn_uses_bounded_context_and_keeps_latest(tmp_path):
    model = RecordingModel("助理回复" * 500)
    latest = "消息 12 " + "x" * 3000
    with TestClient(create_app(str(tmp_path / "long-chat.sqlite3"), owner_id="owner-a",
                               clock=FixedClock(), assistant_task_model=model)) as client:
        conversation_id = create(client)
        sequence = 0
        for index in range(13):
            content = latest if index == 12 else f"消息 {index} " + "x" * 3000
            response = send(client, conversation_id, f"turn-{index}", content, sequence)
            assert response.status_code == 200, response.text
            sequence = response.json()["revision"]

    assert len(model.calls) == 13
    context = model.calls[-1][0]
    turn_context = [item for item in context if item["role"] in {"user", "assistant"}]
    assert len(turn_context) <= 24
    assert sum(len(item["content"]) for item in turn_context) <= 32_000
    assert turn_context[-1] == {"role": "user", "content": latest}
    assert len(turn_context) % 2 == 1
    assert len(context) <= 25  # bounded turns plus the existing system prompt


def test_completed_retry_returns_original_without_second_model_call(tmp_path):
    model = RecordingModel("原始答案")
    with TestClient(create_app(str(tmp_path / "retry.sqlite3"), owner_id="owner-a",
                               clock=FixedClock(), assistant_task_model=model)) as client:
        conversation_id = create(client)
        first = send(client, conversation_id, "retry-me", "原文", 0)
        again = send(client, conversation_id, "retry-me", "原文", 0)
        changed = send(client, conversation_id, "retry-me", "不同内容", 0)
    assert first.status_code == again.status_code == 200
    assert again.json() == first.json()
    assert changed.status_code == 409
    assert len(model.calls) == 1


def test_idempotency_header_must_match_client_message_identity(tmp_path):
    with TestClient(create_app(str(tmp_path / "header-mismatch.sqlite3"), owner_id="owner-a",
                               clock=FixedClock(), assistant_task_model=RecordingModel())) as client:
        conversation_id = create(client)
        response = client.post(f"/api/v1/conversations/{conversation_id}/messages",
            headers={"Idempotency-Key": "different-id"}, json={
                "client_message_id": "body-id", "content": "hello",
                "timezone": "Asia/Shanghai", "expected_sequence": 0,
            })
    assert response.status_code == 422


def seed_committed_draft_conversation(db):
    repository = SqliteRepository(db)
    conversation = repository.create_conversation("owner-a", "create-seeded", "seed-hash")
    repository.reserve_conversation_turn("owner-a", conversation.conversation_id,
        "draft-source", "明天下午两点开会一个小时", "Asia/Shanghai", 0, "source-hash")
    now = datetime(2026, 9, 27, 9, 40, tzinfo=UTC)
    candidate = Candidate("candidate-1", "项目会", "会议室", datetime(2026, 9, 28, 6, tzinfo=UTC),
        datetime(2026, 9, 28, 7, tzinfo=UTC), "Asia/Shanghai")
    draft = make_draft("draft_committed", "owner-a", 1, "draft-source", now,
        datetime(2026, 9, 28, 9, 40, tzinfo=UTC), (candidate,), committed=True)
    repository.save_draft(draft)
    repository.complete_conversation_turn("owner-a", conversation.conversation_id,
        "draft-source", "请核对日程草稿。", [], [draft.draft_id])
    return repository, conversation, draft


def test_committed_latest_draft_confirmation_is_acknowledged_without_model(tmp_path, monkeypatch):
    db = tmp_path / "typed-draft-confirm.sqlite3"
    repository = SqliteRepository(db)
    conversation = repository.create_conversation("owner-a", "create-seeded", "seed-hash")
    repository.reserve_conversation_turn("owner-a", conversation.conversation_id,
        "draft-source", "明天下午两点开会一个小时", "Asia/Shanghai", 0, "source-hash")
    now = datetime(2026, 9, 27, 9, 40, tzinfo=UTC)
    candidate = Candidate("candidate-1", "项目会", "会议室", datetime(2026, 9, 28, 6, tzinfo=UTC),
        datetime(2026, 9, 28, 7, tzinfo=UTC), "Asia/Shanghai")
    draft = make_draft("draft_committed", "owner-a", 1, "draft-source", now,
        datetime(2026, 9, 28, 9, 40, tzinfo=UTC), (candidate,), committed=True)
    repository.save_draft(draft)
    repository.complete_conversation_turn("owner-a", conversation.conversation_id,
        "draft-source", "请核对日程草稿。", [], [draft.draft_id])
    model = RecordingModel("模型不应看到这条确认")
    monkeypatch.delenv("MIMO_API_KEY", raising=False)

    with TestClient(create_app(str(db), owner_id="owner-a", clock=FixedClock(),
                               assistant_task_model=model)) as client:
        response = send(client, conversation.conversation_id, "typed-confirm", "确认", 2)
        page = client.get(f"/api/v1/conversations/{conversation.conversation_id}/messages")

    assert response.status_code == 200
    body = response.json()
    assert body["answer"]["content"] == "已保存这份日程。"
    assert body["tool_results"] == [{
        "action": "confirm_rigid_event_draft", "status": "succeeded",
        "data": {"draft_id": draft.draft_id}, "message": None,
    }]
    assert body["revision"] == 4
    assert page.json()["pending_client_message_id"] is None
    assert len(model.calls) == 0
    assert repository.get_draft("owner-a", draft.draft_id).status == "committed"


def test_committed_confirmation_succeeds_without_assistant_configuration(tmp_path, monkeypatch):
    db = tmp_path / "typed-confirm-no-assistant.sqlite3"
    _, conversation, _ = seed_committed_draft_conversation(db)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    with TestClient(create_app(str(db), owner_id="owner-a", clock=FixedClock(),
                               assistant_task_model=None)) as client:
        response = send(client, conversation.conversation_id,
                        "typed-confirm-no-assistant", "确认", 2)
    assert response.status_code == 200
    assert response.json()["answer"]["content"] == "已保存这份日程。"


def test_broad_affirmative_is_not_a_typed_draft_confirmation(tmp_path, monkeypatch):
    db = tmp_path / "broad-affirmative.sqlite3"
    repository, conversation, draft = seed_committed_draft_conversation(db)
    model = RecordingModel("这是普通对话回复")
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    with TestClient(create_app(str(db), owner_id="owner-a", clock=FixedClock(),
                               assistant_task_model=model)) as client:
        response = send(client, conversation.conversation_id, "broad-yes", "好的", 2)
    assert response.status_code == 200
    assert response.json()["answer"]["content"] == "这是普通对话回复"
    assert len(model.calls) == 1
    assert repository.get_draft("owner-a", draft.draft_id).status == "committed"


def test_historical_draft_is_not_acknowledged_after_unrelated_assistant_reply(tmp_path, monkeypatch):
    db = tmp_path / "unrelated-reply.sqlite3"
    repository, conversation, draft = seed_committed_draft_conversation(db)
    repository.reserve_conversation_turn("owner-a", conversation.conversation_id,
        "unrelated-question", "讲个笑话", "Asia/Shanghai", 2, "unrelated-hash")
    repository.complete_conversation_turn("owner-a", conversation.conversation_id,
        "unrelated-question", "有一天，程序员走进了咖啡店。", [], [])
    model = RecordingModel("请问你想确认什么？")
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    with TestClient(create_app(str(db), owner_id="owner-a", clock=FixedClock(),
                               assistant_task_model=model)) as client:
        response = send(client, conversation.conversation_id, "stale-draft-confirm", "确认", 4)
    assert response.status_code == 200
    assert response.json()["answer"]["content"] == "请问你想确认什么？"
    assert len(model.calls) == 1
    assert repository.get_draft("owner-a", draft.draft_id).status == "committed"


def test_pending_same_id_resumes_but_new_message_and_stale_sequence_conflict(tmp_path):
    class FailOnceModel(RecordingModel):
        def complete(self, messages, tools):
            self.calls.append((messages, tools))
            if len(self.calls) == 1:
                raise RuntimeError("temporary model failure")
            return ModelTurn("恢复完成")

    model = FailOnceModel()
    with TestClient(create_app(str(tmp_path / "pending.sqlite3"), owner_id="owner-a",
                               clock=FixedClock(), assistant_task_model=model)) as client:
        conversation_id = create(client)
        failed = send(client, conversation_id, "pending-id", "十分钟后有个会议", 0)
        pending_page = client.get(f"/api/v1/conversations/{conversation_id}/messages")
        competing = send(client, conversation_id, "other-id", "其他消息", 1)
        resumed = send(client, conversation_id, "pending-id", "十分钟后有个会议", 0)
        completed_page = client.get(f"/api/v1/conversations/{conversation_id}/messages")
        stale = send(client, conversation_id, "next", "新消息", 0)
    assert failed.status_code == 500 or failed.status_code == 502
    assert competing.status_code == 409
    assert pending_page.json()["pending_client_message_id"] == "pending-id"
    assert resumed.status_code == 200
    assert resumed.json()["answer"]["content"] == "恢复完成"
    assert completed_page.json()["pending_client_message_id"] is None
    assert stale.status_code == 409
    assert len(model.calls) == 2


def test_pending_same_id_with_changed_content_conflicts(tmp_path):
    class AlwaysFailModel(RecordingModel):
        def complete(self, messages, tools):
            self.calls.append((messages, tools))
            raise RuntimeError("temporary failure")

    with TestClient(create_app(str(tmp_path / "pending-change.sqlite3"), owner_id="owner-a",
                               clock=FixedClock(), assistant_task_model=AlwaysFailModel())) as client:
        conversation_id = create(client)
        original = send(client, conversation_id, "same-id", "原始内容", 0)
        changed = send(client, conversation_id, "same-id", "改过的内容", 0)
    assert original.status_code == 502
    assert changed.status_code == 409


def test_read_is_passive_and_pages_by_message_sequence(tmp_path):
    model = RecordingModel()
    with TestClient(create_app(str(tmp_path / "pages.sqlite3"), owner_id="owner-a",
                               clock=FixedClock(), assistant_task_model=model)) as client:
        conversation_id = create(client)
        sequence = 0
        for index in range(3):
            response = send(client, conversation_id, f"page-{index}", f"内容 {index}", sequence)
            sequence = response.json()["revision"]
        first = client.get(f"/api/v1/conversations/{conversation_id}/messages?cursor=p0")
        second = client.get(f"/api/v1/conversations/{conversation_id}/messages?cursor=p2")
    assert first.status_code == second.status_code == 200
    assert [item["sequence"] for item in first.json()["items"]] == [1, 2, 3, 4, 5, 6]
    assert [item["sequence"] for item in second.json()["items"]] == [3, 4, 5, 6]
    assert len(model.calls) == 3
