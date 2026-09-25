from datetime import UTC, date, datetime, time, timedelta

import pytest

from kairos.domain.errors import RecurrenceNeedsDSTPolicy
from kairos.domain.models import Event
from kairos.domain.occurrence_ids import make_occurrence_id, parse_occurrence_id
from kairos.domain.scheduling import expand_event, overlaps


def recurring_event(
    *,
    event_id: str = "course",
    timezone_name: str = "Asia/Shanghai",
    first_date: date = date(2026, 9, 21),
    start_time: time = time(14),
    end_time: time = time(15, 40),
    frequency: str = "weekly",
    weekdays: tuple[int, ...] = (1,),
    until_date: date | None = None,
    end_day_offset: int = 0,
    gap_policy: str | None = None,
    fold_policy: str | None = None,
) -> Event:
    start = datetime.combine(first_date, start_time, tzinfo=UTC)
    end = datetime.combine(first_date, end_time, tzinfo=UTC)
    if end_day_offset:
        end += timedelta(days=end_day_offset)
    return Event(
        id=event_id,
        title="数据结构课",
        location="教三 201",
        notes=None,
        timezone=timezone_name,
        start_at=start,
        end_at=end,
        version=1,
        event_type="recurring",
        recurrence_start_date=first_date,
        local_start_time=start_time,
        local_end_time=end_time,
        end_day_offset=end_day_offset,
        frequency=frequency,
        weekdays=weekdays,
        until_date=until_date,
        gap_policy=gap_policy,
        fold_policy=fold_policy,
    )


def test_adjacent_events_do_not_conflict() -> None:
    a = datetime(2026, 9, 25, 6, tzinfo=UTC)
    b = a + timedelta(hours=1)
    c = b + timedelta(hours=1)

    assert not overlaps(a, b, b, c)
    assert overlaps(a, c, b, c)


def test_weekly_recurrence_expands_in_its_original_timezone() -> None:
    event = recurring_event()

    occurrences = expand_event(
        event,
        datetime(2026, 9, 20, tzinfo=UTC),
        datetime(2026, 10, 6, tzinfo=UTC),
    )

    assert [item.start_at.isoformat() for item in occurrences] == [
        "2026-09-21T06:00:00+00:00",
        "2026-09-28T06:00:00+00:00",
        "2026-10-05T06:00:00+00:00",
    ]
    assert occurrences[0].occurrence_id != occurrences[1].occurrence_id


def test_until_date_includes_its_local_date() -> None:
    event = recurring_event(until_date=date(2026, 9, 28))

    occurrences = expand_event(
        event,
        datetime(2026, 9, 20, tzinfo=UTC),
        datetime(2026, 10, 6, tzinfo=UTC),
    )

    assert [item.start_at.date().isoformat() for item in occurrences] == [
        "2026-09-21",
        "2026-09-28",
    ]


def test_nonexistent_dst_time_requires_an_explicit_policy() -> None:
    event = recurring_event(
        timezone_name="America/New_York",
        first_date=date(2026, 3, 8),
        start_time=time(2, 30),
        end_time=time(3, 30),
        frequency="daily",
        weekdays=(),
    )

    with pytest.raises(RecurrenceNeedsDSTPolicy):
        expand_event(
            event,
            datetime(2026, 3, 8, tzinfo=UTC),
            datetime(2026, 3, 9, tzinfo=UTC),
        )


def test_ambiguous_dst_time_uses_only_an_explicit_fold_policy() -> None:
    event = recurring_event(
        timezone_name="America/New_York",
        first_date=date(2026, 11, 1),
        start_time=time(1, 30),
        end_time=time(2, 30),
        frequency="daily",
        weekdays=(),
    )

    with pytest.raises(RecurrenceNeedsDSTPolicy):
        expand_event(
            event,
            datetime(2026, 11, 1, tzinfo=UTC),
            datetime(2026, 11, 2, tzinfo=UTC),
        )


def test_occurrence_id_round_trips_series_and_local_instance_key() -> None:
    key = "2026-11-01T01:30:00;fold=1"

    occurrence_id = make_occurrence_id("series-123", key)

    assert parse_occurrence_id(occurrence_id) == ("series-123", key)
