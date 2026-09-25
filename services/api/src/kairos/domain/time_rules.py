"""Timezone-aware half-open interval rules, adapted from reviewed legacy scheduling."""

from datetime import UTC, datetime


def _valid(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None or end.astimezone(UTC) <= start.astimezone(UTC):
        raise ValueError("interval needs aware start before end")


def is_active(start_at: datetime, end_at: datetime, now: datetime) -> bool:
    _valid(start_at, end_at)
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    return start_at.astimezone(UTC) <= now.astimezone(UTC) < end_at.astimezone(UTC)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    _valid(a_start, a_end)
    _valid(b_start, b_end)
    return a_start.astimezone(UTC) < b_end.astimezone(UTC) and b_start.astimezone(UTC) < a_end.astimezone(UTC)
