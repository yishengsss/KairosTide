import asyncio
from datetime import UTC, datetime
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from kairos.application.planning import EventCandidate, PlannerResult
from kairos.main import create_app
from kairos.settings import Settings


class FrozenClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 2, tzinfo=UTC)


class FixedPlanner:
    def __init__(self, result: PlannerResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, datetime, dict[str, str] | None]] = []

    def parse(
        self,
        text: str,
        timezone: str,
        reference_now: datetime,
        answers: dict[str, str] | None = None,
    ) -> PlannerResult:
        self.calls.append((text, timezone, reference_now, answers))
        return self.result


async def post_preview(app: object, body: dict[str, object]) -> tuple[int, dict[str, object]]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/planning/preview", json=body)
    return response.status_code, response.json()


def test_preview_returns_candidate_without_creating_event_data(tmp_path: Path) -> None:
    database_path = tmp_path / "never-created.sqlite3"
    app = create_app(Settings(db_path=database_path), clock=FrozenClock())
    planner = FixedPlanner(
        PlannerResult(
            status="ready",
            candidates=[
                EventCandidate(
                    title="项目讨论",
                    timezone="Asia/Shanghai",
                    start_at=datetime.fromisoformat("2026-09-26T14:00:00+08:00"),
                    end_at=datetime.fromisoformat("2026-09-26T15:00:00+08:00"),
                )
            ],
        )
    )
    app.state.planner = planner

    status, body = asyncio.run(
        post_preview(
            app,
            {"text": "明天下午两点开会一小时", "timezone": "Asia/Shanghai"},
        )
    )

    assert status == 200
    assert body["status"] == "ready"
    assert body["candidates"][0]["title"] == "项目讨论"
    assert body["reference_now"] == "2026-09-25T02:00:00Z"
    assert len(planner.calls) == 1
    assert not database_path.exists()


def test_preview_rejects_bad_timezone_before_calling_model(tmp_path: Path) -> None:
    app = create_app(Settings(db_path=tmp_path / "never-created.sqlite3"), clock=FrozenClock())
    planner = FixedPlanner(PlannerResult(status="needs_clarification", questions=["哪一天？"]))
    app.state.planner = planner

    status, body = asyncio.run(post_preview(app, {"text": "周五上课", "timezone": "Not/AZone"}))

    assert status == 422
    assert body["detail"]["code"] == "INVALID_TIMEZONE"
    assert planner.calls == []


def test_preview_without_model_configuration_returns_service_unavailable(tmp_path: Path) -> None:
    app = create_app(Settings(db_path=tmp_path / "never-created.sqlite3"), clock=FrozenClock())

    status, body = asyncio.run(
        post_preview(app, {"text": "明天下午两点开会", "timezone": "Asia/Shanghai"})
    )

    assert status == 503
    assert body["detail"]["code"] == "MODEL_UNAVAILABLE"
