"""Event facts separate timing from user disposition."""

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal


@dataclass(frozen=True)
class RecurrenceRule:
    frequency: Literal["daily", "weekly"]
    starts_on: date
    ends_on: date | None
    weekdays: tuple[int, ...]
    local_start: time
    local_end: time
    end_day_offset: int
    gap_policy: Literal["skip"] | None = None
    fold_policy: Literal["earlier", "later"] | None = None

    def __post_init__(self) -> None:
        if self.frequency not in ("daily", "weekly"):
            raise ValueError("unsupported recurrence frequency")
        if (self.ends_on is not None and self.ends_on < self.starts_on) or self.end_day_offset not in (0, 1):
            raise ValueError("invalid recurrence range or day offset")
        if self.frequency == "weekly" and (not self.weekdays or any(day < 1 or day > 7 for day in self.weekdays)):
            raise ValueError("weekly recurrence needs ISO weekdays")
        if self.gap_policy not in (None, "skip") or self.fold_policy not in (None, "earlier", "later"):
            raise ValueError("invalid DST policy")


@dataclass(frozen=True)
class EventSeries:
    event_id: str
    owner_id: str
    version: int
    title: str
    location: str | None
    timezone: str
    start_at: datetime
    end_at: datetime
    recurrence: RecurrenceRule | None = None


@dataclass(frozen=True)
class Occurrence:
    occurrence_id: str
    event_id: str
    owner_id: str
    original_slot: str
    start_at: datetime
    end_at: datetime
    title: str
    location: str | None
    version: int
    schedule_revision: int
    disposition: Literal["scheduled", "excused", "cancelled", "missed"]
