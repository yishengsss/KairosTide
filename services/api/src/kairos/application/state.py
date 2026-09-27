"""A same-instant state projection. Reminder policy will be injected by T5."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from kairos.domain.attention import conflict_groups, state_revision
from kairos.domain.conflicts import pairs
from kairos.domain.events import Occurrence
from kairos.domain.state import temporal_phase

from .ports import Clock


@dataclass(frozen=True)
class StateSnapshot:
    server_now: datetime
    active_occurrences: tuple[Occurrence, ...]
    conflict_pairs: tuple[tuple[str, str], ...]
    conflicts: tuple[tuple[str, ...], ...]
    state_revision: int
    next_transition_at: datetime | None
    due_reminders: tuple[dict, ...] = ()


class StateService:
    def __init__(self, repository, clock: Clock, reminder_service=None) -> None:
        self.repository = repository
        self.clock = clock
        self.reminder_service = reminder_service

    def snapshot(self, owner_id: str) -> StateSnapshot:
        now = self.clock.now()
        occurrences = self.repository.list_occurrences(owner_id, now - timedelta(days=1), now + timedelta(days=1))
        active = tuple(item for item in occurrences if item.disposition == "scheduled" and temporal_phase(item, now) == "active")
        boundaries = [item.end_at for item in active]
        boundaries.extend(item.start_at for item in occurrences
                          if item.disposition == "scheduled" and temporal_phase(item, now) == "upcoming")
        next_transition = min(boundaries, default=None)
        due = self.reminder_service.due(owner_id) if self.reminder_service else ()
        groups = conflict_groups(active)
        return StateSnapshot(now, active, pairs(active, ()), groups, state_revision(active), next_transition, due)
