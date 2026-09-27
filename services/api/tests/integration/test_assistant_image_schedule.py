import base64
from datetime import UTC, date, datetime, time
from io import BytesIO
import json

from fastapi.testclient import TestClient
from PIL import Image

from kairos.adapters.persistence.sqlite import SqliteRepository
from kairos.application.assistant_tasks import ModelTurn, ToolCall
from kairos.application.draft_commit import DraftCommitService
from kairos.application.drafts import DraftService
from kairos.domain.drafts import Candidate
from kairos.domain.events import RecurrenceRule
from kairos.main import create_app
from zoneinfo import ZoneInfo


class FixedModel:
    def __init__(self, arguments):
        self.arguments = arguments
        self.messages = []
        self.tools = []

    def complete(self, messages, tools):
        self.messages = messages
        self.tools = tools
        return ModelTurn(None, (ToolCall(call_id="image-tool", name="create_rigid_event_draft",
            arguments_json=json.dumps(self.arguments, ensure_ascii=False)),))


class EmptyTurnModel:
    def complete(self, messages, tools):
        return ModelTurn(None, ())


class FixedClock:
    def now(self):
        return datetime(2026, 9, 27, 12, tzinfo=UTC)


def encoded_png():
    output = BytesIO()
    Image.new("RGB", (24, 12), "white").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode()


def post_image(client, key="image", prompt="请识别这张课表并生成待确认日程。", timezone="Asia/Shanghai",
               messages=None):
    return client.post("/api/v1/assistant/chat", json={
        "client_message_id": key, "timezone": timezone,
        "messages": messages or [{"role": "user", "content": prompt}],
        "image": {"mime_type": "image/png", "data_base64": encoded_png()},
    })


def test_timetable_image_creates_uncommitted_multi_candidate_draft(tmp_path):
    model = FixedModel({"events": [
        {"title": "数学", "frequency": "weekly", "weekdays": [1],
         "starts_on": "2026-09-01", "ends_on": "2026-12-31",
         "start_time": "09:00", "end_time": "10:00"},
        {"title": "物理", "frequency": "weekly", "weekdays": [3, 5],
         "starts_on": "2026-09-01", "ends_on": "2026-12-31",
         "start_time": "10:00", "end_time": "11:00"},
    ]})
    db = tmp_path / "image-schedule.sqlite3"
    with TestClient(create_app(str(db), owner_id="local", clock=FixedClock(),
                               assistant_task_model=model)) as client:
        response = post_image(client)

    assert response.status_code == 200
    body = response.json()
    assert body["draft"]["status"] == "ready"
    assert [item["title"] for item in body["draft"]["candidates"]] == ["数学", "物理"]
    assert body.get("retain_image", False) is False
    assert body["action_results"][0]["data"]["existing_schedule_matches"] == []
    assert SqliteRepository(db).list_events("local") == []
    assert [item["function"]["name"] for item in model.tools] == ["create_rigid_event_draft"]
    user_content = next(item["content"] for item in model.messages if item["role"] == "user")
    assert isinstance(user_content, list)
    assert any(part.get("type") == "image_url" for part in user_content)


def test_missing_timetable_term_dates_asks_and_retains_attachment(tmp_path):
    model = FixedModel({"events": [{"title": "数学", "frequency": "weekly", "weekdays": [1],
                                      "start_time": "09:00", "end_time": "10:00"}]})
    db = tmp_path / "image-clarification.sqlite3"
    with TestClient(create_app(str(db), owner_id="local", clock=FixedClock(),
                               assistant_task_model=model)) as client:
        response = post_image(client, "image-missing-range")

    assert response.status_code == 200
    body = response.json()
    assert body["draft"] is None
    assert body["retain_image"] is True
    assert "开始日期和结束日期" in body["answer"]
    assert SqliteRepository(db).list_events("local") == []


def test_image_turn_without_tool_call_has_specific_recoverable_feedback(tmp_path):
    app = create_app(str(tmp_path / "image-empty-turn.sqlite3"), owner_id="local",
                     clock=FixedClock(), assistant_task_model=EmptyTurnModel())
    with TestClient(app) as client:
        response = post_image(client, "image-empty-turn")

    body = response.json()
    assert response.status_code == 200
    assert body["retain_image"] is True
    assert "课表图片" in body["answer"]
    assert "固定安排还是待完成事项" not in body["answer"]
    assert SqliteRepository(tmp_path / "image-empty-turn.sqlite3").list_events("local") == []


def test_image_import_followup_keeps_explicit_user_authorization(tmp_path):
    model = FixedModel({"events": [{"title": "软件工程", "frequency": "weekly", "weekdays": [1],
        "starts_on": "2026-09-28", "ends_on": "2026-12-28",
        "start_time": "14:00", "end_time": "15:40"}]})
    app = create_app(str(tmp_path / "image-followup.sqlite3"), owner_id="local",
                     clock=FixedClock(), assistant_task_model=model)
    history = [
        {"role": "user", "content": "请识别这张课表并生成待确认日程。"},
        {"role": "assistant", "content": "请说明这是固定安排还是待完成事项。"},
        {"role": "user", "content": "固定事件安排"},
    ]
    with TestClient(app) as client:
        response = post_image(client, "image-followup", prompt="固定事件安排", messages=history)

    assert response.status_code == 200
    assert response.json()["draft"]["status"] == "ready"
    assert response.json()["draft"]["candidates"][0]["title"] == "软件工程"
    assert SqliteRepository(tmp_path / "image-followup.sqlite3").list_events("local") == []


def test_old_schedule_request_does_not_authorize_a_new_unrelated_image(tmp_path):
    model = FixedModel({"events": [{"title": "不应保存", "frequency": "weekly", "weekdays": [1],
        "starts_on": "2026-09-28", "ends_on": "2026-12-28",
        "start_time": "14:00", "end_time": "15:40"}]})
    db = tmp_path / "image-new-topic.sqlite3"
    app = create_app(str(db), owner_id="local", clock=FixedClock(), assistant_task_model=model)
    history = [
        {"role": "user", "content": "请识别这张课表并生成待确认日程。"},
        {"role": "assistant", "content": "上一次课表导入已处理完成。"},
        {"role": "user", "content": "另外看看这张图里是什么。"},
    ]
    with TestClient(app) as client:
        response = post_image(client, "image-new-topic", prompt="另外看看这张图里是什么。", messages=history)

    assert response.status_code == 200
    assert response.json()["draft"] is None
    assert len(model.tools) > 1
    assert SqliteRepository(db).list_events("local") == []


def test_image_import_reads_owner_scoped_schedule_in_image_date_range(tmp_path):
    db = tmp_path / "image-existing-schedule.sqlite3"
    model = FixedModel({"events": [{"title": "数学", "frequency": "weekly", "weekdays": [1],
        "starts_on": "2026-09-01", "ends_on": "2026-12-31",
        "start_time": "09:00", "end_time": "10:00"}]})
    app = create_app(str(db), owner_id="local", clock=FixedClock(), assistant_task_model=model)
    with TestClient(app) as client:
        repository = SqliteRepository(db)
        zone = ZoneInfo("Asia/Shanghai")
        recurrence = RecurrenceRule("weekly", date(2026, 9, 1), date(2026, 12, 31), (1,),
                                    time(9), time(10), 0)
        existing = Candidate("existing", "原有数学课", None,
            datetime(2026, 9, 7, 9, tzinfo=zone), datetime(2026, 9, 7, 10, tzinfo=zone),
            "Asia/Shanghai", recurrence)
        draft = DraftService(repository, FixedClock()).create("local", [existing], "seed-existing")
        DraftCommitService(repository, FixedClock()).commit("local", draft.draft_id, draft.revision,
            [existing.candidate_id], draft.confirmation_digest, "seed-commit")
        response = post_image(client, "image-query-existing")

    assert response.status_code == 200
    matches = response.json()["action_results"][0]["data"]["existing_schedule_matches"]
    assert len(matches) == 1
    assert matches[0]["overlap_count"] == 17
    assert all(match["existing_title"] == "原有数学课" for match in matches)
    assert all(match["kind"] == "overlap" for match in matches)
    assert len(SqliteRepository(db).list_events("local")) == 1


def test_invalid_image_is_rejected_before_model_invocation(tmp_path):
    model = FixedModel({"events": []})
    with TestClient(create_app(str(tmp_path / "invalid-image.sqlite3"), owner_id="local",
                               assistant_task_model=model)) as client:
        response = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "bad-image", "timezone": "UTC",
            "messages": [{"role": "user", "content": "课表"}],
            "image": {"mime_type": "image/png", "data_base64": base64.b64encode(b"not png").decode()},
        })
    assert response.status_code == 422
    assert model.messages == []


def test_daylight_saving_ambiguity_clarifies_without_persisting_a_draft(tmp_path):
    model = FixedModel({"events": [{"title": "夜间课程", "frequency": "weekly", "weekdays": [7],
        "starts_on": "2026-03-01", "ends_on": "2026-03-30",
        "start_time": "02:30", "end_time": "03:30"}]})
    db = tmp_path / "image-dst.sqlite3"
    with TestClient(create_app(str(db), owner_id="local", clock=FixedClock(),
                               assistant_task_model=model)) as client:
        response = post_image(client, "image-dst", timezone="America/New_York")
    assert response.status_code == 200
    assert response.json().get("draft") is None
    assert response.json()["retain_image"] is True
    assert "夏令时" in response.json()["answer"]
    assert SqliteRepository(db).list_events("local") == []
