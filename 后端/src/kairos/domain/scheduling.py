from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import RecurrenceNeedsDSTPolicy
from .models import Event, Occurrence
from .occurrence_ids import make_occurrence_id


def is_active(start_at: datetime, end_at: datetime, now: datetime) -> bool:
    """Return whether now falls in the half-open event interval [start, end)."""
    if start_at.tzinfo is None or end_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("event times and current time must include a timezone")
    if end_at <= start_at:
        raise ValueError("event end must be later than event start")
    return start_at <= now < end_at


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Return whether two half-open intervals overlap."""
    if any(value.tzinfo is None for value in (a_start, a_end, b_start, b_end)):
        raise ValueError("event times must include a timezone")
    if a_end <= a_start or b_end <= b_start:
        raise ValueError("event end must be later than event start")
    return a_start < b_end and b_start < a_end


def _resolve_local(
    value: datetime, zone: ZoneInfo, gap_policy: str | None, fold_policy: str | None
) -> datetime | None:
    candidates: list[datetime] = []
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(zone)
        if round_trip.replace(tzinfo=None) == value and all(
            previous.utcoffset() != candidate.utcoffset() for previous in candidates
        ):
            candidates.append(candidate)

    if not candidates:
        if gap_policy == "skip":
            return None
        raise RecurrenceNeedsDSTPolicy("nonexistent local time requires an explicit skip policy")
    if len(candidates) == 1:
        return candidates[0]
    if fold_policy not in {"earlier", "later"}:
        raise RecurrenceNeedsDSTPolicy("ambiguous local time requires earlier or later policy")
    candidates.sort(key=lambda candidate: candidate.astimezone(UTC))
    return candidates[0] if fold_policy == "earlier" else candidates[-1]


def _single_occurrence(event: Event) -> Occurrence:
    key = event.start_at.astimezone(UTC).isoformat()
    return Occurrence(
        occurrence_id=make_occurrence_id(event.id, key),
        event_id=event.id,
        title=event.title,
        location=event.location,
        start_at=event.start_at.astimezone(UTC),
        end_at=event.end_at.astimezone(UTC),
        status="scheduled",
        occurrence_key=key,
        version=event.version,
    )


def expand_event(event: Event, window_start: datetime, window_end: datetime) -> list[Occurrence]:
    """Expand one event into UTC occurrences that overlap the half-open query window."""
    if window_start.tzinfo is None or window_end.tzinfo is None or window_start >= window_end:
        raise ValueError("query window must be a valid timezone-aware interval")
    window_start = window_start.astimezone(UTC)
    window_end = window_end.astimezone(UTC)

    if event.event_type == "single":
        occurrence = _single_occurrence(event)
        is_in_window = overlaps(occurrence.start_at, occurrence.end_at, window_start, window_end)
        return [occurrence] if is_in_window else []

    if (
        event.recurrence_start_date is None
        or event.local_start_time is None
        or event.local_end_time is None
        or event.frequency not in {"daily", "weekly"}
    ):
        raise ValueError("recurring event is missing a supported recurrence rule")
    try:
        zone = ZoneInfo(event.timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("recurring event has an invalid IANA timezone") from error

    first_local_date = window_start.astimezone(zone).date() - timedelta(days=1)
    last_local_date = window_end.astimezone(zone).date() + timedelta(days=1)
    current_date = max(event.recurrence_start_date, first_local_date)
    occurrences: list[Occurrence] = []
    while current_date <= last_local_date:
        scheduled = event.frequency == "daily" or current_date.isoweekday() in event.weekdays
        if scheduled and (event.until_date is None or current_date <= event.until_date):
            local_start = datetime.combine(current_date, event.local_start_time)
            end_date = current_date + timedelta(days=event.end_day_offset)
            local_end = datetime.combine(end_date, event.local_end_time)
            resolved_start = _resolve_local(local_start, zone, event.gap_policy, event.fold_policy)
            resolved_end = _resolve_local(local_end, zone, event.gap_policy, event.fold_policy)
            if resolved_start is not None and resolved_end is not None:
                start_at = resolved_start.astimezone(UTC)
                end_at = resolved_end.astimezone(UTC)
                if end_at <= start_at:
                    raise ValueError("recurring event end must be later than event start")
                fold = resolved_start.fold
                key = f"{local_start.isoformat(timespec='seconds')};fold={fold}"
                occurrence = Occurrence(
                    occurrence_id=make_occurrence_id(event.id, key),
                    event_id=event.id,
                    title=event.title,
                    location=event.location,
                    start_at=start_at,
                    end_at=end_at,
                    status="scheduled",
                    occurrence_key=key,
                    version=event.version,
                )
                if overlaps(start_at, end_at, window_start, window_end):
                    occurrences.append(occurrence)
        current_date += timedelta(days=1)
    return occurrences


def find_conflicts(
    candidates: list[Occurrence], existing: list[Occurrence]
) -> list[tuple[str, str]]:
    conflicts: set[tuple[str, str]] = set()
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            if overlaps(left.start_at, left.end_at, right.start_at, right.end_at):
                first_id, second_id = sorted((left.occurrence_id, right.occurrence_id))
                conflicts.add((first_id, second_id))
        for right in existing:
            if overlaps(left.start_at, left.end_at, right.start_at, right.end_at):
                first_id, second_id = sorted((left.occurrence_id, right.occurrence_id))
                conflicts.add((first_id, second_id))
    return sorted(conflicts)
