"""Explicit instance commands cannot change the whole series."""

from datetime import datetime

from .ports import Clock


class OccurrenceService:
    def __init__(self, repository, clock: Clock) -> None:
        self.repository = repository
        self.clock = clock

    def set_exception(self, owner_id: str, occurrence_id: str, disposition: str, expected_version: int,
                      source_action_id: str, idempotency_key: str):
        if disposition not in ("excused", "cancelled"):
            raise ValueError("only explicit excuse or cancellation is supported here")
        return self.repository.set_exception(owner_id, occurrence_id, disposition, expected_version,
                                             source_action_id, idempotency_key, self.clock.now())

    def reschedule_single(self, owner_id: str, occurrence_id: str, expected_version: int,
                          start_at: datetime, end_at: datetime):
        return self.repository.reschedule_single(owner_id, occurrence_id, expected_version, start_at, end_at)
