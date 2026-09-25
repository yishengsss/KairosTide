"""Local calendar expansion with explicit DST policy and immutable slot keys."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .events import EventSeries
from .time_rules import overlaps


class NeedsDSTPolicy(ValueError):
    pass


@dataclass(frozen=True)
class Slot:
    original_slot: str
    start_at: datetime
    end_at: datetime


def resolve_local(value: datetime, zone: ZoneInfo, gap_policy: str | None, fold_policy: str | None) -> datetime | None:
    choices: list[datetime] = []
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone, fold=fold)
        if candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == value and all(
            previous.utcoffset() != candidate.utcoffset() for previous in choices
        ):
            choices.append(candidate)
    if not choices:
        if gap_policy == "skip":
            return None
        raise NeedsDSTPolicy("nonexistent local time needs explicit skip")
    if len(choices) == 1:
        return choices[0]
    if fold_policy not in ("earlier", "later"):
        raise NeedsDSTPolicy("ambiguous local time needs earlier or later")
    choices.sort(key=lambda choice: choice.astimezone(UTC))
    return choices[0] if fold_policy == "earlier" else choices[-1]


def expand_slots(event: EventSeries, window_start: datetime, window_end: datetime) -> list[Slot]:
    if window_start.tzinfo is None or window_end.tzinfo is None or window_end <= window_start:
        raise ValueError("query window must be an aware positive interval")
    if window_end - window_start > timedelta(days=370):
        raise ValueError("query window too large; page the query")
    if event.recurrence is None:
        return [Slot("single", event.start_at.astimezone(UTC), event.end_at.astimezone(UTC))] if overlaps(
            event.start_at, event.end_at, window_start, window_end
        ) else []
    rule = event.recurrence
    if rule.ends_on is None:
        raise ValueError("recurrence end date requires clarification")
    try:
        zone = ZoneInfo(event.timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("invalid IANA timezone") from error
    first = max(rule.starts_on, window_start.astimezone(zone).date() - timedelta(days=1))
    last = min(rule.ends_on, window_end.astimezone(zone).date() + timedelta(days=1))
    slots: list[Slot] = []
    day = first
    while day <= last:
        if rule.frequency == "daily" or day.isoweekday() in rule.weekdays:
            local_start = datetime.combine(day, rule.local_start)
            local_end = datetime.combine(day + timedelta(days=rule.end_day_offset), rule.local_end)
            start = resolve_local(local_start, zone, rule.gap_policy, rule.fold_policy)
            end = resolve_local(local_end, zone, rule.gap_policy, rule.fold_policy)
            if start is not None and end is not None:
                start_at, end_at = start.astimezone(UTC), end.astimezone(UTC)
                if end_at <= start_at:
                    raise ValueError("recurring local end must follow start")
                if overlaps(start_at, end_at, window_start, window_end):
                    slots.append(Slot(day.isoformat(), start_at, end_at))
        day += timedelta(days=1)
    return slots
