import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from kairos.application.assistant_tasks import AssistantService, ModelTurn, ToolCall
from kairos.application.assistant_tasks import _user_intent
from kairos.application.rigid_input import parse_event_candidate
from kairos.application.weather import (WeatherLocation, WeatherLocationAmbiguous,
                                        WeatherLocationChoice, WeatherObservation, WeatherResult)


class FakeModel:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append((messages, tools))
        return self.turns.pop(0) if self.turns else ModelTurn("已根据结果处理。")


class FakeTasks:
    def __init__(self):
        self.created = []
        self.listed = 0
        self.updated = []
        self.deleted = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        return {"task_id": "task-1", "title": kwargs["title"], "deadline": kwargs["deadline"]}

    def list(self, owner_id):
        self.listed += 1
        return [{"task_id": "task-1", "title": "高数作业", "deadline": date(2026, 9, 27)}]

    def update_by_title(self, **kwargs):
        self.updated.append(kwargs)
        return {"task_id": "task-1", "title": "新标题"}

    def delete_by_title(self, **kwargs):
        self.deleted.append(kwargs)
        return {"task_id": "task-1", "title": kwargs["title"]}


def tool(name, args, call_id="call-1"):
    return ToolCall(call_id=call_id, name=name,
                    arguments_json=json.dumps(args, ensure_ascii=False))


def handle(model, tasks, text="你好", message_id="msg-1"):
    return AssistantService(model, tasks).handle(
        "owner-a", message_id, "Asia/Shanghai", [{"role": "user", "content": text}]
    )


def test_relative_meeting_with_duration_before_name_extracts_title_and_location():
    now = datetime(2026, 9, 27, 2, 0, tzinfo=UTC)

    candidate = parse_event_candidate(
        "我10分钟后有一个持续10分钟的会议在9阶1", "Asia/Shanghai", now)

    assert candidate.title == "会议"
    assert candidate.location == "9阶1"
    assert candidate.start_at.isoformat() == "2026-09-27T10:10:00+08:00"
    assert candidate.end_at.isoformat() == "2026-09-27T10:20:00+08:00"


def test_greeting_cannot_trigger_model_requested_task_query():
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("早上好", [tool("query_flexible_tasks", {})]))

    result = handle(model, tasks)

    assert tasks.listed == 0
    assert result.action_results == ()


@pytest.mark.parametrize("text", [
    "帮我看看任务列表界面怎么设计",
    "任务列表页面应该怎么排版？",
    "如何实现待办查询接口？",
    "看看任务卡片怎么画",
    "我的任务列表界面好看吗？",
    "我的任务列表界面怎么样？",
    "我的任务列表界面是什么样？",
    "帮我看看我的任务列表界面布局",
    "我的任务列表界面布局有哪些问题？",
])
def test_task_ui_and_development_questions_cannot_read_saved_records(text):
    tasks = FakeTasks()
    result = handle(FakeModel(ModelTurn("你有高数作业", [tool("query_flexible_tasks", {})])),
                    tasks, text)

    assert tasks.listed == 0
    assert result.action_results == ()
    assert "高数作业" not in result.answer


@pytest.mark.parametrize("text", [
    "帮我看看日程界面怎么设计？",
    "看看日程卡片怎么画",
    "看看我的日程界面布局",
    "看看我的日程卡片展示效果",
])
def test_schedule_ui_question_cannot_read_saved_rigid_records(text):
    class Events:
        def list_occurrences(self, *args):
            raise AssertionError("schedule UI discussion must not read events")

    service = AssistantService(FakeModel(ModelTurn("这是一个界面设计问题", [
        tool("query_rigid_events", {})])), FakeTasks(), rigid_events=Events())
    result = service.handle("owner-a", "schedule-ui", "Asia/Shanghai", [
        {"role": "user", "content": text}])

    assert result.action_results == ()


def test_saved_ui_design_task_title_can_still_be_queried():
    class DesignTasks(FakeTasks):
        def list(self, owner_id):
            self.listed += 1
            return [{"task_id": "design-1", "title": "UI设计", "deadline": None}]

    tasks = DesignTasks()
    result = handle(FakeModel(ModelTurn("没有任务", [tool("query_flexible_tasks", {})])),
                    tasks, "我的UI设计任务有哪些？")

    assert tasks.listed == 1
    assert result.action_results[0].status == "succeeded"
    assert "UI设计" in result.answer


def test_saved_interface_design_task_title_can_still_be_queried():
    class InterfaceTasks(FakeTasks):
        def list(self, owner_id):
            self.listed += 1
            return [{"task_id": "interface-1", "title": "任务列表界面设计", "deadline": None}]

    tasks = InterfaceTasks()
    result = handle(FakeModel(ModelTurn(None, [tool("query_flexible_tasks", {})])),
                    tasks, "我的任务列表界面设计任务有哪些？")

    assert tasks.listed == 1
    assert "任务列表界面设计" in result.answer


def test_saved_interface_layout_task_title_can_still_be_queried():
    class LayoutTasks(FakeTasks):
        def list(self, owner_id):
            self.listed += 1
            return [{"task_id": "layout-1", "title": "任务列表界面布局", "deadline": None}]

    tasks = LayoutTasks()
    result = handle(FakeModel(ModelTurn(None, [tool("query_flexible_tasks", {})])),
                    tasks, "我的任务列表界面布局任务有哪些？")

    assert tasks.listed == 1
    assert "任务列表界面布局" in result.answer


def test_explicit_query_cannot_be_used_to_create_a_task():
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("已添加", [tool("create_flexible_task", {"title": "高数作业"})]))

    result = handle(model, tasks, "我还有哪些事情没完成？")

    assert tasks.created == []
    assert tasks.listed == 1
    assert result.action_results[0].action == "query_flexible_tasks"
    assert result.action_results[0].status == "succeeded"


def test_explicit_query_reads_saved_tasks_and_returns_records_without_writing():
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("已保存一项高数作业。", [tool("query_flexible_tasks", {})]))

    result = handle(model, tasks, "我还有哪些事情没完成？")

    assert tasks.listed == 1
    assert tasks.created == [] and tasks.updated == [] and tasks.deleted == []
    assert result.action_results[0].status == "succeeded"
    assert result.action_results[0].data[0]["deadline"] == "2026-09-27"


def test_query_answer_comes_only_from_saved_records_even_when_model_prose_lies():
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("你有 99 个截止事项。", [tool("query_flexible_tasks", {})]),
                      ModelTurn("其实你还有很多其他事项。"))

    result = handle(model, tasks, "我还有哪些事情没完成？")

    assert tasks.listed == 1
    assert "高数作业" in result.answer
    assert "99" not in result.answer
    assert "其他事项" not in result.answer


def test_model_selected_flexible_query_uses_saved_records_when_intent_hint_is_ambiguous():
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("你有论文和考试。", [tool("query_flexible_tasks", {})]),
                      ModelTurn("你有论文和考试。"))

    result = handle(model, tasks, "请查看我下周的课程和待办")

    assert tasks.listed == 1
    assert "高数作业" in result.answer
    assert "论文" not in result.answer and "考试" not in result.answer


def test_explicit_query_reads_saved_records_without_model_claims():
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("你有三项待办：论文、考试和实验。"))

    result = handle(model, tasks, "最近有什么任务快截止？")

    assert tasks.listed == 1
    assert result.action_results[0].status == "succeeded"
    assert "高数作业" in result.answer
    assert "论文" not in result.answer and "考试" not in result.answer


def test_user_explicitly_queries_rigid_events_reads_own_saved_schedule_only():
    class RigidEvents:
        def __init__(self): self.calls = []
        def list_occurrences(self, owner_id, start, end):
            self.calls.append((owner_id, start, end))
            from types import SimpleNamespace
            return [SimpleNamespace(occurrence_id="o1", title="软件工程课", location="A楼",
                start_at=datetime(2026, 9, 27, 6, tzinfo=UTC), end_at=datetime(2026, 9, 27, 7, 40, tzinfo=UTC),
                disposition="scheduled")]
    events = RigidEvents()
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("没有日程。", [tool("query_rigid_events", {})]))
    service = AssistantService(model, tasks, clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC),
                               rigid_events=events)
    result = service.handle("owner-a", "rigid-query", "Asia/Shanghai", [
        {"role": "user", "content": "我这周有哪些刚性安排？"}])
    assert len(events.calls) == 1 and events.calls[0][0] == "owner-a"
    assert result.action_results[0].action == "query_rigid_events"
    assert "软件工程课" in result.answer and "A楼" in result.answer
    assert "09月27日 14:00–15:40" in result.answer
    assert tasks.listed == 0
    assert len(model.calls) >= 1


@pytest.mark.parametrize("text", [
    "你能查看我的课表吗？",
    "我想查一下保存的固定时间事件",
    "可以告诉我这周的日历安排吗",
    "我能查到自己的会议和课程吗？",
    "我目前有哪些固定时间的事件记录？",
])
def test_natural_language_rigid_schedule_queries_are_authorized_read_actions(text):
    assert _user_intent(text) == "query_rigid_events"


def test_relative_fixed_event_request_uses_clock_and_duration_to_make_draft():
    class Drafts:
        def __init__(self): self.created = []
        def create(self, owner_id, candidates, source_message_id, idempotency_key=None,
                   request_hash=None, *, reference_now=None):
            self.created.append(candidates[0])
            from types import SimpleNamespace
            return SimpleNamespace(draft_id="draft-1")
    drafts = Drafts()
    model = FakeModel(ModelTurn(None, [tool("create_rigid_event_draft", {})]))
    service = AssistantService(model, FakeTasks(), drafts=drafts,
        clock=lambda: datetime(2026, 9, 26, 14, 15, tzinfo=UTC))
    result = service.handle("owner-a", "relative-meeting", "Asia/Shanghai", [
        {"role": "user", "content": "10分钟后开会，持续10分钟"}])
    assert result.draft.draft_id == "draft-1"
    assert drafts.created[0].start_at == datetime(2026, 9, 26, 22, 25, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert drafts.created[0].end_at == datetime(2026, 9, 26, 22, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert drafts.created[0].title == "会议"


def test_unambiguous_relative_event_is_resolved_before_model_can_misclassify_it():
    class Drafts:
        def __init__(self): self.created = []
        def create(self, owner_id, candidates, source_message_id, idempotency_key=None,
                   request_hash=None, *, reference_now=None):
            self.created.append(candidates[0])
            from types import SimpleNamespace
            return SimpleNamespace(draft_id="draft-direct")

    drafts = Drafts()
    model = FakeModel(ModelTurn("日程信息还无法确认，请补充具体日期和开始／结束时间；暂未保存日程。"))
    service = AssistantService(model, FakeTasks(), drafts=drafts,
        clock=lambda: datetime(2026, 9, 27, 2, 0, tzinfo=UTC))

    result = service.handle("owner-a", "relative-meeting-room", "Asia/Shanghai", [
        {"role": "user", "content": "我10分钟后有一个持续10分钟的会议在9阶1"}])

    assert result.draft.draft_id == "draft-direct"
    assert drafts.created[0].title == "会议"
    assert drafts.created[0].location == "9阶1"
    assert drafts.created[0].start_at == datetime(2026, 9, 27, 10, 10,
        tzinfo=ZoneInfo("Asia/Shanghai"))
    assert drafts.created[0].end_at == datetime(2026, 9, 27, 10, 20,
        tzinfo=ZoneInfo("Asia/Shanghai"))
    assert model.calls == []


def test_model_can_choose_rigid_draft_for_natural_event_wording():
    class Drafts:
        def __init__(self): self.created = []
        def create(self, owner_id, candidates, source_message_id, idempotency_key=None,
                   request_hash=None, *, reference_now=None):
            self.created.append(candidates[0])
            from types import SimpleNamespace
            return SimpleNamespace(draft_id="draft-natural")

    drafts = Drafts()
    # “碰头” is not a hard-coded rigid-event keyword. The model may still
    # classify it as a fixed appointment; the server independently parses
    # and validates the actual date, start, and duration before drafting.
    model = FakeModel(ModelTurn(None, [tool("create_rigid_event_draft", {})]))
    service = AssistantService(model, FakeTasks(), drafts=drafts,
        clock=lambda: datetime(2026, 9, 26, 12, 0, tzinfo=UTC))
    result = service.handle("owner-a", "natural-rigid", "Asia/Shanghai", [
        {"role": "user", "content": "明天下午三点和设计组碰头，持续30分钟"}])

    assert result.draft.draft_id == "draft-natural"
    assert drafts.created[0].start_at == datetime(2026, 9, 27, 15, 0,
                                                    tzinfo=ZoneInfo("Asia/Shanghai"))
    assert drafts.created[0].end_at == datetime(2026, 9, 27, 15, 30,
                                                  tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.mark.parametrize("text", [
    "这周课表是什么？", "西安天气如何？",
    "不要添加高数作业", "如果我说添加高数作业，你会怎样？", "‘添加高数作业’是示例句",
])
def test_unrelated_denied_hypothetical_or_quoted_request_never_writes_or_reads_owner_tasks(text):
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("已添加", [tool("create_flexible_task", {
        "title": "高数作业", "deadline": None})]))

    result = handle(model, tasks, text)

    assert tasks.created == [] and tasks.updated == [] and tasks.deleted == []
    assert tasks.listed == 0
    assert result.action_results == ()


def test_explicit_incidental_task_query_is_still_user_authorized():
    tasks = FakeTasks()
    result = handle(FakeModel(ModelTurn("无关回答")), tasks, "你好，顺便看看我的待办")
    assert tasks.listed == 1
    assert result.action_results[0].status == "succeeded"
    assert "高数作业" in result.answer


@pytest.mark.parametrize("text", [
    "‘明天下午两点上软件工程课，一个小时’",
    "日志写道：‘明天下午两点上软件工程课，一个小时’",
    "如果明天下午两点上软件工程课，一个小时，会怎样？",
    "不要帮我创建明天下午两点的软件工程课，一个小时",
])
def test_quoted_hypothetical_or_denied_fixed_event_does_not_create_a_draft(text):
    class Drafts:
        def create(self, *args, **kwargs):
            raise AssertionError("quoted example must not create a draft")

    service = AssistantService(FakeModel(ModelTurn(None, [tool("create_rigid_event_draft", {})])),
                               FakeTasks(), drafts=Drafts())
    result = service.handle("owner-a", "quoted-event", "Asia/Shanghai", [
        {"role": "user", "content": text}])

    assert result.draft is None
    assert result.action_results == ()


@pytest.mark.parametrize("text", [
    "如果我问还有哪些待办，你会查吗？", "‘查看我的待办’是示例句", "不要查我的待办",
])
def test_hypothetical_quoted_or_denied_query_does_not_read_owner_records(text):
    tasks = FakeTasks()
    result = handle(FakeModel(ModelTurn("有高数作业", [tool("query_flexible_tasks", {})])), tasks, text)

    assert tasks.listed == 0
    assert result.action_results == ()
    assert "高数作业" not in result.answer


def test_model_selected_rigid_query_uses_current_owner_and_seven_day_window():
    class Events:
        def __init__(self): self.calls = []
        def list_occurrences(self, owner_id, start, end):
            self.calls.append((owner_id, start, end))
            return []

    events = Events()
    service = AssistantService(FakeModel(ModelTurn(None, [tool("query_rigid_events", {})])),
                               FakeTasks(), rigid_events=events,
                               clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC))
    result = service.handle("owner-b", "query-window", "Asia/Shanghai", [
        {"role": "user", "content": "我的日程这周怎么排的？"}])

    assert events.calls == [("owner-b", datetime(2026, 9, 25, 16, tzinfo=UTC),
                             datetime(2026, 10, 2, 16, tzinfo=UTC))]
    assert result.action_results[0].action == "query_rigid_events"


def test_personal_schedule_question_without_query_tool_does_not_repeat_model_invention():
    class Events:
        def list_occurrences(self, *args):
            raise AssertionError("no query tool means no owner read")

    service = AssistantService(FakeModel(ModelTurn("你周二有一节不存在的课程。")),
                               FakeTasks(), rigid_events=Events())
    result = service.handle("owner-a", "no-rigid-tool", "Asia/Shanghai", [
        {"role": "user", "content": "我的设计评审日程是什么？"}])

    assert result.action_results == ()
    assert "不存在的课程" not in result.answer
    assert "没有读取" in result.answer


def test_design_review_schedule_title_can_still_be_queried():
    from types import SimpleNamespace

    class Events:
        def list_occurrences(self, owner_id, start, end):
            return [SimpleNamespace(title="设计评审", location="B楼",
                                    start_at=datetime(2026, 9, 27, 6, tzinfo=UTC),
                                    end_at=datetime(2026, 9, 27, 7, tzinfo=UTC),
                                    disposition="scheduled")]

    service = AssistantService(FakeModel(ModelTurn("没有日程", [tool("query_rigid_events", {})])),
                               FakeTasks(), rigid_events=Events(),
                               clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC))
    result = service.handle("owner-a", "design-review-query", "Asia/Shanghai", [
        {"role": "user", "content": "我的设计评审日程是什么？"}])

    assert result.action_results[0].status == "succeeded"
    assert "设计评审" in result.answer


def test_model_selected_task_update_cannot_use_unmentioned_new_title():
    tasks = FakeTasks()
    result = handle(FakeModel(ModelTurn(None, [tool("update_flexible_task", {
        "title": "高数作业", "new_title": "模型自造的新任务"})])), tasks,
        "把高数作业改成数学复习")

    assert tasks.listed == 0 and tasks.updated == []
    assert result.action_results[0].status == "clarification_required"


def test_model_decision_does_not_authorize_tool_without_user_basis():
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("早上好", [tool("create_flexible_task", {
        "title": "高数作业", "deadline": None})]))

    result = handle(model, tasks, "早上好")

    assert tasks.created == []
    assert result.action_results == ()


def test_relative_rigid_request_gets_structured_draft_and_later_confirmation_does_not_shift_it():
    class Drafts:
        def __init__(self): self.created = []
        def create(self, owner_id, candidates, source_message_id, idempotency_key=None,
                   request_hash=None, *, reference_now=None):
            self.created.append(candidates[0])
            from types import SimpleNamespace
            return SimpleNamespace(draft_id="draft-2", candidates=tuple(candidates))
    drafts = Drafts()
    moments = iter([datetime(2026, 9, 26, 14, 15, tzinfo=UTC),
                    datetime(2026, 9, 26, 14, 45, tzinfo=UTC)])
    model = FakeModel(ModelTurn("按当前时间推算为22:25至22:35，是否正确？确认后生成日程草稿。"),
                      ModelTurn(None, [tool("create_rigid_event_draft", {})]))
    service = AssistantService(model, FakeTasks(), drafts=drafts, clock=lambda: next(moments))
    initial = service.handle("owner-a", "initial-meeting", "Asia/Shanghai", [
        {"role": "user", "content": "10分钟后开会，持续10分钟"}])
    assert initial.draft is not None
    assert initial.draft.candidates[0].start_at.strftime("%H:%M") == "22:25"
    assert initial.draft.candidates[0].end_at.strftime("%H:%M") == "22:35"
    result = service.handle("owner-a", "confirm-meeting", "Asia/Shanghai", [
        {"role": "user", "content": "10分钟后开会，持续10分钟"},
        {"role": "assistant", "content": "按当前时间推算为22:25至22:35，是否正确？确认后生成日程草稿。"},
        {"role": "user", "content": "确认"},
    ])
    assert result.draft is None
    assert len(drafts.created) == 1
    assert drafts.created[0].start_at.strftime("%H:%M") == "22:25"
    assert "具体" in result.answer and "开始时间" in result.answer


def test_confirmation_can_reuse_natural_fixed_event_without_legacy_event_keyword():
    class Drafts:
        def create(self, owner_id, candidates, source_message_id, idempotency_key=None,
                   request_hash=None, *, reference_now=None):
            from types import SimpleNamespace
            return SimpleNamespace(draft_id="natural-confirmed", candidate=candidates[0])

    service = AssistantService(FakeModel(ModelTurn(None, [tool("create_rigid_event_draft", {})])),
                               FakeTasks(), drafts=Drafts(),
                               clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC))
    result = service.handle("owner-a", "natural-confirm", "Asia/Shanghai", [
        {"role": "user", "content": "明天下午三点和设计组碰头，持续30分钟"},
        {"role": "assistant", "content": "按明天下午三点开始，持续30分钟，确认吗？"},
        {"role": "user", "content": "确认"},
    ])

    assert result.draft.draft_id == "natural-confirmed"
    assert result.draft.candidate.title


def test_rigid_draft_tool_error_is_localized_and_does_not_leak_internal_message():
    model = FakeModel(ModelTurn(None, [tool("create_rigid_event_draft", {})]))
    service = AssistantService(model, FakeTasks())
    result = service.handle("owner-a", "incomplete-meeting", "Asia/Shanghai", [
        {"role": "user", "content": "会议将于今天晚上开始"}])
    assert "Ask for the missing" not in result.answer
    assert "开始时间" in result.answer
    assert result.action_results == ()


def test_rigid_schedule_is_not_read_for_ambiguous_plan_query():
    class RigidEvents:
        def list_occurrences(self, *_): raise AssertionError("must not read ambiguous query")
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("你想查看固定日程还是柔性任务？"))
    result = AssistantService(model, tasks, rigid_events=RigidEvents()).handle(
        "owner-a", "ambiguous", "Asia/Shanghai", [{"role": "user", "content": "列出我的安排"}])
    assert result.action_results == ()
    assert "固定时间的日程" in result.answer or model.calls


def test_elliptical_flexible_followup_queries_tasks_after_rigid_schedule_answer():
    tasks = FakeTasks()
    service = AssistantService(FakeModel(ModelTurn("根据记录回答。")), tasks)
    result = service.handle("owner-a", "elliptical-flexible", "Asia/Shanghai", [
        {"role": "user", "content": "我现在有哪些日程"},
        {"role": "assistant", "content": "接下来七天没有已保存的刚性日程。\n已查询的刚性日程"},
        {"role": "user", "content": "柔性的呢"},
    ])

    assert tasks.listed == 1
    assert result.action_results[0].action == "query_flexible_tasks"
    assert "高数作业" in result.answer


def test_elliptical_rigid_followup_queries_schedule_after_kind_clarification():
    class Events:
        def __init__(self): self.calls = []
        def list_occurrences(self, owner_id, start, end):
            self.calls.append((owner_id, start, end))
            return []

    events = Events()
    model = FakeModel(ModelTurn(None, [tool("query_rigid_events", {})]))
    service = AssistantService(model, FakeTasks(), rigid_events=events,
        clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    result = service.handle("owner-a", "elliptical-rigid", "Asia/Shanghai", [
        {"role": "user", "content": "柔性的呢"},
        {"role": "assistant", "content": "你是想查看没有固定开始时间的柔性任务，还是查询固定时间的日程？"},
        {"role": "user", "content": "固定时间的日程"},
    ])

    assert len(events.calls) == 1
    assert result.action_results[0].action == "query_rigid_events"
    assert "接下来七天没有已保存的刚性日程" in result.answer


def test_elliptical_schedule_category_without_recent_context_does_not_read_records():
    class Events:
        def list_occurrences(self, *args):
            raise AssertionError("standalone category phrase must not read records")

    model = FakeModel(ModelTurn("这次没有读取记录。", [tool("query_rigid_events", {})]))
    service = AssistantService(model, FakeTasks(), rigid_events=Events())
    result = service.handle("owner-a", "unanchored-rigid-category", "Asia/Shanghai", [
        {"role": "user", "content": "固定时间的日程"},
    ])

    assert result.action_results == ()


def test_user_explicitly_asking_what_they_can_do_runs_task_query_only_on_tool_call():
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("你可以做很多事情。", [tool("query_flexible_tasks", {})]),
                      ModelTurn("你可以先做别的。"))

    result = handle(model, tasks, "我现在有什么可以做的？")

    assert tasks.listed == 1
    assert "高数作业" in result.answer
    assert "很多事情" not in result.answer


def test_model_can_query_and_propose_occurrence_change_without_committing():
    from types import SimpleNamespace

    class Events:
        def __init__(self): self.proposals = []
        def list_occurrences(self, owner_id, start, end):
            return [SimpleNamespace(occurrence_id="occ-1", event_id="event-1", owner_id=owner_id,
                original_slot="2026-09-27T14:00:00+08:00", title="软件工程课", location="A楼",
                start_at=datetime(2026, 9, 27, 6, tzinfo=UTC), end_at=datetime(2026, 9, 27, 7, tzinfo=UTC),
                version=3, schedule_revision=1, disposition="scheduled")]
        def list_events(self, owner_id):
            return [SimpleNamespace(event_id="event-1", owner_id=owner_id, version=9)]
        def propose_event_change(self, *args):
            self.proposals.append(args)
            return {"proposal_id": "proposal-1", "target_id": "occ-1", "scope": "occurrence",
                "revision": 1, "action": "update", "summary": "修改本次：软件工程课",
                "confirmation_digest": "digest-1", "status": "pending"}

    events = Events()
    model = FakeModel(
        ModelTurn(None, [tool("query_rigid_events", {})]),
        ModelTurn(None, [tool("propose_rigid_event_change", {
            "target_id": "occ-1", "expected_version": 3,
            "action": "update", "changes": {"title": "软件工程讨论课"}})]),
    )
    result = AssistantService(model, FakeTasks(), rigid_events=events,
        clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC)).handle(
            "owner-a", "change-1", "Asia/Shanghai", [
                {"role": "user", "content": "把软件工程课改成软件工程讨论课"}])

    assert [item.action for item in result.action_results] == [
        "query_rigid_events", "propose_rigid_event_change"]
    proposal = result.action_results[-1]
    assert proposal.status == "succeeded"
    assert proposal.data == {"proposal_id": "proposal-1", "target_id": "occ-1", "scope": "occurrence",
        "revision": 1, "action": "update", "summary": "修改本次：软件工程课",
        "confirmation_digest": "digest-1", "status": "pending", "target_title": "软件工程课",
        "changes": {"title": "软件工程讨论课"}}
    assert events.proposals[0][0:6] == (
        "owner-a", "occ-1", "occurrence", 3, "update", {"title": "软件工程讨论课"})
    assert any(message.get("role") == "tool" and '"series_version":9' in message.get("content", "")
               for message in model.calls[1][0])


def test_series_change_requires_explicit_whole_series_language_and_uses_series_version():
    from types import SimpleNamespace

    class Events:
        def __init__(self): self.proposals = []
        def list_occurrences(self, owner_id, start, end):
            return [SimpleNamespace(occurrence_id="occ-series", event_id="event-series", owner_id=owner_id,
                original_slot="2026-09-28T14:00:00+08:00", title="软件工程课", location=None,
                start_at=datetime(2026, 9, 28, 6, tzinfo=UTC), end_at=datetime(2026, 9, 28, 7, tzinfo=UTC),
                version=2, schedule_revision=1, disposition="scheduled")]
        def list_events(self, owner_id):
            return [SimpleNamespace(event_id="event-series", owner_id=owner_id, version=12)]
        def propose_event_change(self, *args):
            self.proposals.append(args)
            return {"proposal_id": "proposal-series", "target_id": "event-series", "scope": "series",
                "revision": 1, "action": "delete", "summary": "删除整个系列：软件工程课",
                "confirmation_digest": "digest-s", "status": "pending"}

    events = Events()
    model = FakeModel(ModelTurn(None, [tool("query_rigid_events", {})]),
        ModelTurn(None, [tool("propose_rigid_event_change", {
            "target_id": "event-series", "scope": "series", "expected_version": 12,
            "action": "delete", "changes": {}})]))
    result = AssistantService(model, FakeTasks(), rigid_events=events,
        clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC)).handle(
            "owner-a", "delete-series", "Asia/Shanghai", [
                {"role": "user", "content": "删除软件工程课整个系列"}])

    assert result.action_results[-1].status == "succeeded", result.action_results[-1].message
    assert events.proposals[0][1:6] == ("event-series", "series", 12, "delete", {})


def test_series_scope_without_explicit_user_language_and_stale_target_version_are_rejected():
    from types import SimpleNamespace

    class Events:
        def __init__(self): self.proposals = []
        def list_occurrences(self, owner_id, start, end):
            return [SimpleNamespace(occurrence_id="occ-stale", event_id="event-stale", owner_id=owner_id,
                original_slot="2026-09-27T14:00:00+08:00", title="软件工程课", location=None,
                start_at=datetime(2026, 9, 27, 6, tzinfo=UTC), end_at=datetime(2026, 9, 27, 7, tzinfo=UTC),
                version=3, schedule_revision=1, disposition="scheduled")]
        def list_events(self, owner_id):
            return [SimpleNamespace(event_id="event-stale", owner_id=owner_id, version=9)]
        def propose_event_change(self, *args):
            self.proposals.append(args)
            return {"proposal_id": "proposal", "target_id": args[1], "scope": args[2],
                "revision": 1, "action": args[4], "summary": "proposal",
                "confirmation_digest": "digest", "status": "pending"}

    for text, scope, version in [
        ("删除软件工程课", "series", 9),
        ("把软件工程课改成软件工程讨论课", "occurrence", 2),
    ]:
        events = Events()
        target = "event-stale" if scope == "series" else "occ-stale"
        model = FakeModel(ModelTurn(None, [tool("query_rigid_events", {})]),
            ModelTurn(None, [tool("propose_rigid_event_change", {
                "target_id": target, "scope": scope, "expected_version": version,
                "action": "delete" if scope == "series" else "update",
                "changes": {} if scope == "series" else {"title": "软件工程讨论课"}})]))
        result = AssistantService(model, FakeTasks(), rigid_events=events,
            clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC)).handle(
                "owner-a", "invalid-proposal", "Asia/Shanghai", [{"role": "user", "content": text}])
        assert events.proposals == []
        assert result.action_results[-1].status in {"clarification_required", "conflict", "rejected"}


def test_proposal_for_missing_or_ambiguous_query_target_is_not_created():
    from types import SimpleNamespace

    class Events:
        def __init__(self): self.proposals = []
        def list_occurrences(self, owner_id, start, end):
            return [SimpleNamespace(occurrence_id=f"occ-{i}", event_id=f"event-{i}", owner_id=owner_id,
                original_slot=f"2026-09-{27+i}T14:00:00+08:00", title="软件工程课", location=None,
                start_at=datetime(2026, 9, 27+i, 6, tzinfo=UTC), end_at=datetime(2026, 9, 27+i, 7, tzinfo=UTC),
                version=1, schedule_revision=1, disposition="scheduled") for i in range(2)]
        def list_events(self, owner_id):
            return [SimpleNamespace(event_id=f"event-{i}", owner_id=owner_id, version=1) for i in range(2)]
        def propose_event_change(self, *args):
            self.proposals.append(args)
            return {}

    for target_id in ("not-in-query", "occ-0"):
        events = Events()
        model = FakeModel(ModelTurn(None, [tool("query_rigid_events", {})]),
            ModelTurn(None, [tool("propose_rigid_event_change", {
                "target_id": target_id, "scope": "occurrence", "expected_version": 1,
                "action": "delete", "changes": {}})]))
        result = AssistantService(model, FakeTasks(), rigid_events=events,
            clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC)).handle(
                "owner-a", "ambiguous-proposal", "Asia/Shanghai", [{"role": "user", "content": "删除软件工程课"}])
        assert events.proposals == []
        assert result.action_results[-1].status in {"clarification_required", "not_found", "rejected"}


@pytest.mark.parametrize("text", [
    "不要把软件工程课改成软件工程讨论课",
    "如果把软件工程课改成软件工程讨论课会怎样？",
    "‘把软件工程课改成软件工程讨论课’是示例句",
])
def test_denied_hypothetical_or_quoted_rigid_change_cannot_query_or_propose(text):
    class Events:
        def __init__(self): self.queries = 0; self.proposals = []
        def list_occurrences(self, *args):
            self.queries += 1
            return []
        def list_events(self, owner_id): return []
        def propose_event_change(self, *args): self.proposals.append(args)

    events = Events()
    model = FakeModel(ModelTurn(None, [tool("query_rigid_events", {})]),
                      ModelTurn(None, [tool("propose_rigid_event_change", {
                          "target_id": "occ-1", "expected_version": 1, "action": "delete", "changes": {}})]))
    result = AssistantService(model, FakeTasks(), rigid_events=events).handle(
        "owner-a", "unsafe-change", "Asia/Shanghai", [{"role": "user", "content": text}])

    assert events.queries == 0
    assert events.proposals == []
    assert result.action_results == ()


def test_model_cannot_delete_when_user_requested_rigid_event_update():
    from types import SimpleNamespace

    class Events:
        def __init__(self): self.proposals = []
        def list_occurrences(self, owner_id, start, end):
            return [SimpleNamespace(occurrence_id="op-mismatch", event_id="event-mismatch", owner_id=owner_id,
                title="软件工程课", location=None, start_at=datetime(2026, 9, 27, 6, tzinfo=UTC),
                end_at=datetime(2026, 9, 27, 7, tzinfo=UTC), version=1, schedule_revision=1,
                disposition="scheduled")]
        def list_events(self, owner_id): return [SimpleNamespace(event_id="event-mismatch", version=1)]
        def propose_event_change(self, *args): self.proposals.append(args); return {}

    events = Events()
    model = FakeModel(ModelTurn(None, [tool("query_rigid_events", {})]),
        ModelTurn(None, [tool("propose_rigid_event_change", {
            "target_id": "op-mismatch", "expected_version": 1, "action": "delete", "changes": {}})]))
    result = AssistantService(model, FakeTasks(), rigid_events=events,
        clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC)).handle(
            "owner-a", "wrong-action", "Asia/Shanghai", [{"role": "user",
                "content": "把软件工程课改成软件工程讨论课"}])

    assert events.proposals == []
    assert result.action_results[-1].status in {"rejected", "clarification_required"}


def test_explicit_weekday_must_match_target_even_when_only_one_event_has_that_title():
    from types import SimpleNamespace

    class Events:
        def __init__(self): self.proposals = []
        def list_occurrences(self, owner_id, start, end):
            # Tuesday, while the user explicitly said Monday.
            return [SimpleNamespace(occurrence_id="tuesday-course", event_id="event-tuesday", owner_id=owner_id,
                title="软件工程课", location=None, start_at=datetime(2026, 9, 29, 6, tzinfo=UTC),
                end_at=datetime(2026, 9, 29, 7, tzinfo=UTC), version=1, schedule_revision=1,
                disposition="scheduled")]
        def list_events(self, owner_id): return [SimpleNamespace(event_id="event-tuesday", version=1)]
        def propose_event_change(self, *args): self.proposals.append(args); return {}

    events = Events()
    model = FakeModel(ModelTurn(None, [tool("query_rigid_events", {})]),
        ModelTurn(None, [tool("propose_rigid_event_change", {
            "target_id": "tuesday-course", "expected_version": 1, "action": "delete", "changes": {}})]))
    result = AssistantService(model, FakeTasks(), rigid_events=events,
        clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC)).handle(
            "owner-a", "wrong-date", "Asia/Shanghai", [{"role": "user",
                "content": "取消周一的软件工程课"}])

    assert events.proposals == []
    assert result.action_results[-1].status == "clarification_required"


def test_moving_uniquely_identified_course_to_tomorrow_does_not_treat_new_date_as_target_date():
    from types import SimpleNamespace

    class Events:
        def __init__(self): self.proposals = []
        def list_occurrences(self, owner_id, start, end):
            # The existing instance is today; tomorrow is the requested new start date.
            return [SimpleNamespace(occurrence_id="today-course", event_id="event-today", owner_id=owner_id,
                title="软件工程课", location=None, start_at=datetime(2026, 9, 26, 6, tzinfo=UTC),
                end_at=datetime(2026, 9, 26, 7, tzinfo=UTC), version=1, schedule_revision=1,
                disposition="scheduled")]
        def list_events(self, owner_id): return [SimpleNamespace(event_id="event-today", version=1)]
        def propose_event_change(self, *args):
            self.proposals.append(args)
            return {"proposal_id": "move-tomorrow", "target_id": "today-course", "scope": "occurrence",
                "revision": 1, "action": "update", "summary": "proposal",
                "confirmation_digest": "digest", "status": "pending"}

    events = Events()
    model = FakeModel(ModelTurn(None, [tool("query_rigid_events", {})]),
        ModelTurn(None, [tool("propose_rigid_event_change", {
            "target_id": "today-course", "expected_version": 1, "action": "update",
            "changes": {"start_at": "2026-09-27T15:00:00+08:00",
                        "end_at": "2026-09-27T16:00:00+08:00"}})]))
    result = AssistantService(model, FakeTasks(), rigid_events=events,
        clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC)).handle(
            "owner-a", "move-tomorrow", "Asia/Shanghai", [{"role": "user",
                "content": "把软件工程课改到明天下午三点开始，持续一小时"}])

    assert events.proposals
    assert result.action_results[-1].status == "succeeded"


@pytest.mark.parametrize("text,args", [
    ("把软件工程课改成软件工程讨论课", {"title": "软件工程课"}),
    ("把软件工程课的地点从A楼改到B楼", {"location": "A楼"}),
    ("把软件工程课改到明天下午三点开始，持续一小时", {
        "start_at": "2026-09-27T14:00:00+08:00", "end_at": "2026-09-27T15:00:00+08:00"}),
])
def test_rigid_update_values_must_match_new_values_requested_by_user(text, args):
    from types import SimpleNamespace

    class Events:
        def __init__(self): self.proposals = []
        def list_occurrences(self, owner_id, start, end):
            return [SimpleNamespace(occurrence_id="wrong-value", event_id="event-wrong-value", owner_id=owner_id,
                title="软件工程课", location="A楼", start_at=datetime(2026, 9, 27, 6, tzinfo=UTC),
                end_at=datetime(2026, 9, 27, 7, tzinfo=UTC), version=1, schedule_revision=1,
                disposition="scheduled")]
        def list_events(self, owner_id): return [SimpleNamespace(event_id="event-wrong-value", version=1)]
        def propose_event_change(self, *proposal_args): self.proposals.append(proposal_args); return {}

    events = Events()
    model = FakeModel(ModelTurn(None, [tool("query_rigid_events", {})]),
        ModelTurn(None, [tool("propose_rigid_event_change", {
            "target_id": "wrong-value", "expected_version": 1, "action": "update", "changes": args})]))
    result = AssistantService(model, FakeTasks(), rigid_events=events,
        clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC)).handle(
            "owner-a", "wrong-value", "Asia/Shanghai", [{"role": "user", "content": text}])

    assert events.proposals == []
    assert result.action_results[-1].status == "clarification_required"


@pytest.mark.parametrize("text,changes", [
    ("把软件工程课的地点从A楼改到B楼", {"location": "B楼"}),
    ("把软件工程课改到明天下午三点开始，持续一小时", {
        "start_at": "2026-09-27T15:00:00+08:00", "end_at": "2026-09-27T16:00:00+08:00"}),
])
def test_rigid_update_accepts_exact_user_requested_location_and_time(text, changes):
    from types import SimpleNamespace

    class Events:
        def __init__(self): self.proposals = []
        def list_occurrences(self, owner_id, start, end):
            return [SimpleNamespace(occurrence_id="exact-value", event_id="event-exact-value", owner_id=owner_id,
                title="软件工程课", location="A楼", start_at=datetime(2026, 9, 27, 6, tzinfo=UTC),
                end_at=datetime(2026, 9, 27, 7, tzinfo=UTC), version=1, schedule_revision=1,
                disposition="scheduled")]
        def list_events(self, owner_id): return [SimpleNamespace(event_id="event-exact-value", version=1)]
        def propose_event_change(self, *proposal_args):
            self.proposals.append(proposal_args)
            return {"proposal_id": "proposal-exact", "target_id": "exact-value", "scope": "occurrence",
                "revision": 1, "action": "update", "summary": "proposal",
                "confirmation_digest": "digest", "status": "pending"}

    events = Events()
    model = FakeModel(ModelTurn(None, [tool("query_rigid_events", {})]),
        ModelTurn(None, [tool("propose_rigid_event_change", {
            "target_id": "exact-value", "expected_version": 1, "action": "update", "changes": changes})]))
    result = AssistantService(model, FakeTasks(), rigid_events=events,
        clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC)).handle(
            "owner-a", "exact-value", "Asia/Shanghai", [{"role": "user", "content": text}])

    assert result.action_results[-1].status == "succeeded"
    assert events.proposals[0][5] == changes


@pytest.mark.parametrize("text", ["添加任务高数作业", "把高数作业改成复习", "删除高数作业"])
def test_model_prose_cannot_claim_a_task_write_without_successful_tool_result(text):
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("已经成功保存或修改了任务。"))

    result = handle(model, tasks, text)

    assert tasks.created == [] and tasks.updated == [] and tasks.deleted == []
    assert "没有得到服务端确认" in result.answer
    assert "已经成功" not in result.answer


def test_explicit_create_binds_owner_timezone_and_client_message_and_stable_idempotency():
    args = {"title": "操作系统实验", "deadline": "2026-09-27"}
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("我记下了。", [tool("create_flexible_task", args)]))

    result = handle(model, tasks, "帮我添加柔性任务：周日前完成操作系统实验。", "client-77")
    retry_model = FakeModel(ModelTurn("记录完成。", [tool("create_flexible_task", args)]))
    retry = handle(retry_model, tasks, "帮我添加柔性任务：周日前完成操作系统实验。", "client-77")

    assert result.action_results[0].status == "succeeded"
    assert tasks.created[0]["owner_id"] == "owner-a"
    assert tasks.created[0]["source_message_id"] == "client-77"
    assert tasks.created[0]["timezone"] == "Asia/Shanghai"
    assert tasks.created[0]["deadline"] == date(2026, 9, 27)
    assert tasks.created[0]["idempotency_key"] == tasks.created[1]["idempotency_key"]
    assert retry.action_results[0].status == "succeeded"
    assert result.answer == '已添加柔性任务："操作系统实验"'


def test_model_selected_create_without_legacy_task_keyword_uses_server_result():
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("已经安排到明天上午。", [tool("create_flexible_task", {
        "title": "读书笔记", "deadline": None})]))

    result = handle(model, tasks, "新增读书笔记，另外西安天气怎么样")

    assert len(tasks.created) == 1
    assert result.action_results[0].status == "succeeded"
    assert result.answer == '已添加柔性任务："读书笔记"'


def test_create_title_must_be_a_whole_title_explicitly_present_in_user_turn():
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("已添加", [tool("create_flexible_task", {
        "title": "实验", "deadline": None
    })]))

    result = handle(model, tasks, "帮我添加操作系统实验")

    assert tasks.created == []
    assert result.action_results[0].status == "clarification_required"


@pytest.mark.parametrize("name,args,text", [
    ("create_flexible_task", {"title": "x", "sql": "drop table"}, "新增任务 x"),
    ("create_flexible_task", {"title": "x", "deadline": "tomorrow"}, "新增任务 x"),
    ("arbitrary_http", {"url": "https://evil.invalid"}, "新增任务 x"),
])
def test_unknown_tool_or_invalid_arguments_never_mutate(name, args, text):
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("完成", [tool(name, args)]))

    result = handle(model, tasks, text)

    assert not tasks.created and not tasks.updated and not tasks.deleted
    if name == "arbitrary_http":
        assert result.action_results == ()
    else:
        assert result.action_results[0].status == "invalid"


def test_update_and_delete_require_explicit_matching_intent_and_surface_ambiguity_without_write():
    from kairos.domain.tasks import AmbiguousTaskTitle

    class AmbiguousTasks(FakeTasks):
        def list(self, owner_id):
            self.listed += 1
            return [{"title": "高数作业"}, {"title": "高数作业"}]

        def update_by_title(self, **kwargs):
            raise AmbiguousTaskTitle("ambiguous")

        def delete_by_title(self, **kwargs):
            raise AmbiguousTaskTitle("ambiguous")

    tasks = AmbiguousTasks()
    model = FakeModel(ModelTurn(None, [tool("update_flexible_task", {"title": "高数作业", "new_title": "大学数学复习"})]))
    result = handle(model, tasks, "把高数作业任务标题改成大学数学复习")
    assert not tasks.updated
    assert result.action_results[0].status == "clarification_required"

    model = FakeModel(ModelTurn(None, [tool("delete_flexible_task", {"title": "高数作业"})]))
    result = handle(model, tasks, "删除高数作业任务")
    assert not tasks.deleted
    assert result.action_results[0].status == "clarification_required"


def test_unique_update_and_delete_call_only_owner_scoped_title_use_cases():
    tasks = FakeTasks()
    update_call = tool("update_flexible_task", {"title": "高数作业", "new_title": "大学数学复习"})
    result = handle(FakeModel(ModelTurn(None, [update_call])), tasks,
                    "把高数作业任务标题改成大学数学复习", "update-msg")
    assert result.action_results[0].status == "succeeded"
    assert tasks.updated[0]["owner_id"] == "owner-a"
    assert tasks.updated[0]["title"] == "高数作业"
    assert tasks.updated[0]["changes"] == {"title": "大学数学复习"}
    assert tasks.updated[0]["source_message_id"] == "update-msg"
    assert result.answer == '已更新柔性任务："新标题"'

    delete_call = tool("delete_flexible_task", {"title": "高数作业"})
    result = handle(FakeModel(ModelTurn(None, [delete_call])), tasks,
                    "删除高数作业任务", "delete-msg")
    assert result.action_results[0].status == "succeeded"
    assert tasks.deleted[0]["owner_id"] == "owner-a"
    assert tasks.deleted[0]["title"] == "高数作业"
    assert tasks.deleted[0]["source_message_id"] == "delete-msg"
    assert result.answer == '已删除柔性任务："高数作业"'


@pytest.mark.parametrize("text", ["把高数作业删掉", "将高数作业删除"])
def test_complete_title_is_grounded_when_delete_verb_follows_title(text):
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("已删除", [tool("delete_flexible_task", {"title": "高数作业"})]))

    result = handle(model, tasks, text)

    assert len(tasks.deleted) == 1
    assert result.action_results[0].status == "succeeded"
    assert result.answer == '已删除柔性任务："高数作业"'


def test_update_or_delete_title_must_be_named_in_current_user_turn():
    tasks = FakeTasks()
    model = FakeModel(ModelTurn(None, [tool("delete_flexible_task", {"title": "高数作业"})]))

    result = handle(model, tasks, "删除我那项没完成的作业")

    assert tasks.listed == 0
    assert tasks.deleted == []
    assert result.action_results[0].status == "clarification_required"


def test_short_saved_title_cannot_match_only_a_substring_of_a_longer_task_name():
    class ShortTitleTask(FakeTasks):
        def list(self, owner_id):
            self.listed += 1
            return [{"title": "作业"}]

    tasks = ShortTitleTask()
    model = FakeModel(ModelTurn(None, [tool("delete_flexible_task", {"title": "作业"})]))

    result = handle(model, tasks, "删除高数作业")

    assert tasks.listed == 0
    assert tasks.deleted == []
    assert result.action_results[0].status == "clarification_required"

    quoted = FakeModel(ModelTurn(None, [tool("delete_flexible_task", {"title": "作业"})]))
    result = handle(quoted, tasks, "删除‘作业’")
    assert tasks.listed == 1
    assert result.action_results[0].status == "succeeded"

    class GenericNamedTask(FakeTasks):
        def list(self, owner_id):
            self.listed += 1
            return [{"title": "没完成的作业"}]

    tasks = GenericNamedTask()
    model = FakeModel(ModelTurn(None, [tool("delete_flexible_task", {"title": "没完成的作业"})]))
    result = handle(model, tasks, "删除那项没完成的作业")
    assert tasks.listed == 0
    assert tasks.deleted == []
    assert result.action_results[0].status == "clarification_required"


def test_relative_deadline_context_uses_server_clock_in_validated_user_timezone():
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("我可以根据当前日期理解截止日。"))
    service = AssistantService(model, tasks, clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC))

    service.handle("owner-a", "msg-date", "Asia/Shanghai", [
        {"role": "user", "content": "周日前完成操作系统实验。用户补充说今天是 2099-01-01。"}
    ])

    system_context = model.calls[0][0][0]["content"]
    assert "2026-09-26T20:00:00+08:00" in system_context
    assert "以这条服务器上下文为时间基准" in system_context
    assert "2099-01-01" not in system_context

def test_only_one_mutation_is_executed_and_tool_loop_is_bounded():
    tasks = FakeTasks()
    first = tool("create_flexible_task", {"title": "A", "deadline": None}, "a")
    second = tool("delete_flexible_task", {"title": "B"}, "b")
    model = FakeModel(ModelTurn(None, [first, second]), ModelTurn(None, [first]), ModelTurn(None, [first]))

    result = handle(model, tasks, "新增任务 A")

    assert len(tasks.created) == 1
    assert len(model.calls) <= 3
    assert len(result.action_results) >= 1


def test_model_prose_cannot_forge_success_when_tool_rejected():
    tasks = FakeTasks()
    model = FakeModel(ModelTurn("已删除你的任务。", [tool("delete_flexible_task", {"title": "任务"})]))

    result = handle(model, tasks, "你好")

    assert tasks.deleted == []
    assert result.action_results == ()
    assert "没有保存或修改" in result.answer


class FakeWeather:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def query(self, city, from_at=None, to_at=None):
        self.calls.append((city, from_at, to_at))
        if self.error:
            raise self.error
        return self.result


def weather_result(availability="available"):
    return WeatherResult(
        availability=availability,
        location=WeatherLocation("西安", 34.26, 108.94, "Asia/Shanghai", "中国", "陕西"),
        source="Open-Meteo",
        fetched_at=datetime(2026, 9, 26, 12, tzinfo=UTC),
        observations=(WeatherObservation("rain", 80, 1.2, 12000,
            datetime(2026, 9, 26, 12, tzinfo=UTC),
            datetime(2026, 9, 26, 13, tzinfo=UTC)),),
        attribution="Weather data by Open-Meteo (CC BY 4.0)",
    )


def weather_handle(weather, model, text):
    return AssistantService(model, FakeTasks(), weather=weather,
        clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC)).handle(
        "owner-a", "weather-msg", "Asia/Shanghai", [{"role": "user", "content": text}])


def test_explicit_current_weather_question_returns_provider_facts_with_freshness():
    weather = FakeWeather(weather_result())
    model = FakeModel(ModelTurn("凭空回答晴天", [tool("query_weather", {"city": "西安"})]),
                      ModelTurn("天气晴朗，来源未知"))

    result = weather_handle(weather, model, "西安现在天气怎么样？")

    assert weather.calls == [("西安", None, None)]
    assert result.action_results[0].status == "succeeded"
    assert "rain" in result.answer or "雨" in result.answer
    assert "Open-Meteo" in result.answer
    assert "2026-09-26" in result.answer
    assert "晴朗" not in result.answer
    assert result.action_results[0].data["source"] == "Open-Meteo"


def test_model_selected_weather_read_uses_provider_when_request_mentions_two_topics():
    weather = FakeWeather(weather_result())
    result = weather_handle(weather, FakeModel(ModelTurn("晴天", [
        tool("query_weather", {"city": "西安"})])), "西安天气怎么样，顺便查我的待办")

    assert len(weather.calls) == 1
    assert "Open-Meteo" in result.answer
    assert "雨" in result.answer


def test_incidental_city_or_non_weather_request_cannot_read_weather():
    weather = FakeWeather(weather_result())
    call = tool("query_weather", {"city": "西安"})
    for text in ("我在西安，帮我记操作系统实验", "西安的项目会安排好了没有？",
                 "我在西安开发天气问答界面，先说说布局"):
        result = weather_handle(weather, FakeModel(ModelTurn("现在有雨", [call])), text)
        assert result.action_results == ()
        assert "现在有雨" not in result.answer
    assert weather.calls == []


def test_weather_city_must_be_in_current_request_not_model_invention_or_chat_history():
    weather = FakeWeather(weather_result())
    result = weather_handle(weather, FakeModel(ModelTurn(None, [tool("query_weather", {"city": "西安"})])),
                            "现在天气如何？")
    assert weather.calls == []
    assert result.action_results[0].status == "clarification_required"
    assert "城市" in result.answer


def test_ambiguous_city_returns_choices_without_a_forecast_claim():
    ambiguity = WeatherLocationAmbiguous("Springfield", (
        WeatherLocationChoice("Springfield", 39.8, -89.6, "America/Chicago", "美国", "Illinois"),
        WeatherLocationChoice("Springfield", 37.2, -93.3, "America/Chicago", "美国", "Missouri"),
    ))
    weather = FakeWeather(error=ambiguity)
    model = FakeModel(ModelTurn("晴天", [tool("query_weather", {"city": "Springfield"})]))

    result = weather_handle(weather, model, "Springfield 现在天气如何？")

    assert result.action_results[0].status == "clarification_required"
    assert len(result.action_results[0].data["choices"]) == 2
    assert "Illinois" in result.answer and "Missouri" in result.answer
    assert "晴天" not in result.answer


def test_unavailable_weather_is_honest_and_still_cites_provider_and_fetch_time():
    unavailable = WeatherResult("unavailable", None, "Open-Meteo",
                                datetime(2026, 9, 26, 12, tzinfo=UTC), (),
                                "Weather data by Open-Meteo (CC BY 4.0)", "offline")
    result = weather_handle(FakeWeather(unavailable), FakeModel(ModelTurn("晴天", [
        tool("query_weather", {"city": "西安"})])), "西安现在天气如何？")

    assert result.action_results[0].status == "unavailable"
    assert "不可用" in result.answer
    assert "Open-Meteo" in result.answer
    assert "2026-09-26" in result.answer
    assert "晴天" not in result.answer


def test_weather_tool_cannot_query_past_or_unrequested_forecast_range():
    weather = FakeWeather(weather_result())
    result = weather_handle(weather, FakeModel(ModelTurn(None, [tool("query_weather", {
        "city": "西安", "from_at": "2026-09-24T00:00:00+08:00",
        "to_at": "2026-09-24T23:00:00+08:00"})])), "西安未来天气如何？")

    assert weather.calls == []
    assert result.action_results[0].status == "invalid"


def test_tomorrow_weather_rejects_a_model_window_for_the_wrong_day():
    weather = FakeWeather(weather_result())
    result = weather_handle(weather, FakeModel(ModelTurn(None, [tool("query_weather", {
        "city": "西安", "from_at": "2026-09-28T00:00:00+08:00",
        "to_at": "2026-09-29T00:00:00+08:00"})])), "明天西安天气如何？")

    assert weather.calls == []
    assert result.action_results[0].status == "invalid"


def test_tomorrow_weather_reads_only_the_requested_future_day():
    weather = FakeWeather(weather_result())
    result = weather_handle(weather, FakeModel(ModelTurn(None, [tool("query_weather", {
        "city": "西安", "from_at": "2026-09-27T00:00:00+08:00",
        "to_at": "2026-09-28T00:00:00+08:00"})])), "明天西安天气如何？")

    assert result.action_results[0].status == "succeeded"
    assert weather.calls[0][1].isoformat() == "2026-09-27T00:00:00+08:00"
    assert weather.calls[0][2].isoformat() == "2026-09-28T00:00:00+08:00"


def test_previous_weather_city_is_not_a_default_for_next_user_turn():
    weather = FakeWeather(weather_result())
    service = AssistantService(FakeModel(ModelTurn("西安下雨了。", [tool("query_weather", {
        "city": "西安"})])), FakeTasks(), weather=weather,
        clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC))
    service.handle("owner-a", "first", "Asia/Shanghai", [
        {"role": "user", "content": "西安现在天气如何？"}])
    service.model = FakeModel(ModelTurn("和上次一样", [tool("query_weather", {"city": "西安"})]))
    second = service.handle("owner-a", "second", "Asia/Shanghai", [
        {"role": "assistant", "content": "西安刚才下雨。"},
        {"role": "user", "content": "现在天气如何？"}])

    assert len(weather.calls) == 1
    assert second.action_results[0].status == "clarification_required"
    assert "城市" in second.answer
    assert "和上次一样" not in second.answer


def test_question_about_whether_it_will_rain_tomorrow_is_a_weather_request():
    weather = FakeWeather(weather_result())
    result = weather_handle(weather, FakeModel(ModelTurn(None, [tool("query_weather", {
        "city": "西安", "from_at": "2026-09-27T00:00:00+08:00",
        "to_at": "2026-09-28T00:00:00+08:00"})])), "西安明天会下雨吗")

    assert result.action_results[0].status == "succeeded"
    assert len(weather.calls) == 1


def test_weather_model_repeat_does_not_trigger_another_provider_request():
    weather = FakeWeather(weather_result())
    model = FakeModel(ModelTurn(None, [tool("query_weather", {"city": "西安"})]),
                      ModelTurn(None, [tool("query_weather", {"city": "西安"})]))

    result = weather_handle(weather, model, "西安现在天气如何？")

    assert len(weather.calls) == 1
    assert len(result.action_results) == 1


def test_duration_before_course_name_preserves_specific_title():
    candidate = parse_event_candidate('我15分钟后有一个持续90分钟的网络工程课程在9阶1',
                                     'Asia/Shanghai', datetime(2026, 9, 27, 4, tzinfo=UTC))
    assert candidate.title == '网络工程课程'
    assert candidate.location == '9阶1'
    assert (candidate.end_at - candidate.start_at).total_seconds() == 5400
