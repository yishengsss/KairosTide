from dataclasses import dataclass
from datetime import date, datetime, time


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    location: str | None
    notes: str | None
    timezone: str
    start_at: datetime
    end_at: datetime
    version: int
    event_type: str = "single"
    recurrence_start_date: date | None = None
    local_start_time: time | None = None
    local_end_time: time | None = None
    end_day_offset: int = 0
    frequency: str | None = None
    weekdays: tuple[int, ...] = ()
    until_date: date | None = None
    gap_policy: str | None = None
    fold_policy: str | None = None


@dataclass(frozen=True)
class Occurrence:
    occurrence_id: str
    event_id: str
    title: str
    location: str | None
    start_at: datetime
    end_at: datetime
    status: str
    occurrence_key: str | None = None
    version: int = 1


@dataclass(frozen=True)
class EventException:
    event_id: str
    occurrence_key: str
    exception_type: str


@dataclass(frozen=True)
class StateSnapshot:
    server_now: datetime
    active_occurrences: list[Occurrence]
    next_transition_at: datetime | None
