"""Reviewable candidates; a draft never represents a saved event."""

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .events import RecurrenceRule
from .time_rules import overlaps


class DraftNotReady(ValueError):
    pass


class RevisionConflict(ValueError):
    pass


class IdempotencyConflict(ValueError):
    pass


class OwnershipError(ValueError):
    pass


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    title: str | None
    location: str | None
    start_at: datetime | None
    end_at: datetime | None
    timezone: str | None
    recurrence: RecurrenceRule | None = None

    @property
    def missing_fields(self) -> tuple[str, ...]:
        fields = []
        if not self.title or not self.title.strip():
            fields.append("title")
        if self.start_at is None:
            fields.append("start_at")
        if self.end_at is None:
            fields.append("end_at")
        if not self.timezone:
            fields.append("timezone")
        if self.recurrence is not None and self.recurrence.ends_on is None:
            fields.append("recurrence.ends_on")
        return tuple(fields)

    def validate_ready(self) -> None:
        if self.missing_fields:
            raise DraftNotReady(f"candidate {self.candidate_id} needs {', '.join(self.missing_fields)}")
        assert self.start_at is not None and self.end_at is not None
        overlaps(self.start_at, self.end_at, self.start_at, self.end_at)
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise DraftNotReady("candidate times must be timezone aware")


@dataclass(frozen=True)
class Draft:
    draft_id: str
    owner_id: str
    revision: int
    source_message_id: str
    reference_now: datetime
    expires_at: datetime
    candidates: tuple[Candidate, ...]
    status: str
    confirmation_digest: str | None


def digest_for(draft_id: str, revision: int, candidates: tuple[Candidate, ...]) -> str:
    payload = {
        "draft_id": draft_id,
        "revision": revision,
        "candidates": [
            {
                "candidate_id": c.candidate_id,
                "title": c.title,
                "location": c.location,
                "start_at": c.start_at.isoformat() if c.start_at else None,
                "end_at": c.end_at.isoformat() if c.end_at else None,
                "timezone": c.timezone,
                "recurrence": repr(c.recurrence) if c.recurrence else None,
            } for c in candidates
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def make_draft(draft_id: str, owner_id: str, revision: int, source_message_id: str,
               reference_now: datetime, expires_at: datetime, candidates: tuple[Candidate, ...],
               committed: bool = False) -> Draft:
    if not candidates or len({c.candidate_id for c in candidates}) != len(candidates):
        raise ValueError("draft needs nonempty unique candidate IDs")
    for candidate in candidates:
        if candidate.timezone:
            try:
                ZoneInfo(candidate.timezone)
            except ZoneInfoNotFoundError as error:
                raise ValueError("invalid IANA timezone") from error
    status = "committed" if committed else ("ready" if all(not c.missing_fields for c in candidates) else "needs_clarification")
    return Draft(draft_id, owner_id, revision, source_message_id, reference_now, expires_at,
                 candidates, status, digest_for(draft_id, revision, candidates))


def edit_candidate(draft: Draft, candidate_id: str, **changes: object) -> Draft:
    allowed = {"title", "location", "start_at", "end_at", "timezone", "recurrence"}
    if not changes or set(changes) - allowed:
        raise ValueError("unsupported candidate edit")
    if draft.status == "committed":
        raise RevisionConflict("committed draft is immutable")
    if candidate_id not in {candidate.candidate_id for candidate in draft.candidates}:
        raise KeyError(candidate_id)
    edited = tuple(replace(candidate, **changes) if candidate.candidate_id == candidate_id else candidate
                   for candidate in draft.candidates)
    return make_draft(draft.draft_id, draft.owner_id, draft.revision + 1, draft.source_message_id,
                      draft.reference_now, draft.expires_at, edited)
