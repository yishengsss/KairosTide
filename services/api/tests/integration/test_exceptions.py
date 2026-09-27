from datetime import UTC, date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient

from kairos.adapters.persistence.sqlite import SqliteRepository
from kairos.application.draft_commit import DraftCommitService
from kairos.application.drafts import DraftService
from kairos.application.occurrence_commands import OccurrenceService
from kairos.domain.drafts import RevisionConflict
from kairos.domain.events import RecurrenceRule
from kairos.domain.drafts import Candidate
from kairos.main import create_app


NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


def test_excusing_one_weekly_occurrence_preserves_series_and_following_week(tmp_path) -> None:
    path = tmp_path / "kairos.db"
    repo = SqliteRepository(path)
    clock = FixedClock()
    recurrence = RecurrenceRule("weekly", date(2026, 9, 21), date(2026, 9, 28), (1,), time(14), time(15, 40), 0)
    candidate = Candidate("course", "软件工程", "教学楼A", datetime(2026, 9, 21, 6, tzinfo=UTC),
                          datetime(2026, 9, 21, 7, 40, tzinfo=UTC), "Asia/Shanghai", recurrence)
    draft = DraftService(repo, clock).create("local", [candidate], source_message_id="course-message")
    DraftCommitService(repo, clock).commit("local", draft.draft_id, draft.revision, ["course"], draft.confirmation_digest, "save-course")
    window_end = NOW + timedelta(days=16)
    before = repo.list_occurrences("local", NOW, window_end)
    assert len(before) == 2
    assert before[0].occurrence_id != before[1].occurrence_id
    changed = OccurrenceService(repo, clock).set_exception("local", before[0].occurrence_id, "excused", before[0].version,
                                                          "leave-request", "leave-key")
    assert changed.disposition == "excused"
    reopened = SqliteRepository(path)
    after = reopened.list_occurrences("local", NOW, window_end)
    assert [item.occurrence_id for item in after] == [item.occurrence_id for item in before]
    assert [item.disposition for item in after] == ["excused", "scheduled"]
    assert len(reopened.list_events("local")) == 1
    assert OccurrenceService(reopened, clock).set_exception("local", before[0].occurrence_id,
                                                             "excused", before[0].version, "leave-request", "leave-key") == changed


def test_single_occurrence_reschedule_keeps_identity_and_increments_schedule_revision(tmp_path) -> None:
    repo = SqliteRepository(tmp_path / "kairos.db")
    clock = FixedClock()
    candidate = Candidate("meeting", "项目会", None, NOW + timedelta(days=1), NOW + timedelta(days=1, hours=1), "Asia/Shanghai")
    draft = DraftService(repo, clock).create("local", [candidate], source_message_id="meeting-message")
    DraftCommitService(repo, clock).commit("local", draft.draft_id, draft.revision, ["meeting"], draft.confirmation_digest, "save-meeting")
    before = repo.list_occurrences("local", NOW, NOW + timedelta(days=4))[0]
    moved = OccurrenceService(repo, clock).reschedule_single("local", before.occurrence_id, before.version,
                                                              before.start_at + timedelta(hours=2), before.end_at + timedelta(hours=2))
    assert moved.occurrence_id == before.occurrence_id
    assert moved.original_slot == before.original_slot
    assert moved.schedule_revision == before.schedule_revision + 1
    assert moved.version == before.version + 1
    with pytest.raises(RevisionConflict):
        OccurrenceService(repo, clock).set_exception("local", before.occurrence_id, "cancelled", before.version,
                                                  "stale-action", "stale-key")


def test_owner_cannot_read_or_modify_another_owners_draft_and_occurrence(tmp_path) -> None:
    repo = SqliteRepository(tmp_path / "kairos.db")
    clock = FixedClock()
    draft = DraftService(repo, clock).create("alice", [Candidate("one", "课", None,
        NOW + timedelta(days=1), NOW + timedelta(days=1, hours=1), "Asia/Shanghai")], source_message_id="alice-message")
    assert repo.get_draft("bob", draft.draft_id) is None
    with pytest.raises(KeyError):
        DraftCommitService(repo, clock).commit("bob", draft.draft_id, 1, ["one"], draft.confirmation_digest, "bob-key")
    DraftCommitService(repo, clock).commit("alice", draft.draft_id, 1, ["one"], draft.confirmation_digest, "alice-key")
    occurrence = repo.list_occurrences("alice", NOW, NOW + timedelta(days=2))[0]
    assert repo.list_occurrences("bob", NOW, NOW + timedelta(days=2)) == []
    with pytest.raises(KeyError):
        OccurrenceService(repo, clock).set_exception("bob", occurrence.occurrence_id, "excused", 1, "bob-action", "bob-key")


def test_exception_retry_returns_original_result_after_later_reschedule(tmp_path) -> None:
    repo = SqliteRepository(tmp_path / "kairos.db")
    clock = FixedClock()
    proposed = Candidate("one", "课", None, NOW + timedelta(days=1), NOW + timedelta(days=1, hours=1), "Asia/Shanghai")
    draft = DraftService(repo, clock).create("local", [proposed], source_message_id="one-message")
    DraftCommitService(repo, clock).commit("local", draft.draft_id, 1, ["one"], draft.confirmation_digest, "create-key")
    before = repo.list_occurrences("local", NOW, NOW + timedelta(days=2))[0]
    command = OccurrenceService(repo, clock)
    first = command.set_exception("local", before.occurrence_id, "excused", before.version, "action", "exception-key")
    moved = command.reschedule_single("local", first.occurrence_id, first.version,
                                      first.start_at + timedelta(hours=2), first.end_at + timedelta(hours=2))
    assert moved.version == first.version + 1
    assert command.set_exception("local", before.occurrence_id, "excused", before.version, "action", "exception-key") == first


def test_http_exception_changes_only_the_requested_occurrence(tmp_path):
    repo = SqliteRepository(tmp_path / "kairos.db")
    clock = FixedClock()
    recurrence = RecurrenceRule("weekly", date(2026, 9, 21), date(2026, 9, 28), (1,),
                                time(14), time(15), 0)
    candidate = Candidate("weekly", "软件工程课", "教学楼A", datetime(2026, 9, 21, 6, tzinfo=UTC),
                          datetime(2026, 9, 21, 7, tzinfo=UTC), "Asia/Shanghai", recurrence)
    draft = DraftService(repo, clock).create("local", [candidate], source_message_id="class")
    DraftCommitService(repo, clock).commit("local", draft.draft_id, 1, ["weekly"], draft.confirmation_digest, "create")
    occurrences = repo.list_occurrences("local", NOW, NOW + timedelta(days=20))
    client = TestClient(create_app(str(repo.path), clock=clock, owner_id="local"))

    response = client.post(f"/api/v1/occurrences/{occurrences[0].occurrence_id}/exceptions",
        headers={"Idempotency-Key": "leave"}, json={"type": "excused", "expected_version": occurrences[0].version,
        "source_action_id": "leave-this-time"})

    assert response.status_code == 200
    assert response.json()["disposition"] == "excused"
    assert response.json()["event_id"] == occurrences[0].event_id
    remaining = repo.list_occurrences("local", NOW, NOW + timedelta(days=20))
    assert [item.disposition for item in remaining] == ["excused", "scheduled"]
