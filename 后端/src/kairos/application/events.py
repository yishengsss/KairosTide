import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kairos.domain.errors import (
    EventNotFound,
    EventVersionConflict,
    ExceptionConflict,
    RecurrenceNeedsDSTPolicy,
    SeriesHasExceptions,
)
from kairos.domain.models import Event, EventException, Occurrence
from kairos.domain.occurrence_ids import parse_occurrence_id
from kairos.domain.scheduling import expand_event


def _updated_value[T](fields: dict[str, object], key: str, default: T) -> T:
    return cast(T, fields.get(key, default))


class EventWriter(Protocol):
    def get_event(self, event_id: str) -> Event | None: ...

    def update_event(self, event_id: str, version: int, fields: dict[str, object]) -> Event: ...

    def delete_event(self, event_id: str, version: int) -> None: ...

    def add_exception(
        self,
        event_id: str,
        occurrence_key: str,
        exception_type: str,
        idempotency_key: str,
        created_at: datetime,
    ) -> EventException: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class OccurrenceExceptionConflict(Exception):
    """Raised when a different exception already exists for this event instance."""


class OccurrenceDoesNotExist(Exception):
    """Raised when an occurrence identifier does not match a stored event."""


class RecurrenceNeedsConfirmation(Exception):
    """Raised when the instance needs an explicit daylight-saving policy."""


class EventUpdateNotFound(Exception):
    """Raised when the requested event does not exist."""


class EventUpdateConflict(Exception):
    """Raised when an update conflicts with the current event version."""


class EventSeriesHasExceptions(Exception):
    """Raised when a schedule change would invalidate saved instance exceptions."""


class InvalidEventUpdate(Exception):
    """Raised when updated event fields do not form a valid schedule."""


class EventCommands:
    def __init__(self, writer: EventWriter, clock: Clock) -> None:
        self._writer = writer
        self._clock = clock

    def add_exception(
        self,
        occurrence_id: str,
        exception_type: str,
        idempotency_key: str,
    ) -> Occurrence:
        if exception_type not in {"excused", "cancelled"}:
            raise ValueError("exception type must be excused or cancelled")
        if not idempotency_key.strip() or len(idempotency_key) > 128:
            raise ValueError("idempotency key must contain 1 to 128 characters")
        try:
            event_id, occurrence_key = parse_occurrence_id(occurrence_id)
        except ValueError as error:
            raise OccurrenceDoesNotExist from error
        event = self._writer.get_event(event_id)
        if event is None:
            raise OccurrenceDoesNotExist
        try:
            local_date = date.fromisoformat(occurrence_key[:10])
        except ValueError as error:
            raise OccurrenceDoesNotExist from error
        range_start = datetime.combine(local_date - timedelta(days=1), datetime.min.time(), UTC)
        range_end = datetime.combine(local_date + timedelta(days=2), datetime.min.time(), UTC)
        try:
            occurrences = expand_event(event, range_start, range_end)
        except RecurrenceNeedsDSTPolicy as error:
            raise RecurrenceNeedsConfirmation from error
        occurrence = next(
            (item for item in occurrences if item.occurrence_id == occurrence_id),
            None,
        )
        if occurrence is None:
            raise OccurrenceDoesNotExist
        try:
            self._writer.add_exception(
                event_id,
                occurrence_key,
                exception_type,
                idempotency_key,
                self._clock.now(),
            )
        except ExceptionConflict as error:
            raise OccurrenceExceptionConflict from error
        return replace(occurrence, status=exception_type)

    def update_event(self, event_id: str, version: int, fields: dict[str, object]) -> Event:
        allowed = {
            "title",
            "location",
            "notes",
            "timezone",
            "start_at",
            "end_at",
            "event_type",
            "recurrence_start_date",
            "local_start_time",
            "local_end_time",
            "end_day_offset",
            "frequency",
            "weekdays",
            "until_date",
            "gap_policy",
            "fold_policy",
        }
        if version < 1 or not fields or set(fields) - allowed:
            raise InvalidEventUpdate
        current = self._writer.get_event(event_id)
        if current is None:
            raise EventUpdateNotFound
        updates = dict(fields)
        candidate_values = {name: value for name, value in updates.items() if name != "weekdays"}
        if "weekdays" in updates:
            weekdays = updates.pop("weekdays")
            if not isinstance(weekdays, list) or any(day not in range(1, 8) for day in weekdays):
                raise InvalidEventUpdate
            if len(weekdays) != len(set(weekdays)):
                raise InvalidEventUpdate
            candidate_values["weekdays"] = tuple(weekdays)
            updates["weekdays_json"] = json.dumps(weekdays)
        if "title" in updates:
            title = updates["title"]
            if not isinstance(title, str) or not title.strip():
                raise InvalidEventUpdate
            updates["title"] = title.strip()
            candidate_values["title"] = title.strip()
        timezone_name = candidate_values.get("timezone", current.timezone)
        if not isinstance(timezone_name, str):
            raise InvalidEventUpdate
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise InvalidEventUpdate from error
        candidate_values["timezone"] = timezone_name
        candidate = replace(
            current,
            title=_updated_value(candidate_values, "title", current.title),
            location=_updated_value(candidate_values, "location", current.location),
            notes=_updated_value(candidate_values, "notes", current.notes),
            timezone=_updated_value(candidate_values, "timezone", current.timezone),
            start_at=_updated_value(candidate_values, "start_at", current.start_at),
            end_at=_updated_value(candidate_values, "end_at", current.end_at),
            event_type=_updated_value(candidate_values, "event_type", current.event_type),
            recurrence_start_date=_updated_value(
                candidate_values, "recurrence_start_date", current.recurrence_start_date
            ),
            local_start_time=_updated_value(
                candidate_values, "local_start_time", current.local_start_time
            ),
            local_end_time=_updated_value(
                candidate_values, "local_end_time", current.local_end_time
            ),
            end_day_offset=_updated_value(
                candidate_values, "end_day_offset", current.end_day_offset
            ),
            frequency=_updated_value(candidate_values, "frequency", current.frequency),
            weekdays=_updated_value(candidate_values, "weekdays", current.weekdays),
            until_date=_updated_value(candidate_values, "until_date", current.until_date),
            gap_policy=_updated_value(candidate_values, "gap_policy", current.gap_policy),
            fold_policy=_updated_value(candidate_values, "fold_policy", current.fold_policy),
        )
        if candidate.event_type == "single":
            if candidate.start_at.tzinfo is None or candidate.end_at.tzinfo is None:
                raise InvalidEventUpdate
            duration = candidate.end_at - candidate.start_at
            if duration <= timedelta(0) or duration > timedelta(days=7):
                raise InvalidEventUpdate
        elif candidate.event_type == "recurring":
            if (
                candidate.recurrence_start_date is None
                or candidate.local_start_time is None
                or candidate.local_end_time is None
                or candidate.frequency not in {"daily", "weekly"}
                or (candidate.frequency == "weekly" and not candidate.weekdays)
                or candidate.end_day_offset not in {0, 1}
            ):
                raise InvalidEventUpdate
            start = datetime.combine(candidate.recurrence_start_date, candidate.local_start_time)
            end = datetime.combine(
                candidate.recurrence_start_date + timedelta(days=candidate.end_day_offset),
                candidate.local_end_time,
            )
            if end <= start or end - start > timedelta(days=1):
                raise InvalidEventUpdate
        else:
            raise InvalidEventUpdate
        try:
            return self._writer.update_event(event_id, version, updates)
        except EventNotFound as error:
            raise EventUpdateNotFound from error
        except EventVersionConflict as error:
            raise EventUpdateConflict from error
        except SeriesHasExceptions as error:
            raise EventSeriesHasExceptions from error

    def delete_event(self, event_id: str, version: int) -> None:
        try:
            self._writer.delete_event(event_id, version)
        except EventNotFound as error:
            raise EventUpdateNotFound from error
        except EventVersionConflict as error:
            raise EventUpdateConflict from error
