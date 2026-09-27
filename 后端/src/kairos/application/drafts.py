from datetime import datetime, timedelta
from typing import Protocol, cast
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kairos.application.planning import Planner, PlannerResult
from kairos.application.state import StorageUnavailable
from kairos.domain.errors import (
    DatabaseNotInitialized,
    DraftNotFound,
    DraftVersionConflict,
    IdempotencyKeyReused,
)

DRAFT_LIFETIME = timedelta(minutes=30)


class DraftRepository(Protocol):
    def save_draft(self, draft: dict[str, object]) -> None: ...

    def get_draft(self, draft_id: str) -> dict[str, object] | None: ...

    def update_draft(self, draft: dict[str, object], expected_revision: int) -> bool: ...

    def commit_draft(
        self,
        draft_id: str,
        revision: int,
        idempotency_key: str,
        candidates: list[dict[str, object]],
        created_at: datetime,
    ) -> list[str]: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class DraftNotFoundError(Exception):
    pass


class DraftExpiredError(Exception):
    pass


class DraftConflictError(Exception):
    pass


class DraftIdempotencyConflictError(Exception):
    pass


class InvalidCandidateError(Exception):
    pass


class InvalidTimezoneError(Exception):
    pass


class DraftCommands:
    def __init__(self, repository: DraftRepository, planner: Planner, clock: Clock) -> None:
        self._repository = repository
        self._planner = planner
        self._clock = clock

    def _now(self) -> datetime:
        current = self._clock.now()
        if current.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return current

    def _get_draft(self, draft_id: str) -> dict[str, object] | None:
        try:
            return self._repository.get_draft(draft_id)
        except DatabaseNotInitialized as error:
            raise StorageUnavailable from error

    @staticmethod
    def _validate_candidates(result: PlannerResult, timezone: str) -> None:
        for candidate in result.candidates:
            if candidate.timezone != timezone:
                raise InvalidCandidateError
            try:
                ZoneInfo(candidate.timezone)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise InvalidCandidateError from error

    @staticmethod
    def _view(draft: dict[str, object]) -> dict[str, object]:
        result = PlannerResult.model_validate(draft["result"])
        return {
            "draft_id": draft["id"],
            "revision": draft["revision"],
            "status": draft["status"],
            "timezone": draft["timezone"],
            "reference_now": draft["reference_now"],
            "expires_at": draft["expires_at"],
            "candidates": result.candidates,
            "questions": result.questions,
            "message": result.message,
        }

    def create(self, text: str, timezone: str) -> dict[str, object]:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise InvalidTimezoneError from error
        reference_now = self._now()
        result = self._planner.parse(text, timezone, reference_now)
        self._validate_candidates(result, timezone)
        draft: dict[str, object] = {
            "id": uuid4().hex,
            "revision": 1,
            "status": result.status,
            "text": text,
            "timezone": timezone,
            "reference_now": reference_now,
            "expires_at": reference_now + DRAFT_LIFETIME,
            "answers": {},
            "result": result.model_dump(mode="json"),
        }
        try:
            self._repository.save_draft(draft)
        except DatabaseNotInitialized as error:
            raise StorageUnavailable from error
        return self._view(draft)

    def clarify(self, draft_id: str, revision: int, answers: dict[str, str]) -> dict[str, object]:
        draft = self._get_draft(draft_id)
        if draft is None:
            raise DraftNotFoundError
        if self._now() >= cast(datetime, draft["expires_at"]):
            raise DraftExpiredError
        if draft["revision"] != revision or draft["status"] != "needs_clarification":
            raise DraftConflictError
        combined_answers = dict(cast(dict[str, str], draft["answers"]))
        combined_answers.update(answers)
        result = self._planner.parse(
            str(draft["text"]),
            str(draft["timezone"]),
            cast(datetime, draft["reference_now"]),
            combined_answers,
        )
        self._validate_candidates(result, str(draft["timezone"]))
        updated = {
            **draft,
            "revision": revision + 1,
            "status": result.status,
            "answers": combined_answers,
            "result": result.model_dump(mode="json"),
        }
        try:
            updated_successfully = self._repository.update_draft(updated, revision)
        except DatabaseNotInitialized as error:
            raise StorageUnavailable from error
        except DraftVersionConflict as error:
            raise DraftConflictError from error
        if not updated_successfully:
            raise DraftConflictError
        return self._view(updated)

    def commit(self, draft_id: str, revision: int, idempotency_key: str) -> dict[str, object]:
        if not idempotency_key.strip():
            raise ValueError("idempotency key cannot be blank")
        draft = self._get_draft(draft_id)
        if draft is None:
            raise DraftNotFoundError
        result = PlannerResult.model_validate(draft["result"])
        if draft["status"] != "committed":
            if self._now() >= cast(datetime, draft["expires_at"]):
                raise DraftExpiredError
            if draft["revision"] != revision or draft["status"] != "ready":
                raise DraftConflictError
        candidates = [candidate.model_dump(mode="json") for candidate in result.candidates]
        try:
            event_ids = self._repository.commit_draft(
                draft_id,
                revision,
                idempotency_key,
                candidates,
                self._now(),
            )
        except DraftNotFound as error:
            raise DraftNotFoundError from error
        except DatabaseNotInitialized as error:
            raise StorageUnavailable from error
        except IdempotencyKeyReused as error:
            raise DraftIdempotencyConflictError from error
        except DraftVersionConflict as error:
            raise DraftConflictError from error
        return {"draft_id": draft_id, "event_ids": event_ids}
