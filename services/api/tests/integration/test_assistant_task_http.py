import json

from fastapi.testclient import TestClient

from kairos.adapters.persistence.sqlite import SqliteRepository
from kairos.application.assistant_tasks import ModelTurn, ToolCall
from kairos.main import create_app
from datetime import UTC, datetime, timedelta


class FixedModel:
    def __init__(self, *turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        return self.turns.pop(0) if self.turns else ModelTurn("根据已保存记录回答。")


def call(name, arguments):
    return ToolCall(call_id="tool-1", name=name,
                    arguments_json=json.dumps(arguments, ensure_ascii=False))


class FixedClock:
    def now(self):
        return datetime(2026, 9, 26, 12, tzinfo=UTC)


class TickingClock:
    def __init__(self):
        self.calls = 0

    def now(self):
        result = datetime(2026, 9, 26, 12, tzinfo=UTC) + timedelta(seconds=self.calls * 3)
        self.calls += 1
        return result


def test_model_classifies_relative_meeting_as_rigid_and_returns_uncommitted_draft(tmp_path):
    db = tmp_path / "rigid-chat.sqlite3"
    model = FixedModel(ModelTurn(None, (call("create_rigid_event_draft", {}),)))
    with TestClient(create_app(str(db), owner_id="local", clock=TickingClock(),
                               assistant_task_model=model)) as client:
        response = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "meeting-relative-1", "timezone": "Asia/Shanghai",
            "messages": [{"role": "user", "content": "我10分钟后有个会，持续10分钟"}],
        })

    assert response.status_code == 200
    body = response.json()
    assert body["draft"]["status"] == "ready"
    candidate = body["draft"]["candidates"][0]
    assert candidate["title"] == "会议"
    reference_now = datetime.fromisoformat(body["draft"]["reference_now"])
    start_at = datetime.fromisoformat(candidate["start_at"])
    end_at = datetime.fromisoformat(candidate["end_at"])
    assert start_at - reference_now.astimezone(start_at.tzinfo) == timedelta(minutes=10)
    assert end_at - start_at == timedelta(minutes=10)
    assert body["action_results"][0]["action"] == "create_rigid_event_draft"
    assert SqliteRepository(db).list_events("local") == []


def test_user_confirmation_of_relative_time_asks_for_absolute_start_without_draft(tmp_path):
    db = tmp_path / "confirmed-relative-rigid.sqlite3"
    model = FixedModel(ModelTurn(None, (call("create_rigid_event_draft", {}),)))
    with TestClient(create_app(str(db), owner_id="local", clock=FixedClock(),
                               assistant_task_model=model)) as client:
        response = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "confirmed-relative-meeting", "timezone": "Asia/Shanghai",
            "messages": [
                {"role": "user", "content": "10分钟后开会，持续10分钟"},
                {"role": "assistant", "content": "按服务器当前时间推算为20:10至20:20，确认这个开始时间是否正确？"},
                {"role": "user", "content": "确认"},
            ],
        })
    assert response.status_code == 200
    body = response.json()
    assert body["draft"] is None
    assert "具体几点开始" in body["answer"]
    assert SqliteRepository(db).list_events("local") == []


def test_uncertain_schedule_message_can_ask_without_creating_a_draft(tmp_path):
    model = FixedModel(ModelTurn("你是希望安排一个固定时刻，还是只记录为待完成事项？"))
    with TestClient(create_app(str(tmp_path / "clarify.sqlite3"), owner_id="local",
                               assistant_task_model=model)) as client:
        response = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "uncertain-schedule-1", "timezone": "Asia/Shanghai",
            "messages": [{"role": "user", "content": "之后找时间处理一下课程"}],
        })
    assert response.status_code == 200
    assert response.json()["draft"] is None
    assert "固定时刻" in response.json()["answer"]


def test_model_cannot_route_a_deadline_task_to_the_rigid_draft_tool(tmp_path):
    model = FixedModel(ModelTurn(None, (call("create_rigid_event_draft", {}),)),
                       ModelTurn("这是一项带截止日期的柔性事项。"))
    db = tmp_path / "flexible-only.sqlite3"
    with TestClient(create_app(str(db), owner_id="local", assistant_task_model=model)) as client:
        response = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "deadline-task-1", "timezone": "Asia/Shanghai",
            "messages": [{"role": "user", "content": "周日前完成操作系统实验"}],
        })
    assert response.status_code == 200
    assert response.json()["draft"] is None
    assert response.json()["action_results"] == []
    assert SqliteRepository(db).list_events("local") == []


def test_empty_model_turn_returns_safe_clarification_instead_of_empty_http_answer(tmp_path):
    model = FixedModel(ModelTurn(""))
    with TestClient(create_app(str(tmp_path / "empty-turn.sqlite3"), assistant_task_model=model)) as client:
        response = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "empty-turn-1", "timezone": "Asia/Shanghai",
            "messages": [{"role": "user", "content": "你好"}],
        })
    assert response.status_code == 200
    assert response.json()["answer"]


def test_assistant_task_write_and_query_return_structured_persisted_records(tmp_path):
    db = tmp_path / "tasks.sqlite3"
    add_turn = ModelTurn("已记下操作系统实验。", (call("create_flexible_task", {
        "title": "操作系统实验", "deadline": "2026-09-27",
    }),))
    with TestClient(create_app(str(db), owner_id="local", assistant_task_model=FixedModel(add_turn))) as client:
        added = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "add-1", "timezone": "Asia/Shanghai",
            "messages": [{"role": "user", "content": "周日前帮我添加操作系统实验"}],
        })
    assert added.status_code == 200
    created_result = added.json()["action_results"][0]
    assert created_result["status"] == "succeeded"
    assert created_result["data"]["title"] == "操作系统实验"
    assert created_result["data"]["deadline"] == "2026-09-27"

    query_turn = ModelTurn("你有一项操作系统实验，周日截止。", (call("query_flexible_tasks", {}),))
    with TestClient(create_app(str(db), owner_id="local", assistant_task_model=FixedModel(query_turn))) as client:
        queried = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "query-1", "timezone": "Asia/Shanghai",
            "messages": [{"role": "user", "content": "列出我的规划"}],
        })
    assert queried.status_code == 200
    task_result = queried.json()["action_results"][0]
    assert task_result["status"] == "succeeded"
    assert len(task_result["data"]) == 1
    assert task_result["data"][0]["task_id"] == created_result["data"]["task_id"]
    assert SqliteRepository(db).list_flexible_tasks("local")[0].title == "操作系统实验"


def test_ambiguous_plan_query_clarifies_without_showing_internal_tool_rejection(tmp_path):
    model = FixedModel(ModelTurn(None, (call("query_flexible_tasks", {}),)),
                       ModelTurn("你想查看没有固定时间的柔性事项，还是某个固定日程？"))
    with TestClient(create_app(str(tmp_path / "ambiguous-query.sqlite3"), owner_id="local",
                               assistant_task_model=model)) as client:
        response = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "ambiguous-plan-query-1", "timezone": "Asia/Shanghai",
            "messages": [{"role": "user", "content": "列出我的安排"}],
        })
    assert response.status_code == 200
    assert response.json()["action_results"] == []
    assert "柔性任务" in response.json()["answer"]


def test_assistant_query_tool_cannot_write_even_if_model_returns_create_call(tmp_path):
    model = FixedModel(ModelTurn("已添加。", (call("create_flexible_task", {
        "title": "不该创建", "deadline": None,
    }),)))
    with TestClient(create_app(str(tmp_path / "tasks.sqlite3"), owner_id="local",
                              assistant_task_model=model)) as client:
        response = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "query-only", "timezone": "Asia/Shanghai",
            "messages": [{"role": "user", "content": "我还有哪些事情没完成？"}],
        })
    assert response.status_code == 200
    assert response.json()["action_results"][0]["action"] == "query_flexible_tasks"
    assert response.json()["action_results"][0]["status"] == "succeeded"
    assert SqliteRepository(tmp_path / "tasks.sqlite3").list_flexible_tasks("local") == []


def test_assistant_reads_saved_rigid_schedule_only_after_explicit_user_query(tmp_path):
    db = tmp_path / "rigid-assistant-query.sqlite3"
    model = FixedModel(ModelTurn("模型文本不能覆盖保存的事实。",
                                 (call("query_rigid_events", {}),)))
    with TestClient(create_app(str(db), owner_id="local", clock=FixedClock(),
                               assistant_task_model=model)) as client:
        draft = client.post("/api/v1/drafts", headers={"Idempotency-Key": "schedule-draft"}, json={
            "conversation_id": "conversation", "source_message_id": "source",
            "intent": "create_rigid_event", "text": "明天下午两点上软件工程课，一个小时，地点 A 楼",
            "timezone": "Asia/Shanghai",
        }).json()
        candidate = draft["candidates"][0]
        saved = client.post(f"/api/v1/drafts/{draft['draft_id']}/commit",
            headers={"Idempotency-Key": "schedule-commit"}, json={
                "revision": draft["revision"], "confirmed_candidate_ids": [candidate["candidate_id"]],
                "confirmation_digest": draft["confirmation_digest"], "conflict_acceptance": None,
            })
        assert saved.status_code == 200
        response = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "rigid-query", "timezone": "Asia/Shanghai",
            "messages": [{"role": "user", "content": "我这周有哪些刚性安排？"}],
        })
    assert response.status_code == 200
    body = response.json()
    assert "软件工程课" in body["answer"]
    assert "09月27日 14:00–15:00" in body["answer"]
    assert body["action_results"][0]["action"] == "query_rigid_events"


def test_assistant_rigid_change_returns_reviewable_proposal_until_commit_endpoint(tmp_path):
    db = tmp_path / "assistant-change-proposal.sqlite3"
    repository = SqliteRepository(db)
    with TestClient(create_app(str(db), owner_id="local", clock=FixedClock())) as client:
        draft = client.post("/api/v1/drafts", headers={"Idempotency-Key": "seed-event-draft"}, json={
            "conversation_id": "conversation", "source_message_id": "seed-event",
            "intent": "create_rigid_event", "text": "明天下午两点上软件工程课，一个小时，地点 A 楼",
            "timezone": "Asia/Shanghai",
        }).json()
        saved = client.post(f"/api/v1/drafts/{draft['draft_id']}/commit",
            headers={"Idempotency-Key": "seed-event-commit"}, json={
                "revision": draft["revision"],
                "confirmed_candidate_ids": [draft["candidates"][0]["candidate_id"]],
                "confirmation_digest": draft["confirmation_digest"],
                "conflict_acceptance": None,
            })
        assert saved.status_code == 200
        before = repository.list_occurrences("local", datetime(2026, 9, 27, tzinfo=UTC),
                                             datetime(2026, 9, 28, tzinfo=UTC))[0]

        proposal_model = FixedModel(
            ModelTurn(None, (call("query_rigid_events", {}),)),
            ModelTurn(None, (call("propose_rigid_event_change", {
                "target_id": before.occurrence_id, "scope": "occurrence",
                "expected_version": before.version, "action": "update",
                "changes": {"title": "软件工程讨论课"},
            }),)),
        )
    with TestClient(create_app(str(db), owner_id="local", clock=FixedClock(),
                               assistant_task_model=proposal_model)) as client:
        response = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "change-course-title", "timezone": "Asia/Shanghai",
            "messages": [{"role": "user", "content": "把软件工程课改成软件工程讨论课"}],
        })
        assert response.status_code == 200
        action = response.json()["action_results"][-1]
        assert action["action"] == "propose_rigid_event_change"
        assert action["status"] == "succeeded"
        proposal = action["data"]
        assert proposal["target_title"] == "软件工程课"
        assert proposal["changes"] == {"title": "软件工程讨论课"}
        assert proposal["scope"] == "occurrence"
        assert proposal["status"] == "pending"
        assert repository.list_occurrences("local", datetime(2026, 9, 27, tzinfo=UTC),
                                           datetime(2026, 9, 28, tzinfo=UTC))[0].title == "软件工程课"

        committed = client.post(f"/api/v1/event-change-proposals/{proposal['proposal_id']}/commit",
            headers={"Idempotency-Key": "explicit-user-confirmation"}, json={
                "revision": proposal["revision"],
                "confirmation_digest": proposal["confirmation_digest"],
                "source_action_id": "explicit-user-confirmation",
            })
        assert committed.status_code == 200
        assert committed.json()["status"] == "committed"
        assert repository.list_occurrences("local", datetime(2026, 9, 27, tzinfo=UTC),
                                           datetime(2026, 9, 28, tzinfo=UTC))[0].title == "软件工程讨论课"


def test_model_selected_task_query_does_not_leak_another_owners_records(tmp_path):
    db = tmp_path / "owner-query.sqlite3"
    add = ModelTurn(None, (call("create_flexible_task", {
        "title": "操作系统实验", "deadline": None}),))
    with TestClient(create_app(str(db), owner_id="owner-a",
                               assistant_task_model=FixedModel(add))) as client:
        created = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "owner-a-add", "timezone": "Asia/Shanghai",
            "messages": [{"role": "user", "content": "帮我添加操作系统实验任务"}],
        })
    assert created.status_code == 200
    assert created.json()["action_results"][0]["status"] == "succeeded"

    query = ModelTurn("你有操作系统实验。", (call("query_flexible_tasks", {}),))
    with TestClient(create_app(str(db), owner_id="owner-b",
                               assistant_task_model=FixedModel(query))) as client:
        response = client.post("/api/v1/assistant/chat", json={
            "client_message_id": "owner-b-query", "timezone": "Asia/Shanghai",
            "messages": [{"role": "user", "content": "我有哪些待办？"}],
        })

    assert response.status_code == 200
    assert response.json()["action_results"][0]["data"] == []
    assert "操作系统实验" not in response.json()["answer"]
