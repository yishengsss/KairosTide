"""Structured draft creation and targeted candidate editing."""

from datetime import timedelta
from uuid import uuid4

from kairos.domain.drafts import Candidate, Draft, RevisionConflict, edit_candidate, make_draft

from .ports import Clock


class DraftService:
    def __init__(self, repository, clock: Clock) -> None:
        self.repository = repository
        self.clock = clock

    def create(self, owner_id: str, candidates: list[Candidate], source_message_id: str) -> Draft:
        now = self.clock.now()
        draft = make_draft(f"draft_{uuid4().hex}", owner_id, 1, source_message_id,
                           now, now + timedelta(hours=24), tuple(candidates))
        self.repository.save_draft(draft)
        return draft

    def update_candidate(self, owner_id: str, draft_id: str, revision: int, candidate_id: str, **changes) -> Draft:
        draft = self._editable(owner_id, draft_id, revision)
        updated = edit_candidate(draft, candidate_id, **changes)
        self.repository.update_draft(updated, revision)
        return updated

    def add_candidate(self, owner_id: str, draft_id: str, revision: int, candidate: Candidate) -> Draft:
        draft = self._editable(owner_id, draft_id, revision)
        if candidate.candidate_id in {item.candidate_id for item in draft.candidates}:
            raise ValueError("candidate ID already exists")
        updated = make_draft(draft.draft_id, owner_id, revision + 1, draft.source_message_id,
                             draft.reference_now, draft.expires_at, draft.candidates + (candidate,))
        self.repository.update_draft(updated, revision)
        return updated

    def remove_candidate(self, owner_id: str, draft_id: str, revision: int, candidate_id: str) -> Draft:
        draft = self._editable(owner_id, draft_id, revision)
        if candidate_id not in {item.candidate_id for item in draft.candidates}:
            raise KeyError(candidate_id)
        updated = make_draft(draft.draft_id, owner_id, revision + 1, draft.source_message_id,
                             draft.reference_now, draft.expires_at,
                             tuple(item for item in draft.candidates if item.candidate_id != candidate_id))
        self.repository.update_draft(updated, revision)
        return updated

    def _editable(self, owner_id: str, draft_id: str, revision: int) -> Draft:
        draft = self.repository.get_draft(owner_id, draft_id)
        if draft is None:
            raise KeyError(draft_id)
        if draft.revision != revision or draft.expires_at <= self.clock.now() or draft.status == "committed":
            raise RevisionConflict("draft version changed or expired")
        return draft
