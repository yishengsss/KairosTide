from datetime import UTC, datetime, timedelta

from kairos.application.state import StateService
from kairos.domain.events import Occurrence


class Clock:
    def __init__(self, instant):
        self.instant = instant

    def now(self):
        return self.instant


class Repository:
    def __init__(self, occurrences):
        self.occurrences = occurrences

    def list_occurrences(self, _owner, _start, _end):
        return self.occurrences


def occurrence(identity, start, end, version=1, disposition="scheduled"):
    return Occurrence(identity, f"event-{identity}", "owner", "slot", start, end,
                      identity, None, version, 1, disposition)


def test_snapshot_groups_all_overlapping_active_occurrences_and_revisions_membership():
    now = datetime(2026, 9, 26, 14, 0, tzinfo=UTC)
    a = occurrence("a", now - timedelta(minutes=1), now + timedelta(hours=1))
    b = occurrence("b", now, now + timedelta(minutes=30))
    c = occurrence("c", now - timedelta(minutes=10), now + timedelta(hours=2))
    service = StateService(Repository([a, b, c]), Clock(now))

    snapshot = service.snapshot("owner")

    assert snapshot.conflicts == (("a", "b", "c"),)
    assert isinstance(snapshot.state_revision, int)
    assert snapshot.state_revision < 2**53
    assert snapshot.state_revision != 1


def test_conflict_snapshot_revision_changes_when_member_schedule_changes():
    now = datetime(2026, 9, 26, 14, 0, tzinfo=UTC)
    a = occurrence("a", now - timedelta(minutes=1), now + timedelta(hours=1))
    b = occurrence("b", now, now + timedelta(minutes=30))

    first = StateService(Repository([a, b]), Clock(now)).snapshot("owner")
    changed = occurrence("b", now, now + timedelta(minutes=31), version=2)
    second = StateService(Repository([a, changed]), Clock(now)).snapshot("owner")

    assert first.state_revision != second.state_revision


def test_non_overlapping_active_occurrences_do_not_create_conflict_groups():
    now = datetime(2026, 9, 26, 14, 0, tzinfo=UTC)
    a = occurrence("a", now - timedelta(minutes=1), now + timedelta(minutes=1))
    b = occurrence("b", now + timedelta(minutes=2), now + timedelta(minutes=30))

    snapshot = StateService(Repository([a, b]), Clock(now)).snapshot("owner")

    assert snapshot.conflicts == ()
