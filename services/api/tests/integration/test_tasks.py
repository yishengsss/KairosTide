from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from kairos.adapters.persistence.sqlite import SqliteRepository
from kairos.application.tasks import FlexibleTaskService
from kairos.domain.tasks import AmbiguousTaskTitle, IdempotencyConflict, TaskNotFound
from kairos.main import create_app


def service(path):
    return FlexibleTaskService(SqliteRepository(path))


def test_create_and_list_survive_repository_recreation_and_are_owner_scoped(tmp_path):
    path = tmp_path / "kairos.db"
    tasks = service(path)
    saved = tasks.create("alice", "操作系统实验", date(2026, 9, 27), "date", "Asia/Shanghai", "msg-1", "create-1")
    tasks.create("bob", "另一项", None, None, "Asia/Shanghai", "msg-2", "create-2")

    reopened = service(path)
    assert reopened.list("alice") == [saved]
    assert reopened.list("bob")[0].title == "另一项"


def test_date_and_instant_deadlines_keep_their_precision(tmp_path):
    tasks = service(tmp_path / "kairos.db")
    day = tasks.create("local", "日期截止", date(2026, 9, 27), "date", "Asia/Shanghai", "d", "d1")
    instant_value = datetime(2026, 9, 27, 12, 30, tzinfo=timezone.utc)
    instant = tasks.create("local", "具体时刻", instant_value, "instant", "Asia/Shanghai", "i", "i1")
    reopened = service(tmp_path / "kairos.db")
    records = {record.title: record for record in reopened.list("local")}
    assert records["日期截止"].deadline == date(2026, 9, 27)
    assert records["日期截止"].deadline_precision == "date"
    assert records["具体时刻"].deadline == instant_value
    assert records["具体时刻"].deadline_precision == "instant"
    assert day != instant


def test_create_is_idempotent_and_rejects_key_reuse_with_different_payload(tmp_path):
    tasks = service(tmp_path / "kairos.db")
    first = tasks.create("local", "实验", None, None, "Asia/Shanghai", "msg", "key")
    retry = tasks.create("local", "实验", None, None, "Asia/Shanghai", "msg", "key")
    assert retry == first
    with pytest.raises(IdempotencyConflict):
        tasks.create("local", "别的任务", None, None, "Asia/Shanghai", "msg", "key")
    assert tasks.list("local") == [first]


def test_migrations_are_recorded_once_and_legacy_database_gets_new_schema(tmp_path):
    path = tmp_path / "kairos.db"
    SqliteRepository(path)
    first = SqliteRepository(path)
    with first._connect() as connection:
        before = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    assert [row[0] for row in before] == ["001_initial.sql", "002_flexible_tasks.sql", "003_rigid_changes.sql", "004_flexible_task_lifecycle.sql"]
    second = SqliteRepository(path)
    with second._connect() as connection:
        after = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    assert [row[0] for row in after] == [row[0] for row in before]


def test_update_retry_returns_original_result_after_later_mutation(tmp_path):
    tasks = service(tmp_path / "kairos.db")
    original = tasks.create("local", "实验", None, None, "Asia/Shanghai", "msg", "create")
    first = tasks.update_by_title("local", "实验", {"title": "报告"}, "edit-1", "update-1")
    tasks.update_by_title("local", "报告", {"title": "最终报告"}, "edit-2", "update-2")
    assert tasks.update_by_title("local", "实验", {"title": "报告"}, "edit-1", "update-1") == first
    assert tasks.list("local")[0].version == original.version + 2


def test_unique_title_update_increments_version_and_delete_removes_task(tmp_path):
    tasks = service(tmp_path / "kairos.db")
    original = tasks.create("local", "实验", None, None, "Asia/Shanghai", "msg", "key")
    updated = tasks.update_by_title("local", "实验", {"title": "实验报告"}, "edit-msg", "edit-key")
    assert updated.title == "实验报告"
    assert updated.version == original.version + 1
    removed = tasks.delete_by_title("local", "实验报告", "delete-msg", "delete-key")
    assert removed == updated
    assert tasks.list("local") == []


@pytest.mark.parametrize("deadline,precision", [
    (date(2026, 9, 28), "date"),
    (datetime(2026, 9, 28, 12, 30, tzinfo=timezone.utc), "instant"),
])
def test_update_deadline_preserves_precision_and_supports_idempotent_retry(tmp_path, deadline, precision):
    tasks = service(tmp_path / "kairos.db")
    original = tasks.create("local", "实验", None, None, "Asia/Shanghai", "msg", "create")

    updated = tasks.update_by_title("local", "实验", {
        "deadline": deadline, "deadline_precision": precision,
    }, "edit", "update-deadline")

    reopened = service(tmp_path / "kairos.db").list("local")[0]
    assert updated.deadline == deadline
    assert updated.deadline_precision == precision
    assert reopened.deadline == deadline
    assert reopened.deadline_precision == precision
    assert tasks.update_by_title("local", "实验", {
        "deadline": deadline, "deadline_precision": precision,
    }, "edit", "update-deadline") == updated
    assert updated.version == original.version + 1


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_duplicate_casefolded_title_is_ambiguous_and_never_mutates(tmp_path, operation):
    tasks = service(tmp_path / "kairos.db")
    first = tasks.create("local", "Task", None, None, "Asia/Shanghai", "m1", "k1")
    second = tasks.create("local", "task", None, None, "Asia/Shanghai", "m2", "k2")
    with pytest.raises(AmbiguousTaskTitle):
        if operation == "update":
            tasks.update_by_title("local", "TASK", {"title": "新标题"}, "edit", "mutation-key")
        else:
            tasks.delete_by_title("local", "TASK", "delete", "mutation-key")
    assert set(tasks.list("local")) == {first, second}


def test_missing_or_cross_owner_title_is_not_found_without_mutation(tmp_path):
    tasks = service(tmp_path / "kairos.db")
    own = tasks.create("alice", "私人实验", None, None, "Asia/Shanghai", "m", "k")
    with pytest.raises(TaskNotFound):
        tasks.delete_by_title("bob", "私人实验", "delete", "d")
    assert tasks.list("alice") == [own]
    assert tasks.list("bob") == []


def test_flexible_task_http_create_and_user_initiated_query_use_structured_records(tmp_path):
    db = tmp_path / "kairos.db"
    app = create_app(str(db), owner_id="local")
    with TestClient(app) as client:
        saved = client.post("/api/v1/flexible-tasks", headers={"Idempotency-Key": "task-create"}, json={
            "title": "操作系统实验", "deadline": "2026-09-27", "deadline_precision": "date",
            "timezone": "Asia/Shanghai", "source_message_id": "msg-add",
        })
        assert saved.status_code == 200
        assert saved.json()["deadline_precision"] == "date"
        queried = client.post("/api/v1/flexible-task-queries", headers={"Idempotency-Key": "task-query"}, json={
            "conversation_id": "conversation-1", "source_message_id": "msg-query", "query_scope": "all",
        })
    assert queried.status_code == 200
    assert queried.json()["items"][0]["task_id"] == saved.json()["task_id"]
    assert queried.json()["source_message_id"] == "msg-query"
