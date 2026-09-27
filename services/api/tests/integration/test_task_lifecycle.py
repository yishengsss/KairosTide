"""Persisted, owner-scoped lifecycle changes for flexible tasks."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kairos.adapters.persistence.sqlite import SqliteRepository
from kairos.application.tasks import FlexibleTaskService
from kairos.main import create_app


def _create(client, key="create"):
    response = client.post("/api/v1/flexible-tasks", headers={"Idempotency-Key": key}, json={
        "title": "操作系统实验", "deadline": None, "deadline_precision": None,
        "timezone": "Asia/Shanghai", "source_message_id": "message-1",
    })
    assert response.status_code == 200
    return response.json()


def _transition(client, task_id, status, version, key):
    return client.post(f"/api/v1/flexible-tasks/{task_id}/lifecycle",
        headers={"Idempotency-Key": key}, json={"status": status, "expected_version": version})


def test_created_task_defaults_to_planned_and_transition_sequence_persists(tmp_path):
    path = tmp_path / "kairos.db"
    with TestClient(create_app(str(path), owner_id="alice")) as client:
        original = _create(client)
        assert original["lifecycle_status"] == "planned"
        assert original["version"] == 1
        task_id = original["task_id"]
        active = _transition(client, task_id, "active", 1, "accept")
        assert active.status_code == 200
        assert active.json() == {**original, "version": 2, "lifecycle_status": "active"}
        paused = _transition(client, task_id, "planned", 2, "pause")
        assert paused.status_code == 200
        assert paused.json()["version"] == 3
        assert paused.json()["lifecycle_status"] == "planned"
        accepted_again = _transition(client, task_id, "active", 3, "accept-again")
        assert accepted_again.status_code == 200
        completed = _transition(client, task_id, "completed", 4, "complete")
        assert completed.status_code == 200
        assert completed.json()["version"] == 5
        assert completed.json()["lifecycle_status"] == "completed"
    reopened = FlexibleTaskService(SqliteRepository(path)).list("alice")
    assert len(reopened) == 1
    assert reopened[0].lifecycle_status == "completed"
    assert reopened[0].version == 5


@pytest.mark.parametrize("initial,target", [
    ("planned", "planned"), ("planned", "completed"),
    ("active", "active"), ("completed", "planned"), ("completed", "active"),
])
def test_invalid_transition_does_not_mutate_task(tmp_path, initial, target):
    path = tmp_path / "kairos.db"
    with TestClient(create_app(str(path), owner_id="alice")) as client:
        original = _create(client)
        if initial == "active":
            current = _transition(client, original["task_id"], "active", 1, "accept").json()
        elif initial == "completed":
            active = _transition(client, original["task_id"], "active", 1, "accept").json()
            current = _transition(client, original["task_id"], "completed", 2, "complete").json()
        else:
            current = original
        response = _transition(client, original["task_id"], target, current["version"], "invalid")
        assert response.status_code == 409
        listed = client.get("/api/v1/flexible-tasks").json()["items"]
        assert listed == [current]


def test_stale_version_and_foreign_or_unknown_ids_do_not_mutate(tmp_path):
    path = tmp_path / "kairos.db"
    with TestClient(create_app(str(path), owner_id="alice")) as alice:
        original = _create(alice)
        accepted = _transition(alice, original["task_id"], "active", 1, "accept")
        assert accepted.status_code == 200
        stale = _transition(alice, original["task_id"], "planned", 1, "stale")
        assert stale.status_code == 409
        missing = _transition(alice, "task_missing", "active", 1, "missing")
        assert missing.status_code == 404
    with TestClient(create_app(str(path), owner_id="bob")) as bob:
        foreign = _transition(bob, original["task_id"], "planned", 2, "foreign")
        assert foreign.status_code == 404
    assert FlexibleTaskService(SqliteRepository(path)).list("alice")[0].lifecycle_status == "active"


def test_idempotent_replay_returns_original_response_after_later_transition(tmp_path):
    path = tmp_path / "kairos.db"
    with TestClient(create_app(str(path), owner_id="alice")) as client:
        original = _create(client)
        first = _transition(client, original["task_id"], "active", 1, "accept")
        assert first.status_code == 200
        paused = _transition(client, original["task_id"], "planned", 2, "pause")
        assert paused.status_code == 200
        replay = _transition(client, original["task_id"], "active", 1, "accept")
        assert replay.status_code == 200
        assert replay.json() == first.json()
        reused = _transition(client, original["task_id"], "completed", 2, "accept")
        assert reused.status_code == 409
        assert client.get("/api/v1/flexible-tasks").json()["items"] == [paused.json()]


def test_existing_database_rows_migrate_to_planned(tmp_path):
    path = tmp_path / "kairos.db"
    migration_dir = Path(__file__).resolve().parents[2] / "migrations"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)")
        for name in ("001_initial.sql", "002_flexible_tasks.sql", "003_rigid_changes.sql"):
            connection.executescript((migration_dir / name).read_text())
            connection.execute("INSERT INTO schema_migrations(version) VALUES (?)", (name,))
        connection.execute("""INSERT INTO flexible_tasks
            (task_id, owner_id, version, title, deadline_value, deadline_precision, timezone, source_message_id)
            VALUES ('task_old', 'alice', 7, '旧任务', NULL, NULL, 'Asia/Shanghai', NULL)""")
    records = FlexibleTaskService(SqliteRepository(path)).list("alice")
    assert len(records) == 1
    assert records[0].lifecycle_status == "planned"
    assert records[0].version == 7
