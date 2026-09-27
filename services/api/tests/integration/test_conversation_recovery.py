import base64
import sqlite3
from datetime import UTC, datetime, timedelta
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from kairos.adapters.persistence.sqlite import SqliteRepository
from kairos.application.assistant_tasks import ModelTurn
from kairos.domain.drafts import Candidate, make_draft
from kairos.main import create_app


class FixedClock:
    def now(self):
        return datetime(2026, 9, 27, 12, tzinfo=UTC)


class AnswerModel:
    def complete(self, messages, tools):
        return ModelTurn("我已根据本轮图片回答。")


def encoded_png():
    image = BytesIO()
    Image.new("RGB", (24, 12), "white").save(image, format="PNG")
    return base64.b64encode(image.getvalue()).decode("ascii")


def test_api_reopens_ordered_history_pending_turn_and_uncommitted_draft(tmp_path):
    db_path = tmp_path / "conversation-recovery.sqlite3"
    repository = SqliteRepository(db_path)
    conversation = repository.create_conversation("local", "create-key", "create-hash")
    first = repository.reserve_conversation_turn(
        "local", conversation.conversation_id, "message-1", "十分钟后有会议", "Asia/Shanghai", 0, "hash-1"
    )
    repository.complete_conversation_turn("local", conversation.conversation_id, "message-1",
                                          "需要知道持续时间。", [], [])

    now = FixedClock().now()
    draft = make_draft(
        "draft-uncommitted", "local", 1, first.user_message.message_id,
        now, now + timedelta(hours=1),
        (Candidate("candidate-1", "会议", "会议室", now + timedelta(minutes=10),
                   now + timedelta(minutes=30), "Asia/Shanghai"),),
    )
    repository.save_draft(draft)
    repository.reserve_conversation_turn(
        "local", conversation.conversation_id, "message-2", "持续20分钟", "Asia/Shanghai", 2, "hash-2"
    )
    repository.complete_conversation_turn("local", conversation.conversation_id, "message-2",
                                          "已生成待确认草稿。", [], [draft.draft_id])
    repository.reserve_conversation_turn(
        "local", conversation.conversation_id, "message-3", "确认", "Asia/Shanghai", 4, "hash-3"
    )

    with TestClient(create_app(str(db_path), owner_id="local", clock=FixedClock(),
                               assistant_task_model=AnswerModel())) as client:
        history = client.get(f"/api/v1/conversations/{conversation.conversation_id}/messages")
        restored_draft = client.get(f"/api/v1/drafts/{draft.draft_id}")

    assert history.status_code == 200
    body = history.json()
    assert [(item["sequence"], item["role"], item["content"], item["status"])
            for item in body["items"]] == [
        (1, "user", "十分钟后有会议", "completed"),
        (2, "assistant", "需要知道持续时间。", "completed"),
        (3, "user", "持续20分钟", "completed"),
        (4, "assistant", "已生成待确认草稿。", "completed"),
        (5, "user", "确认", "pending"),
    ]
    assert body["revision"] == 5
    assert body["draft_refs"] == [draft.draft_id]
    assert body["pending_client_message_id"] == "message-3"
    assert restored_draft.status_code == 200
    assert restored_draft.json()["status"] == "ready"
    assert restored_draft.json()["draft_id"] == draft.draft_id


def test_image_payload_is_request_only_and_absent_from_every_persisted_sqlite_field(tmp_path, caplog):
    db_path = tmp_path / "image-conversation.sqlite3"
    image_bytes = Image.new("RGB", (24, 12), "white")
    png = BytesIO()
    image_bytes.save(png, format="PNG")
    raw_image = png.getvalue()
    encoded = base64.b64encode(raw_image).decode("ascii")
    data_url = f"data:image/png;base64,{encoded}"
    model = AnswerModel()

    with TestClient(create_app(str(db_path), owner_id="local", clock=FixedClock(),
                               assistant_task_model=model)) as client:
        created = client.post("/api/v1/conversations", headers={"Idempotency-Key": "image-conv"})
        assert created.status_code == 200
        conversation_id = created.json()["conversation_id"]
        response = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers={"Idempotency-Key": "image-message"},
            json={"client_message_id": "image-message", "content": "请描述这张图片", "timezone": "UTC",
                  "expected_sequence": 0,
                  "image": {"mime_type": "image/png", "data_base64": encoded}},
        )
        assert response.status_code == 200

    persisted_values = []
    with sqlite3.connect(db_path) as connection:
        table_names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        for table_name in table_names:
            escaped = table_name.replace('"', '""')
            rows = connection.execute(f'SELECT * FROM "{escaped}"').fetchall()
            persisted_values.extend(value for row in rows for value in row if value is not None)

    for value in persisted_values:
        if isinstance(value, bytes):
            assert raw_image not in value
            assert encoded.encode("ascii") not in value
        elif isinstance(value, str):
            assert data_url not in value
            assert encoded not in value
    assert response.json()["answer"]["content"] == "我已根据本轮图片回答。"
    assert data_url not in caplog.text
