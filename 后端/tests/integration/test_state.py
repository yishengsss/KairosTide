import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from kairos.adapters.sqlite import SQLiteStore
from kairos.main import create_app
from kairos.settings import Settings


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def add_event(database_path: Path, event_id: str, start: datetime, end: datetime) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO events (
                id, title, location, notes, timezone, start_at, end_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event_id,
                None,
                None,
                "UTC",
                start.isoformat(),
                end.isoformat(),
                start.isoformat(),
                start.isoformat(),
            ),
        )


async def get_json(app: object, path: str) -> tuple[int, dict[str, object]]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
    return response.status_code, response.json()


def test_state_returns_active_event_and_next_boundary(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 6, tzinfo=UTC)
    database_path = tmp_path / "events.sqlite3"
    store = SQLiteStore(database_path)
    store.initialize()
    add_event(database_path, "class", now, now + timedelta(minutes=90))
    app = create_app(Settings(db_path=database_path), clock=FrozenClock(now))

    status, body = asyncio.run(get_json(app, "/api/v1/state"))

    assert status == 200
    assert [event["event_id"] for event in body["active_occurrences"]] == ["class"]
    assert body["active_occurrences"][0]["status"] == "active"
    assert body["next_transition_at"] == "2026-09-25T07:30:00Z"


def test_occurrence_query_includes_event_that_started_before_window(tmp_path: Path) -> None:
    now = datetime(2026, 9, 25, 6, tzinfo=UTC)
    database_path = tmp_path / "events.sqlite3"
    store = SQLiteStore(database_path)
    store.initialize()
    add_event(database_path, "overnight", now - timedelta(hours=1), now + timedelta(hours=1))
    app = create_app(Settings(db_path=database_path), clock=FrozenClock(now))

    status, body = asyncio.run(
        get_json(app, "/api/v1/occurrences?from=2026-09-25T05:30:00Z&to=2026-09-25T08:00:00Z")
    )

    assert status == 200
    assert [event["event_id"] for event in body["items"]] == ["overnight"]


def test_state_does_not_create_uninitialized_database(tmp_path: Path) -> None:
    database_path = tmp_path / "missing.sqlite3"
    app = create_app(Settings(db_path=database_path))

    status, body = asyncio.run(get_json(app, "/api/v1/state"))

    assert status == 503
    assert body["detail"]["code"] == "DATABASE_NOT_INITIALIZED"
    assert not database_path.exists()


def test_occurrence_query_rejects_naive_or_reversed_range(tmp_path: Path) -> None:
    database_path = tmp_path / "events.sqlite3"
    store = SQLiteStore(database_path)
    store.initialize()
    app = create_app(Settings(db_path=database_path))

    naive_path = "/api/v1/occurrences?from=2026-09-25T06:00:00&to=2026-09-25T07:00:00Z"
    reversed_path = "/api/v1/occurrences?from=2026-09-25T07:00:00Z&to=2026-09-25T06:00:00Z"
    naive_status, _ = asyncio.run(get_json(app, naive_path))
    reversed_status, _ = asyncio.run(get_json(app, reversed_path))

    assert naive_status == 422
    assert reversed_status == 422


def test_occurrence_query_rejects_range_over_90_days(tmp_path: Path) -> None:
    database_path = tmp_path / "events.sqlite3"
    store = SQLiteStore(database_path)
    store.initialize()
    app = create_app(Settings(db_path=database_path))
    path = "/api/v1/occurrences?from=2026-09-25T06:00:00Z&to=2026-12-25T06:00:00Z"

    status, body = asyncio.run(get_json(app, path))

    assert status == 422
    assert body["detail"]["code"] == "RANGE_TOO_LARGE"
