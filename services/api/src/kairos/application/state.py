"""A same-instant state projection. Reminder policy will be injected by T5."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from kairos.domain.conflicts import pairs
from kairos.domain.events import Occurrence
from kairos.domain.state import temporal_phase

from .ports import Clock


@dataclass(frozen=True)
class StateSnapshot:
    server_now: datetime
    active_occurrences: tuple[Occurrence, ...]
    conflict_pairs: tuple[tuple[str, str], ...]


class StateService:
    def __init__(self, repository, clock: Clock) -> None:
        self.repository = repository
        self.clock = clock

    def snapshot(self, owner_id: str) -> StateSnapshot:
        now = self.clock.now()
        occurrences = self.repository.list_occurrences(owner_id, now - timedelta(days=1), now + timedelta(days=1))
        active = tuple(item for item in occurrences if item.disposition == "scheduled" and temporal_phase(item, now) == "active")
        return StateSnapshot(now, active, pairs(active, ()))
