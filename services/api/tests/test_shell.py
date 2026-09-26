from pathlib import Path

from fastapi.testclient import TestClient

from kairos.main import create_app


def test_health_uses_new_temporary_database(tmp_path: Path) -> None:
    database = tmp_path / "new" / "kairos.sqlite3"
    with TestClient(create_app(str(database))) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert database.is_file()


def test_state_and_event_routes_are_implemented(tmp_path: Path) -> None:
    with TestClient(create_app(str(tmp_path / "new.sqlite3"))) as client:
        state = client.get("/api/v1/state")
        events = client.get("/api/v1/events")
    assert state.status_code == 200
    assert state.json()["due_reminders"] == []
    assert events.status_code == 200
    assert events.json() == {"items": [], "next_cursor": None}


def test_occurrence_query_returns_only_requested_window(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta
    from kairos.adapters.clock import SystemClock
    from kairos.adapters.persistence.sqlite import SqliteRepository
    from kairos.application.drafts import DraftService
    from kairos.application.draft_commit import DraftCommitService
    from kairos.domain.drafts import Candidate

    now = datetime.now(UTC)
    path = tmp_path / "events.sqlite3"
    repo = SqliteRepository(path)
    draft = DraftService(repo, SystemClock()).create("local", [Candidate("class", "软件工程课", "教学楼A",
        now + timedelta(hours=2), now + timedelta(hours=3), "UTC")], source_message_id="msg")
    DraftCommitService(repo, SystemClock()).commit("local", draft.draft_id, draft.revision, ["class"],
        draft.confirmation_digest, "commit")
    with TestClient(create_app(str(path), owner_id="local")) as client:
        page = client.get("/api/v1/occurrences", params={"from": now.isoformat(), "to": (now + timedelta(days=1)).isoformat()})
        assert page.status_code == 200
        assert len(page.json()["items"]) == 1
        assert page.json()["items"][0]["title"] == "软件工程课"
        assert page.json()["items"][0]["temporal_phase"] == "upcoming"
    with TestClient(create_app(str(tmp_path / "shell.sqlite3"))) as client:
        response = client.get("/api/v1/weather", params={"location_id": "home"})
    assert response.status_code == 501
    payload = response.json()
    assert payload["code"] == "NOT_IMPLEMENTED"
    assert payload["request_id"]
    assert "message" in payload
