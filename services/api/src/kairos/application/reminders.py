"""Persistent five-minute reminders with schedule-version fencing."""

from datetime import timedelta
from .ports import Clock


class ReminderConflict(Exception):
    pass


class ReminderService:
    def __init__(self, repository, clock: Clock) -> None:
        self.repository = repository
        self.clock = clock

    def due(self, owner_id: str):
        now = self.clock.now()
        occurrences = self.repository.list_occurrences(owner_id, now, now + timedelta(days=1))
        for item in occurrences:
            if item.disposition == "scheduled" and timedelta(0) < item.start_at - now <= timedelta(minutes=5):
                self.repository.ensure_reminder(owner_id, item, now)
        return tuple(self.repository.list_active_reminders(owner_id, now))

    def acknowledge(self, owner_id: str, reminder_id: str, expected_version: int,
                    schedule_revision: int, idempotency_key: str):
        try:
            return self.repository.acknowledge_reminder(owner_id, reminder_id, expected_version,
                                                        schedule_revision, idempotency_key, self.clock.now())
        except ValueError as exc:
            raise ReminderConflict(str(exc)) from exc
