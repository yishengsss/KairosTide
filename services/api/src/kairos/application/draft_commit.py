"""A user-confirmed draft commits every candidate in one repository transaction."""

from dataclasses import dataclass

from kairos.domain.drafts import DraftNotReady

from .ports import Clock


class ConflictReviewRequired(ValueError):
    def __init__(self, conflict_pairs: tuple[tuple[str, str], ...], acceptance_token: str) -> None:
        super().__init__("overlapping events require explicit review")
        self.conflict_pairs = conflict_pairs
        self.acceptance_token = acceptance_token


@dataclass(frozen=True)
class CommitResult:
    draft_id: str
    revision: int
    event_ids: tuple[str, ...]


class DraftCommitService:
    def __init__(self, repository, clock: Clock) -> None:
        self.repository = repository
        self.clock = clock

    def commit(self, owner_id: str, draft_id: str, revision: int, confirmed_candidate_ids: list[str],
               confirmation_digest: str | None, idempotency_key: str,
               conflict_acceptance: str | None = None) -> CommitResult:
        if not confirmed_candidate_ids or len(set(confirmed_candidate_ids)) != len(confirmed_candidate_ids):
            raise DraftNotReady("confirm each candidate once")
        if not confirmation_digest:
            raise DraftNotReady("confirmation digest required")
        return self.repository.commit_draft(owner_id, draft_id, revision, tuple(confirmed_candidate_ids),
                                            confirmation_digest, idempotency_key,
                                            conflict_acceptance, self.clock.now())
