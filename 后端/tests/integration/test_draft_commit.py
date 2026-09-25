import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from kairos.adapters.sqlite import SQLiteStore
from kairos.application.drafts import DraftCommands
from kairos.application.planning import EventCandidate, PlannerResult
from kairos.main import create_app
from kairos.settings import Settings


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 25, 15, 55, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


class ClarifyingPlanner:
    def __init__(self) -> None:
        self.references: list[datetime] = []

    def parse(
        self,
        text: str,
        timezone: str,
        reference_now: datetime,
        answers: dict[str, str] | None = None,
    ) -> PlannerResult:
        self.references.append(reference_now)
        if not answers or "time" not in answers:
            return PlannerResult(status="needs_clarification", questions=["几点开始和结束？"])
        return PlannerResult(
            status="ready",
            candidates=[
                EventCandidate(
                    title="复诊",
                    timezone=timezone,
                    start_at=datetime.fromisoformat("2026-09-26T14:00:00+08:00"),
                    end_at=datetime.fromisoformat("2026-09-26T15:00:00+08:00"),
                    location="医院",
                )
            ],
        )


async def request_json(
    app: object, method: str, path: str, body: dict[str, object] | None = None
) -> tuple[int, dict[str, object]]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, json=body)
    return response.status_code, response.json()


def make_app(database_path: Path) -> tuple[object, MutableClock, ClarifyingPlanner]:
    clock = MutableClock()
    planner = ClarifyingPlanner()
    store = SQLiteStore(database_path)
    store.initialize()
    app = create_app(Settings(db_path=database_path), clock=clock)
    app.state.planner = planner
    app.state.draft_commands = DraftCommands(store, planner, clock)
    return app, clock, planner


def test_draft_clarification_and_commit_is_persistent_idempotent_and_atomic(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "kairos.sqlite3"
    app, clock, planner = make_app(database_path)

    draft_status, draft = asyncio.run(
        request_json(
            app,
            "POST",
            "/api/v1/drafts",
            {"text": "周六去复诊", "timezone": "Asia/Shanghai"},
        )
    )
    draft_id = str(draft["draft_id"])
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    assert draft_status == 201
    assert draft["status"] == "needs_clarification"

    # Cross local midnight. The clarification must keep the original reference instant.
    clock.current = datetime(2026, 9, 25, 16, 5, tzinfo=UTC)
    clarification_status, clarified = asyncio.run(
        request_json(
            app,
            "POST",
            f"/api/v1/drafts/{draft_id}/clarifications",
            {"revision": 1, "answers": {"time": "下午两点到三点"}},
        )
    )
    assert clarification_status == 200
    assert clarified["status"] == "ready"
    assert clarified["revision"] == 2
    assert planner.references[0] == planner.references[1]

    commit_body = {"revision": 2, "idempotency_key": "save-this-draft"}
    first_status, first = asyncio.run(
        request_json(app, "POST", f"/api/v1/drafts/{draft_id}/commit", commit_body)
    )
    retry_status, retry = asyncio.run(
        request_json(app, "POST", f"/api/v1/drafts/{draft_id}/commit", commit_body)
    )
    assert first_status == retry_status == 200
    assert first == retry
    assert first["event_ids"]
    with sqlite3.connect(database_path) as connection:
        event_count = connection.execute("SELECT count(*) FROM events").fetchone()[0]
        stored_status = connection.execute(
            "SELECT status FROM planning_drafts WHERE id = ?", (draft_id,)
        ).fetchone()[0]
    assert event_count == 1
    assert stored_status == "committed"


def test_draft_expiry_and_stale_revision_are_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "kairos.sqlite3"
    app, clock, _planner = make_app(database_path)
    draft_status, draft = asyncio.run(
        request_json(
            app,
            "POST",
            "/api/v1/drafts",
            {"text": "周六复诊", "timezone": "Asia/Shanghai"},
        )
    )
    assert draft_status == 201
    path = f"/api/v1/drafts/{draft['draft_id']}/clarifications"
    stale_status, stale = asyncio.run(
        request_json(app, "POST", path, {"revision": 9, "answers": {"time": "14 点"}})
    )
    assert stale_status == 409
    assert stale["detail"]["code"] == "DRAFT_VERSION_CONFLICT"

    clock.current = datetime(2026, 9, 25, 16, 26, tzinfo=UTC)
    expired_status, expired = asyncio.run(
        request_json(app, "POST", path, {"revision": 1, "answers": {"time": "14 点"}})
    )
    assert expired_status == 410
    assert expired["detail"]["code"] == "DRAFT_EXPIRED"


def test_batch_failure_rolls_back_events_draft_and_idempotency(tmp_path: Path) -> None:
    database_path = tmp_path / "kairos.sqlite3"
    app, clock, _planner = make_app(database_path)
    status, draft = asyncio.run(
        request_json(
            app,
            "POST",
            "/api/v1/drafts",
            {"text": "两场会议", "timezone": "Asia/Shanghai"},
        )
    )
    assert status == 201
    draft_id = str(draft["draft_id"])
    _clarify_status, ready = asyncio.run(
        request_json(
            app,
            "POST",
            f"/api/v1/drafts/{draft_id}/clarifications",
            {"revision": 1, "answers": {"time": "下午两点"}},
        )
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_bad_candidate BEFORE INSERT ON events
               WHEN NEW.title = '故意失败'
               BEGIN SELECT RAISE(ABORT, 'test failure'); END"""
        )

    from kairos.adapters.sqlite import SQLiteStore

    store = SQLiteStore(database_path)
    candidates = [
        {
            "title": "正常会议",
            "timezone": "Asia/Shanghai",
            "start_at": "2026-09-26T14:00:00+08:00",
            "end_at": "2026-09-26T15:00:00+08:00",
        },
        {
            "title": "故意失败",
            "timezone": "Asia/Shanghai",
            "start_at": "2026-09-26T16:00:00+08:00",
            "end_at": "2026-09-26T17:00:00+08:00",
        },
    ]
    try:
        store.commit_draft(
            draft_id, int(ready["revision"]), "rollback-key", candidates, clock.now()
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("the injected database failure should abort the batch")

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT status FROM planning_drafts WHERE id = ?", (draft_id,)
            ).fetchone()[0]
            == "ready"
        )
        assert connection.execute("SELECT count(*) FROM planning_idempotency").fetchone()[0] == 0


def test_simultaneous_commit_requests_share_one_event_batch(tmp_path: Path) -> None:
    database_path = tmp_path / "kairos.sqlite3"
    app, clock, _planner = make_app(database_path)
    status, draft = asyncio.run(
        request_json(
            app,
            "POST",
            "/api/v1/drafts",
            {"text": "复诊", "timezone": "Asia/Shanghai"},
        )
    )
    assert status == 201
    draft_id = str(draft["draft_id"])
    _clarify_status, ready = asyncio.run(
        request_json(
            app,
            "POST",
            f"/api/v1/drafts/{draft_id}/clarifications",
            {"revision": 1, "answers": {"time": "下午两点"}},
        )
    )
    from kairos.adapters.sqlite import SQLiteStore

    store = SQLiteStore(database_path)
    candidates = [
        {
            "title": "复诊",
            "timezone": "Asia/Shanghai",
            "start_at": "2026-09-26T14:00:00+08:00",
            "end_at": "2026-09-26T15:00:00+08:00",
        }
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _index: store.commit_draft(
                    draft_id, int(ready["revision"]), "race-key", candidates, clock.now()
                ),
                range(2),
            )
        )
    assert results[0] == results[1]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 1


def test_reusing_commit_key_for_another_draft_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "kairos.sqlite3"
    app, _clock, _planner = make_app(database_path)
    drafts: list[dict[str, object]] = []
    for text in ("第一次复诊", "第二次复诊"):
        status, draft = asyncio.run(
            request_json(
                app,
                "POST",
                "/api/v1/drafts",
                {"text": text, "timezone": "Asia/Shanghai"},
            )
        )
        assert status == 201
        draft_id = str(draft["draft_id"])
        _status, ready = asyncio.run(
            request_json(
                app,
                "POST",
                f"/api/v1/drafts/{draft_id}/clarifications",
                {"revision": 1, "answers": {"time": "下午两点"}},
            )
        )
        drafts.append({"draft_id": draft_id, "revision": ready["revision"]})

    first_status, _first = asyncio.run(
        request_json(
            app,
            "POST",
            f"/api/v1/drafts/{drafts[0]['draft_id']}/commit",
            {"revision": drafts[0]["revision"], "idempotency_key": "shared-key"},
        )
    )
    second_status, second = asyncio.run(
        request_json(
            app,
            "POST",
            f"/api/v1/drafts/{drafts[1]['draft_id']}/commit",
            {"revision": drafts[1]["revision"], "idempotency_key": "shared-key"},
        )
    )
    assert first_status == 200
    assert second_status == 409
    assert second["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 1
