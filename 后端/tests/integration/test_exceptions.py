import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from kairos.adapters.sqlite import SQLiteStore
from kairos.domain.occurrence_ids import make_occurrence_id
from kairos.main import create_app
from kairos.settings import Settings


class FrozenClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 28, 6, 30, tzinfo=UTC)


def add_weekly_class(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO events (
                id, title, location, notes, timezone, start_at, end_at, version,
                created_at, updated_at, event_type, recurrence_start_date,
                local_start_time, local_end_time, end_day_offset, frequency,
                weekdays_json, until_date, gap_policy, fold_policy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "course",
                "数据结构课",
                "教三 201",
                None,
                "Asia/Shanghai",
                "2026-09-21T06:00:00+00:00",
                "2026-09-21T07:40:00+00:00",
                1,
                "2026-09-20T00:00:00+00:00",
                "2026-09-20T00:00:00+00:00",
                "recurring",
                "2026-09-21",
                "14:00:00",
                "15:40:00",
                0,
                "weekly",
                json.dumps([1]),
                None,
                None,
                None,
            ),
        )


async def request_json(
    app: object, method: str, path: str, json_body: dict[str, str] | None = None
) -> tuple[int, dict[str, object]]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, json=json_body)
    return response.status_code, response.json() if response.content else {}


def test_excusing_one_occurrence_leaves_next_week_unchanged(tmp_path: Path) -> None:
    database_path = tmp_path / "events.sqlite3"
    store = SQLiteStore(database_path)
    store.initialize()
    add_weekly_class(database_path)
    app = create_app(Settings(db_path=database_path), clock=FrozenClock())
    occurrence_id = make_occurrence_id("course", "2026-09-28T14:00:00;fold=0")

    status, saved = asyncio.run(
        request_json(
            app,
            "POST",
            f"/api/v1/occurrences/{occurrence_id}/exceptions",
            {"exception_type": "excused", "idempotency_key": "leave-this-week"},
        )
    )

    assert status == 200
    assert saved["status"] == "excused"
    state_status, state = asyncio.run(request_json(app, "GET", "/api/v1/state"))
    assert state_status == 200
    assert state["active_occurrences"] == []
    assert state["next_transition_at"] == "2026-10-05T06:00:00Z"

    list_status, occurrences = asyncio.run(
        request_json(
            app,
            "GET",
            "/api/v1/occurrences?from=2026-09-28T00:00:00Z&to=2026-10-06T00:00:00Z",
        )
    )
    assert list_status == 200
    assert [(item["start_at"], item["status"]) for item in occurrences["items"]] == [
        ("2026-09-28T06:00:00Z", "excused"),
        ("2026-10-05T06:00:00Z", "scheduled"),
    ]


def test_exception_retry_is_idempotent_and_different_exception_conflicts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "events.sqlite3"
    SQLiteStore(database_path).initialize()
    add_weekly_class(database_path)
    app = create_app(Settings(db_path=database_path), clock=FrozenClock())
    occurrence_id = make_occurrence_id("course", "2026-09-28T14:00:00;fold=0")
    path = f"/api/v1/occurrences/{occurrence_id}/exceptions"
    payload = {"exception_type": "excused", "idempotency_key": "leave-this-week"}

    first_status, first = asyncio.run(request_json(app, "POST", path, payload))
    retry_status, retry = asyncio.run(request_json(app, "POST", path, payload))
    conflict_status, conflict = asyncio.run(
        request_json(
            app,
            "POST",
            path,
            {"exception_type": "cancelled", "idempotency_key": "cancel-this-week"},
        )
    )

    assert first_status == retry_status == 200
    assert first == retry
    assert conflict_status == 409
    assert conflict["detail"]["code"] == "EXCEPTION_CONFLICT"


def test_exception_rejects_unknown_instance(tmp_path: Path) -> None:
    database_path = tmp_path / "events.sqlite3"
    SQLiteStore(database_path).initialize()
    app = create_app(Settings(db_path=database_path), clock=FrozenClock())

    status, body = asyncio.run(
        request_json(
            app,
            "POST",
            "/api/v1/occurrences/not-a-valid-instance/exceptions",
            {"exception_type": "excused", "idempotency_key": "bad-id"},
        )
    )

    assert status == 404
    assert body["detail"]["code"] == "OCCURRENCE_NOT_FOUND"


def test_series_update_guards_exceptions_and_delete_cascades(tmp_path: Path) -> None:
    database_path = tmp_path / "events.sqlite3"
    SQLiteStore(database_path).initialize()
    add_weekly_class(database_path)
    app = create_app(Settings(db_path=database_path), clock=FrozenClock())
    occurrence_id = make_occurrence_id("course", "2026-09-28T14:00:00;fold=0")
    exception_path = f"/api/v1/occurrences/{occurrence_id}/exceptions"
    exception_status, _ = asyncio.run(
        request_json(
            app,
            "POST",
            exception_path,
            {"exception_type": "excused", "idempotency_key": "one-instance"},
        )
    )
    assert exception_status == 200

    schedule_status, schedule_body = asyncio.run(
        request_json(
            app,
            "PATCH",
            "/api/v1/events/course",
            {"version": 1, "timezone": "Asia/Tokyo"},
        )
    )
    assert schedule_status == 409
    assert schedule_body["detail"]["code"] == "SERIES_HAS_EXCEPTIONS"

    title_status, _ = asyncio.run(
        request_json(
            app,
            "PATCH",
            "/api/v1/events/course",
            {"version": 1, "title": "数据结构课（改名）"},
        )
    )
    assert title_status == 204
    occurrences_status, occurrences = asyncio.run(
        request_json(
            app,
            "GET",
            "/api/v1/occurrences?from=2026-09-28T00:00:00Z&to=2026-09-29T00:00:00Z",
        )
    )
    assert occurrences_status == 200
    assert occurrences["items"][0]["title"] == "数据结构课（改名）"
    assert occurrences["items"][0]["status"] == "excused"

    stale_status, _ = asyncio.run(request_json(app, "DELETE", "/api/v1/events/course?version=1"))
    deleted_status, _ = asyncio.run(request_json(app, "DELETE", "/api/v1/events/course?version=2"))
    assert stale_status == 409
    assert deleted_status == 204
    with sqlite3.connect(database_path) as connection:
        event_count = connection.execute("SELECT count(*) FROM events").fetchone()[0]
        exception_count = connection.execute("SELECT count(*) FROM event_exceptions").fetchone()[0]
    assert event_count == 0
    assert exception_count == 0
