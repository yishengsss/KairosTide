from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from kairos.domain.errors import DatabaseNotInitialized, RecurrenceNeedsDSTPolicy
from kairos.domain.models import Event, EventException, Occurrence, StateSnapshot
from kairos.domain.scheduling import expand_event, is_active


class Clock(Protocol):
    def now(self) -> datetime: ...


class EventReader(Protocol):
    def list_events(self, start_before: datetime, end_after: datetime) -> list[Event]: ...

    def get_events(self, limit: int, offset: int) -> list[Event]: ...

    def get_exceptions(self, event_ids: list[str]) -> list[EventException]: ...


class StorageUnavailable(Exception):
    """Raised when local event storage has not been initialized."""


class RecurrenceNeedsConfirmation(Exception):
    """Raised when the requested window contains a DST time without policy."""


class EventQueries:
    def __init__(self, reader: EventReader, clock: Clock) -> None:
        self._reader = reader
        self._clock = clock

    def now(self) -> datetime:
        current = self._clock.now()
        if current.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return current.astimezone(UTC)

    @staticmethod
    def _status(occurrence: Occurrence, now: datetime) -> str:
        if is_active(occurrence.start_at, occurrence.end_at, now):
            return "active"
        if now < occurrence.start_at:
            return "scheduled"
        return "finished"

    def _query_occurrences(self, start: datetime, end: datetime) -> list[Occurrence]:
        try:
            events = self._reader.list_events(end, start)
        except DatabaseNotInitialized as error:
            raise StorageUnavailable from error
        try:
            occurrences = [
                occurrence for event in events for occurrence in expand_event(event, start, end)
            ]
        except RecurrenceNeedsDSTPolicy as error:
            raise RecurrenceNeedsConfirmation from error
        exceptions = self._reader.get_exceptions([event.id for event in events])
        exception_types = {
            (exception.event_id, exception.occurrence_key): exception.exception_type
            for exception in exceptions
        }
        now = self.now()
        marked = [
            replace(
                occurrence,
                status=exception_types.get(
                    (occurrence.event_id, occurrence.occurrence_key or ""),
                    self._status(occurrence, now),
                ),
            )
            for occurrence in occurrences
        ]
        return sorted(marked, key=lambda item: (item.start_at, item.occurrence_id))

    def get_state(self) -> StateSnapshot:
        now = self.now()
        occurrences = self._query_occurrences(now - timedelta(days=90), now + timedelta(days=90))
        active = [occurrence for occurrence in occurrences if occurrence.status == "active"]
        valid = [
            occurrence
            for occurrence in occurrences
            if occurrence.status not in {"excused", "cancelled", "finished"}
        ]
        boundaries = [
            boundary
            for occurrence in valid
            for boundary in (occurrence.start_at, occurrence.end_at)
            if boundary > now
        ]
        return StateSnapshot(
            server_now=now,
            active_occurrences=active,
            next_transition_at=min(boundaries, default=None),
        )

    def get_events(self, limit: int, offset: int) -> list[Occurrence]:
        try:
            events = self._reader.get_events(limit, offset)
        except DatabaseNotInitialized as error:
            raise StorageUnavailable from error
        now = self.now()
        result: list[Occurrence] = []
        for event in events:
            try:
                occurrences = expand_event(
                    event, now - timedelta(days=90), now + timedelta(days=90)
                )
            except RecurrenceNeedsDSTPolicy as error:
                raise RecurrenceNeedsConfirmation from error
            if occurrences:
                result.append(replace(occurrences[0], status=self._status(occurrences[0], now)))
        return result

    def get_occurrences(self, start: datetime, end: datetime) -> list[Occurrence]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("from and to must include a timezone")
        return self._query_occurrences(start.astimezone(UTC), end.astimezone(UTC))
