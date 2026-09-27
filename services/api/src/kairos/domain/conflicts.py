"""Conflict detection does not decide attendance or mark anything missed."""

from collections.abc import Iterable

from .events import Occurrence
from .time_rules import overlaps


def pairs(candidates: Iterable[Occurrence], existing: Iterable[Occurrence]) -> tuple[tuple[str, str], ...]:
    left = [item for item in candidates if item.disposition == "scheduled"]
    right = [item for item in existing if item.disposition == "scheduled"]
    found: set[tuple[str, str]] = set()
    for index, item in enumerate(left):
        for other in left[index + 1:] + right:
            if item.occurrence_id != other.occurrence_id and overlaps(item.start_at, item.end_at, other.start_at, other.end_at):
                found.add(tuple(sorted((item.occurrence_id, other.occurrence_id))))
    return tuple(sorted(found))
