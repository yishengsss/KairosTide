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
        if not tools and self.arguments.get("events"):
            return ModelTurn(json.dumps(self.arguments, ensure_ascii=False), ())
        return ModelTurn(None, (ToolCall(call_id="image-tool", name="create_rigid_event_draft",
            arguments_json=json.dumps(self.arguments, ensure_ascii=False)),))


class EmptyTurnModel:
    def complete(self, messages, tools):
        return ModelTurn(None, ())


class TextTurnModel:
    def __init__(self, answer):
        self.answer = answer
        self.tools = None

    def complete(self, messages, tools):
        self.tools = tools
        return ModelTurn(self.answer, ())


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
    assert model.tools == []
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
    assert "图片" in body["answer"]
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


def test_affirmative_reply_accepts_assistant_offer_to_make_image_schedule_draft(tmp_path):
    model = FixedModel({"events": [{"title": "软件工程", "frequency": "once",
        "date": "2026-09-30", "location": "8#602D",
        "start_time": "08:00", "end_time": "09:35"}]})
    db = tmp_path / "image-offer-accepted.sqlite3"
    app = create_app(str(db), owner_id="local", clock=FixedClock(), assistant_task_model=model)
    history = [
        {"role": "user", "content": "请识别图片中的信息并告诉我能看出什么。"},
        {"role": "assistant", "content": (
            "这是一张课程表。如果你需要，我可以帮你把这几门课整理成待确认的日程草稿"
            "（保存前需要你确认）。")},
        {"role": "user", "content": "好的"},
    ]
    with TestClient(app) as client:
        response = post_image(client, "image-offer-accepted", prompt="好的", messages=history)

    body = response.json()
    assert response.status_code == 200
    assert body["draft"]["status"] == "ready"
    assert body["draft"]["candidates"][0]["title"] == "软件工程"
    assert body.get("retain_image", False) is False
    assert model.tools == []
    assert SqliteRepository(db).list_events("local") == []


def test_affirmative_reply_does_not_accept_unrelated_assistant_offer(tmp_path):
    model = FixedModel({"events": [{"title": "不应导入", "frequency": "once",
        "date": "2026-09-30", "start_time": "08:00", "end_time": "09:35"}]})
    db = tmp_path / "image-unrelated-offer.sqlite3"
    app = create_app(str(db), owner_id="local", clock=FixedClock(), assistant_task_model=model)
    history = [
        {"role": "user", "content": "请识别图片中的信息并告诉我能看出什么。"},
        {"role": "assistant", "content": "如果你需要，我可以再详细描述一下图片内容。"},
        {"role": "user", "content": "好的"},
    ]
    with TestClient(app) as client:
        response = post_image(client, "image-unrelated-offer", prompt="好的", messages=history)

    body = response.json()
    assert response.status_code == 200
    assert body["draft"] is None
    assert body["retain_image"] is True
    assert model.tools == []
    assert SqliteRepository(db).list_events("local") == []


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
    assert model.tools == []
    assert SqliteRepository(db).list_events("local") == []


def test_generic_image_analysis_is_adaptive_read_only_and_returns_model_description(tmp_path):
    model = TextTurnModel("这张图片是一张课程安排表，显示了多个日期、时段和课程信息。")
    db = tmp_path / "image-generic-analysis.sqlite3"
    app = create_app(str(db), owner_id="local", clock=FixedClock(), assistant_task_model=model)
    with TestClient(app) as client:
        response = post_image(client, "image-generic-analysis", prompt="请读取并提取这张图片中的信息")

    assert response.status_code == 200
    assert response.json()["answer"] == model.answer
    assert response.json()["retain_image"] is True
    assert model.tools == []
    assert response.json()["draft"] is None
    assert SqliteRepository(db).list_events("local") == []


def test_explicit_image_import_denial_does_not_create_a_schedule_draft(tmp_path):
    model = TextTurnModel("好的，我只描述图片，不导入日程。")
    db = tmp_path / "image-denied-import.sqlite3"
    app = create_app(str(db), owner_id="local", clock=FixedClock(), assistant_task_model=model)
    with TestClient(app) as client:
        response = post_image(client, "image-denied-import",
            prompt="请识别这张课表，但不要导入日程。")
    assert response.status_code == 200
    assert response.json()["draft"] is None
    assert model.tools == []
    assert SqliteRepository(db).list_events("local") == []


def test_generic_schedule_extraction_request_can_make_visible_date_drafts(tmp_path):
    model = FixedModel({"events": [
        {"title": "软件测试技术", "frequency": "once", "date": "2026-09-28",
         "location": "9#阶5", "start_time": "08:00", "end_time": "09:35"},
        {"title": "软件工程", "frequency": "once", "date": "2026-09-30",
         "location": "8#602D", "start_time": "08:00", "end_time": "09:35"},
        {"title": "线性代数B", "frequency": "once", "date": "2026-09-29",
         "location": "16#205D", "start_time": "10:05", "end_time": "11:40"},
        {"title": "离散数学", "frequency": "once", "date": "2026-09-30",
         "location": "8#604D", "start_time": "10:05", "end_time": "11:40"},
        {"title": "软件测试技术实验", "frequency": "once", "date": "2026-09-28",
         "location": "8#410D", "start_time": "16:15", "end_time": "17:50"},
        {"title": "算法设计与分析", "frequency": "once", "date": "2026-09-29",
         "location": "8#510D", "start_time": "19:20", "end_time": "21:00"},
    ]})
    db = tmp_path / "image-generic-schedule-import.sqlite3"
    app = create_app(str(db), owner_id="local", clock=FixedClock(), assistant_task_model=model)
    prompt = "请从图片提取日程安排并生成待确认草稿，只导入图片可见日期，不要根据周次推断整学期重复。"
    with TestClient(app) as client:
        response = post_image(client, "image-generic-schedule-import", prompt=prompt)

    body = response.json()
    assert response.status_code == 200
    assert body["draft"]["status"] == "ready"
    candidates = body["draft"]["candidates"]
    assert len(candidates) == 6
    assert {item["title"] for item in candidates} == {
        "软件测试技术", "软件工程", "线性代数B", "离散数学", "软件测试技术实验", "算法设计与分析"
    }
    assert {item["start_at"][:10] for item in candidates} == {
        "2026-09-28", "2026-09-29", "2026-09-30"
    }
    assert all(item.get("recurrence") is None for item in candidates)
    assert model.tools == []
    assert SqliteRepository(db).list_events("local") == []


def test_schedule_image_extraction_preserves_user_selected_scope(tmp_path):
    model = FixedModel({"events": [{"title": "软件工程", "frequency": "once", "date": "2026-09-30",
        "start_time": "08:00", "end_time": "09:35", "location": "8#602D"}]})
    db = tmp_path / "image-extraction-scope.sqlite3"
    app = create_app(str(db), owner_id="local", clock=FixedClock(), assistant_task_model=model)
    prompt = "从这张图片只提取周三的软件工程课程并生成待确认日程。"
    with TestClient(app) as client:
        response = post_image(client, "image-extraction-scope", prompt=prompt)
    assert response.status_code == 200
    assert len(response.json()["draft"]["candidates"]) == 1
    user_message = next(message for message in model.messages if message.get("role") == "user")
    vision_text = next(part["text"] for part in user_message["content"] if part.get("type") == "text")
    assert "用户指定的提取范围" in vision_text
    assert prompt in vision_text


def test_image_import_rejects_unstructured_tool_text_without_executing_it(tmp_path):
    model = TextTurnModel("<tool_call><function=create_rigid_event_draft>untrusted text</function></tool_call>")
    db = tmp_path / "image-unstructured.sqlite3"
    app = create_app(str(db), owner_id="local", clock=FixedClock(), assistant_task_model=model)
    with TestClient(app) as client:
        response = post_image(client, "image-unstructured",
            prompt="请识别这张图中的课程安排并生成待确认日程")

    assert response.status_code == 200
    assert response.json()["draft"] is None
    assert response.json()["retain_image"] is True
    assert "没有生成日程草稿" in response.json()["answer"]
    assert SqliteRepository(db).list_events("local") == []


def test_image_import_reports_unreadable_items_and_keeps_confirmable_draft(tmp_path):
    event = {"title": "数学", "frequency": "once", "date": "2026-09-28",
             "start_time": "09:00", "end_time": "10:00", "location": None}
    model = TextTurnModel(json.dumps({"events": [event], "uncertainties": ["第二行结束时间模糊"]}, ensure_ascii=False))
    db = tmp_path / "image-partial-extraction.sqlite3"
    app = create_app(str(db), owner_id="local", clock=FixedClock(), assistant_task_model=model)
    with TestClient(app) as client:
        response = post_image(client, "image-partial-extraction",
            prompt="提取图片中的日程并生成待确认草稿")

    body = response.json()
    assert body["draft"]["status"] == "ready"
    assert len(body["draft"]["candidates"]) == 1
    assert "1 项图片信息无法可靠辨认" in body["answer"]
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
