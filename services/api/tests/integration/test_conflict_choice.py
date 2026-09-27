from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from kairos.adapters.persistence.sqlite import SqliteRepository
from kairos.application.draft_commit import DraftCommitService
from kairos.application.drafts import DraftService
from kairos.domain.drafts import Candidate
from kairos.main import create_app


class Clock:
    def __init__(self, instant):
        self.instant = instant

    def now(self):
        return self.instant


def add_event(repo, clock, title, starts_at, source):
    drafts = DraftService(repo, clock)
    draft = drafts.create("local", [Candidate(source, title, None, starts_at,
        starts_at + timedelta(hours=1), "Asia/Shanghai")], source_message_id=source)
    return DraftCommitService(repo, clock).commit("local", draft.draft_id, draft.revision,
        [source], draft.confirmation_digest, f"commit-{source}")


def test_explicit_conflict_choice_marks_only_current_unselected_members_missed(tmp_path):
    now = datetime(2026, 9, 26, 6, 55, tzinfo=UTC)
    clock = Clock(now)
    db = tmp_path / "kairos.db"
    repo = SqliteRepository(db)
    add_event(repo, clock, "课程 A", now, "a")
    add_event(repo, clock, "课程 B", now + timedelta(hours=2), "b")
    b = repo.list_occurrences("local", now, now + timedelta(days=1))[1]
    repo.reschedule_single("local", b.occurrence_id, b.version, now, now + timedelta(hours=1))
    client = TestClient(create_app(str(db), clock=clock, owner_id="local"))
    state = client.get("/api/v1/state").json()
    conflict = state["conflicts"][0]
    selected_id = conflict["member_ids"][0]
    payload = {"member_ids": conflict["member_ids"], "selected_id": selected_id,
               "snapshot_revision": state["state_revision"], "source_action_id": "choose-a"}

    response = client.post("/api/v1/conflict-decisions", headers={"Idempotency-Key": "choice-1"}, json=payload)

    assert response.status_code == 200
    result = response.json()
    assert result["selected_id"] == selected_id
    assert {item["occurrence_id"] for item in result["affected_occurrences"]} == set(conflict["member_ids"])
    dispositions = {item.occurrence_id: item.disposition
        for item in repo.list_occurrences("local", now, now + timedelta(days=1))}
    assert dispositions[selected_id] == "scheduled"
    assert {disposition for identity, disposition in dispositions.items() if identity != selected_id} == {"missed"}
    assert client.get("/api/v1/state").json()["conflicts"] == []
    retry = client.post("/api/v1/conflict-decisions", headers={"Idempotency-Key": "choice-1"}, json=payload)
    assert retry.status_code == 200
    assert retry.json() == result


def test_conflict_choice_rejects_stale_snapshot_without_marking_anything_missed(tmp_path):
    now = datetime(2026, 9, 26, 6, 55, tzinfo=UTC)
    clock = Clock(now)
    db = tmp_path / "kairos.db"
    repo = SqliteRepository(db)
    add_event(repo, clock, "课程 A", now, "a")
    add_event(repo, clock, "课程 B", now + timedelta(hours=2), "b")
    b = repo.list_occurrences("local", now, now + timedelta(days=1))[1]
    repo.reschedule_single("local", b.occurrence_id, b.version, now, now + timedelta(hours=1))
    client = TestClient(create_app(str(db), clock=clock, owner_id="local"))
    old_state = client.get("/api/v1/state").json()
    add_event(repo, clock, "课程 C", now + timedelta(hours=4), "c")
    c = repo.list_occurrences("local", now, now + timedelta(days=1))[-1]
    repo.reschedule_single("local", c.occurrence_id, c.version, now, now + timedelta(hours=1))
    conflict = old_state["conflicts"][0]
    payload = {"member_ids": conflict["member_ids"], "selected_id": conflict["member_ids"][0],
               "snapshot_revision": old_state["state_revision"], "source_action_id": "stale-choice"}

    response = client.post("/api/v1/conflict-decisions", headers={"Idempotency-Key": "stale"}, json=payload)

    assert response.status_code == 409
    assert all(item.disposition == "scheduled" for item in repo.list_occurrences("local", now, now + timedelta(days=1)))
