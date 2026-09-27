"""Business phase is derived from time; disposition remains a persisted user fact."""

from datetime import datetime
from typing import Literal

from .events import Occurrence
from .time_rules import is_active


def temporal_phase(occurrence: Occurrence, now: datetime) -> Literal["upcoming", "active", "ended"]:
    if is_active(occurrence.start_at, occurrence.end_at, now):
        return "active"
    return "upcoming" if now < occurrence.start_at else "ended"
