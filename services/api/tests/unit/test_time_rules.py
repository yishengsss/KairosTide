from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from kairos.domain.events import EventSeries, RecurrenceRule
from kairos.domain.recurrence import NeedsDSTPolicy, expand_slots
from kairos.domain.time_rules import is_active, overlaps


def test_half_open_intervals_allow_adjacent_events_and_exclude_end() -> None:
    start = datetime(2026, 9, 26, 13, tzinfo=UTC)
    middle = start + timedelta(hours=1)
    end = middle + timedelta(hours=1)
    assert is_active(start, middle, start)
    assert not is_active(start, middle, middle)
    assert not overlaps(start, middle, middle, end)
    assert overlaps(start, end, middle, end)


def test_cross_midnight_weekly_slots_keep_local_day_and_utc_instants() -> None:
    event = EventSeries(
        event_id="course", owner_id="local", version=1, title="夜课", location=None,
        timezone="Asia/Shanghai", start_at=datetime(2026, 9, 21, 23, 30, tzinfo=UTC),
        end_at=datetime(2026, 9, 22, 1, tzinfo=UTC),
        recurrence=RecurrenceRule("weekly", date(2026, 9, 21), date(2026, 9, 28), (1,),
                                  time(23, 30), time(1), 1),
    )
    slots = expand_slots(event, datetime(2026, 9, 20, tzinfo=UTC), datetime(2026, 9, 30, tzinfo=UTC))
    assert [(slot.original_slot, slot.start_at.isoformat(), slot.end_at.isoformat()) for slot in slots] == [
        ("2026-09-21", "2026-09-21T15:30:00+00:00", "2026-09-21T17:00:00+00:00"),
        ("2026-09-28", "2026-09-28T15:30:00+00:00", "2026-09-28T17:00:00+00:00"),
    ]


def test_dst_gap_requires_explicit_skip_and_fold_requires_choice() -> None:
    base = dict(event_id="dst", owner_id="local", version=1, title="课", location=None,
                timezone="America/New_York", start_at=datetime(2026, 3, 8, tzinfo=UTC),
                end_at=datetime(2026, 3, 8, 1, tzinfo=UTC))
    gap = EventSeries(**base, recurrence=RecurrenceRule("daily", date(2026, 3, 8), date(2026, 3, 8), (),
                                                       time(2, 30), time(3, 30), 0))
    with pytest.raises(NeedsDSTPolicy):
        expand_slots(gap, datetime(2026, 3, 8, tzinfo=UTC), datetime(2026, 3, 9, tzinfo=UTC))
    skipped = EventSeries(**base, recurrence=RecurrenceRule("daily", date(2026, 3, 8), date(2026, 3, 8), (),
                                                           time(2, 30), time(3, 30), 0, "skip"))
    assert expand_slots(skipped, datetime(2026, 3, 8, tzinfo=UTC), datetime(2026, 3, 9, tzinfo=UTC)) == []
    fold = EventSeries(**base, recurrence=RecurrenceRule("daily", date(2026, 11, 1), date(2026, 11, 1), (),
                                                        time(1, 30), time(2, 30), 0))
    with pytest.raises(NeedsDSTPolicy):
        expand_slots(fold, datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 2, tzinfo=UTC))
    earlier = EventSeries(**base, recurrence=RecurrenceRule("daily", date(2026, 11, 1), date(2026, 11, 1), (),
                                                           time(1, 30), time(2, 30), 0, None, "earlier"))
    later = EventSeries(**base, recurrence=RecurrenceRule("daily", date(2026, 11, 1), date(2026, 11, 1), (),
                                                         time(1, 30), time(2, 30), 0, None, "later"))
    window_start = datetime(2026, 11, 1, tzinfo=UTC)
    window_end = datetime(2026, 11, 2, tzinfo=UTC)
    assert expand_slots(earlier, window_start, window_end)[0].start_at.isoformat() == "2026-11-01T05:30:00+00:00"
    assert expand_slots(later, window_start, window_end)[0].start_at.isoformat() == "2026-11-01T06:30:00+00:00"


def test_half_open_rules_compare_instants_across_dst_fold() -> None:
    zone = ZoneInfo("America/New_York")
    start = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    end = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    assert is_active(start, end, datetime(2026, 11, 1, 1, 15, tzinfo=zone, fold=1))
    assert not is_active(start, end, end)
