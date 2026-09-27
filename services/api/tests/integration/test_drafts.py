import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta

import pytest

from kairos.adapters.persistence.sqlite import SqliteRepository
from kairos.application.draft_commit import ConflictReviewRequired, DraftCommitService
from kairos.application.drafts import DraftService
from kairos.domain.drafts import Candidate, DraftNotReady, IdempotencyConflict, RevisionConflict
from kairos.domain.events import RecurrenceRule


NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


def candidate(index: int, *, title: str | None = None) -> Candidate:
    start = NOW + timedelta(days=1, hours=index)
    return Candidate(f"candidate-{index}", title or f"课程{index}", None, start, start + timedelta(hours=1), "Asia/Shanghai")


def services(tmp_path):
    repo = SqliteRepository(tmp_path / "kairos.db")
    clock = FixedClock()
    return repo, DraftService(repo, clock), DraftCommitService(repo, clock)


def test_ready_draft_is_not_a_formal_event_until_all_candidates_confirmed(tmp_path) -> None:
    repo, drafts, commits = services(tmp_path)
    draft = drafts.create("local", [candidate(1), candidate(2), candidate(3)], source_message_id="message-1")
    assert draft.status == "ready"
    assert len(draft.candidates) == 3
    assert repo.list_events("local") == []
    assert repo.list_occurrences("local", NOW, NOW + timedelta(days=3)) == []

    result = commits.commit("local", draft.draft_id, draft.revision,
                            ["candidate-1", "candidate-2", "candidate-3"], draft.confirmation_digest, "request-1")
    assert len(result.event_ids) == 3
    assert len(repo.list_events("local")) == 3
    assert commits.commit("local", draft.draft_id, draft.revision,
                          ["candidate-1", "candidate-2", "candidate-3"], draft.confirmation_digest, "request-1") == result
    assert len(repo.list_events("local")) == 3
    with pytest.raises(IdempotencyConflict):
        commits.commit("local", draft.draft_id, draft.revision,
                       ["candidate-1"], draft.confirmation_digest, "request-1")
    with pytest.raises(RevisionConflict):
        commits.commit("local", draft.draft_id, draft.revision,
                       ["candidate-1", "candidate-2", "candidate-3"], draft.confirmation_digest, "request-2")


def test_second_insert_failure_rolls_back_events_draft_and_idempotency(tmp_path) -> None:
    repo, drafts, commits = services(tmp_path)
    draft = drafts.create("local", [candidate(1), candidate(2), candidate(3)], source_message_id="message-1")
    with sqlite3.connect(repo.path) as connection:
        connection.execute("CREATE TRIGGER fail_middle BEFORE INSERT ON events WHEN NEW.title = '课程2' BEGIN SELECT RAISE(FAIL, 'injected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        commits.commit("local", draft.draft_id, draft.revision,
                       ["candidate-1", "candidate-2", "candidate-3"], draft.confirmation_digest, "retryable-key")
    assert repo.list_events("local") == []
    assert repo.get_draft("local", draft.draft_id).status == "ready"
    with sqlite3.connect(repo.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM operation_audit WHERE owner_id = 'local'").fetchone()[0] == 0
    with sqlite3.connect(repo.path) as connection:
        connection.execute("DROP TRIGGER fail_middle")
    result = commits.commit("local", draft.draft_id, draft.revision,
                            ["candidate-1", "candidate-2", "candidate-3"], draft.confirmation_digest, "retryable-key")
    assert len(result.event_ids) == 3
    with sqlite3.connect(repo.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM operation_audit WHERE owner_id = 'local' AND operation = 'draft_commit'").fetchone()[0] == 1


def test_candidate_edits_are_targeted_and_missing_time_is_never_guessed(tmp_path) -> None:
    repo, drafts, commits = services(tmp_path)
    incomplete = Candidate("unknown", "下周二上课", None, None, None, "Asia/Shanghai")
    draft = drafts.create("local", [incomplete, candidate(1), candidate(2)], source_message_id="message-2")
    assert draft.status == "needs_clarification"
    assert draft.candidates[0].start_at is None
    with pytest.raises(DraftNotReady):
        commits.commit("local", draft.draft_id, draft.revision,
                       [item.candidate_id for item in draft.candidates], draft.confirmation_digest, "incomplete-key")
    updated = drafts.update_candidate("local", draft.draft_id, draft.revision, "unknown",
                                      start_at=NOW + timedelta(days=3), end_at=NOW + timedelta(days=3, hours=1))
    assert updated.revision == 2
    assert [item.candidate_id for item in updated.candidates] == ["unknown", "candidate-1", "candidate-2"]
    assert updated.status == "ready"
    assert updated.confirmation_digest != draft.confirmation_digest
    with pytest.raises(RevisionConflict):
        drafts.update_candidate("local", draft.draft_id, draft.revision, "unknown", title="覆盖")


def test_candidate_removal_requires_id_and_addition_preserves_existing_candidates(tmp_path) -> None:
    repo, drafts, _ = services(tmp_path)
    initial = drafts.create("local", [candidate(1), candidate(2)], source_message_id="many")
    added = drafts.add_candidate("local", initial.draft_id, initial.revision, candidate(3))
    assert [item.candidate_id for item in added.candidates] == ["candidate-1", "candidate-2", "candidate-3"]
    with pytest.raises(ValueError):
        drafts.add_candidate("local", added.draft_id, added.revision, candidate(3))
    removed = drafts.remove_candidate("local", added.draft_id, added.revision, "candidate-2")
    assert [item.candidate_id for item in removed.candidates] == ["candidate-1", "candidate-3"]
    with pytest.raises(KeyError):
        drafts.remove_candidate("local", removed.draft_id, removed.revision, "candidate-2")


def test_new_conflict_requires_review_at_commit_without_marking_missed(tmp_path) -> None:
    repo, drafts, commits = services(tmp_path)
    first = drafts.create("local", [candidate(1)], source_message_id="one")
    pending = drafts.create("local", [candidate(1, title="另一门课")], source_message_id="two")
    commits.commit("local", first.draft_id, first.revision, ["candidate-1"], first.confirmation_digest, "first-key")
    with pytest.raises(ConflictReviewRequired) as caught:
        commits.commit("local", pending.draft_id, pending.revision, ["candidate-1"], pending.confirmation_digest, "second-key")
    assert repo.get_draft("local", pending.draft_id).status == "ready"
    assert len(repo.list_events("local")) == 1
    result = commits.commit("local", pending.draft_id, pending.revision,
                            ["candidate-1"], pending.confirmation_digest, "second-key",
                            conflict_acceptance=caught.value.acceptance_token)
    assert len(result.event_ids) == 1
    occurrences = repo.list_occurrences("local", NOW, NOW + timedelta(days=3))
    assert len(occurrences) == 2
    assert {item.disposition for item in occurrences} == {"scheduled"}


def test_recurrence_without_end_date_stays_unconfirmed(tmp_path) -> None:
    repo, drafts, commits = services(tmp_path)
    open_ended = RecurrenceRule("weekly", date(2026, 9, 28), None, (1,), time(14), time(15), 0)
    proposed = candidate(1)
    draft = drafts.create("local", [Candidate(proposed.candidate_id, proposed.title, None,
                                               proposed.start_at, proposed.end_at, proposed.timezone, open_ended)],
                          source_message_id="no-range")
    assert draft.status == "needs_clarification"
    assert draft.candidates[0].missing_fields == ("recurrence.ends_on",)
    with pytest.raises(DraftNotReady):
        commits.commit("local", draft.draft_id, draft.revision, [proposed.candidate_id],
                       draft.confirmation_digest, "no-range-key")
    assert repo.list_events("local") == []


def test_conflict_acceptance_expires_when_another_event_joins(tmp_path) -> None:
    repo, drafts, commits = services(tmp_path)
    first = drafts.create("local", [candidate(1)], source_message_id="one")
    second = drafts.create("local", [candidate(1, title="课程乙")], source_message_id="two")
    third = drafts.create("local", [candidate(1, title="课程丙")], source_message_id="three")
    commits.commit("local", first.draft_id, 1, ["candidate-1"], first.confirmation_digest, "first")
    with pytest.raises(ConflictReviewRequired) as initial:
        commits.commit("local", second.draft_id, 1, ["candidate-1"], second.confirmation_digest, "second")
    with pytest.raises(ConflictReviewRequired) as third_review:
        commits.commit("local", third.draft_id, 1, ["candidate-1"], third.confirmation_digest, "third")
    commits.commit("local", third.draft_id, 1, ["candidate-1"], third.confirmation_digest,
                   "third", conflict_acceptance=third_review.value.acceptance_token)
    with pytest.raises(ConflictReviewRequired) as refreshed:
        commits.commit("local", second.draft_id, 1, ["candidate-1"], second.confirmation_digest,
                       "second", conflict_acceptance=initial.value.acceptance_token)
    assert refreshed.value.acceptance_token != initial.value.acceptance_token
    assert len(repo.list_events("local")) == 2


def test_competing_confirmations_create_only_one_batch(tmp_path) -> None:
    repo, drafts, commits = services(tmp_path)
    draft = drafts.create("local", [candidate(1), candidate(2), candidate(3)], source_message_id="parallel")

    def attempt(key: str):
        try:
            return commits.commit("local", draft.draft_id, 1,
                                  ["candidate-1", "candidate-2", "candidate-3"], draft.confirmation_digest, key)
        except RevisionConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("parallel-a", "parallel-b")))
    assert sum(hasattr(item, "event_ids") for item in results) == 1
    assert sum(isinstance(item, RevisionConflict) for item in results) == 1
    assert len(repo.list_events("local")) == 3


def test_invalid_iana_timezone_is_rejected_before_draft_is_saved(tmp_path) -> None:
    repo, drafts, _ = services(tmp_path)
    proposed = candidate(1)
    with pytest.raises(ValueError, match="IANA timezone"):
        drafts.create("local", [Candidate(proposed.candidate_id, proposed.title, None,
                                           proposed.start_at, proposed.end_at, "Mars/Olympus")],
                      source_message_id="invalid-zone")
    assert repo.list_events("local") == []
