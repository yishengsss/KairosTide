"""Stable active-state versions and explicit conflict grouping."""

from hashlib import sha256

from .conflicts import pairs
from .events import Occurrence


def conflict_groups(active: tuple[Occurrence, ...]) -> tuple[tuple[str, ...], ...]:
    edges = pairs(active, ())
    neighbors: dict[str, set[str]] = {identity: set() for edge in edges for identity in edge}
    for left, right in edges:
        neighbors[left].add(right)
        neighbors[right].add(left)
    groups: list[tuple[str, ...]] = []
    remaining = set(neighbors)
    while remaining:
        root = min(remaining)
        pending = [root]
        component: set[str] = set()
        while pending:
            identity = pending.pop()
            if identity in component:
                continue
            component.add(identity)
            pending.extend(neighbors[identity] - component)
        remaining -= component
        groups.append(tuple(sorted(component)))
    return tuple(sorted(groups))


def state_revision(active: tuple[Occurrence, ...]) -> int:
    canonical = "\n".join(
        "|".join((item.occurrence_id, str(item.version), str(item.schedule_revision),
                  item.start_at.isoformat(), item.end_at.isoformat(), item.disposition))
        for item in sorted(active, key=lambda value: value.occurrence_id)
    )
    # Keep the integer within JavaScript's exact 53-bit range for round-trip use
    # in the state/conflict HTTP DTOs.
    revision = int.from_bytes(sha256(canonical.encode()).digest()[:6], "big")
    return 2 if revision == 1 else revision
