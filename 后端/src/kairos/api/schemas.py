from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kairos.application.planning import EventCandidate, PlannerResult


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    occurrence_id: str
    event_id: str
    title: str
    location: str | None
    start_at: datetime
    end_at: datetime
    status: str
    version: int


class StateResponse(BaseModel):
    server_now: datetime
    active_occurrences: list[EventResponse]
    next_transition_at: datetime | None


class EventListResponse(BaseModel):
    items: list[EventResponse]


class ExceptionRequest(BaseModel):
    exception_type: Literal["excused", "cancelled"]
    idempotency_key: str = Field(min_length=1, max_length=128)


class PlanningPreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    timezone: str = Field(min_length=1, max_length=100)
    answers: dict[str, str] | None = None

    @field_validator("text")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text cannot be blank")
        return value.strip()


class PlanningPreviewResponse(PlannerResult):
    reference_now: datetime


class DraftCreateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    timezone: str = Field(min_length=1, max_length=100)

    @field_validator("text")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text cannot be blank")
        return value.strip()


class DraftClarificationRequest(BaseModel):
    revision: int = Field(ge=1)
    answers: dict[str, str] = Field(min_length=1)


class DraftCommitRequest(BaseModel):
    revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)


class DraftResponse(BaseModel):
    draft_id: str
    revision: int
    status: str
    timezone: str
    reference_now: datetime
    expires_at: datetime
    candidates: list[EventCandidate]
    questions: list[str]
    message: str | None


class DraftCommitResponse(BaseModel):
    draft_id: str
    event_ids: list[str]


class EventPatch(BaseModel):
    version: int
    title: str | None = None
    location: str | None = None
    notes: str | None = None
    timezone: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    event_type: Literal["single", "recurring"] | None = None
    recurrence_start_date: date | None = None
    local_start_time: time | None = None
    local_end_time: time | None = None
    end_day_offset: int | None = None
    frequency: Literal["daily", "weekly"] | None = None
    weekdays: list[int] | None = None
    until_date: date | None = None
    gap_policy: Literal["skip"] | None = None
    fold_policy: Literal["earlier", "later"] | None = None

    @field_validator("version")
    @classmethod
    def version_is_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("version must be positive")
        return value

    @field_validator("end_day_offset")
    @classmethod
    def overnight_offset_is_supported(cls, value: int | None) -> int | None:
        if value is not None and value not in {0, 1}:
            raise ValueError("end_day_offset must be 0 or 1")
        return value

    @field_validator("weekdays")
    @classmethod
    def weekdays_are_valid(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and (
            any(day not in range(1, 8) for day in value) or len(value) != len(set(value))
        ):
            raise ValueError("weekdays must be unique ISO weekday numbers from 1 through 7")
        return value
