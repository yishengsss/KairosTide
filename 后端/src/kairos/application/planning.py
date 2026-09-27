from datetime import datetime, timedelta
from typing import Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


class ModelUnavailable(Exception):
    """The configured model service could not be reached."""


class ModelTimeout(Exception):
    """The configured model service timed out."""


class ModelInvalidOutput(Exception):
    """The model returned malformed or invalid planner data."""


class EventCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    timezone: str
    start_at: datetime
    end_at: datetime
    location: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("title")
    @classmethod
    def title_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title cannot be blank")
        return value.strip()

    @field_validator("end_at")
    @classmethod
    def end_follows_start(cls, value: datetime, info: ValidationInfo) -> datetime:
        start = info.data.get("start_at")
        if start is not None:
            if value.tzinfo is None or start.tzinfo is None or value <= start:
                raise ValueError("event end must follow its timezone-aware start")
            if value - start > timedelta(days=7):
                raise ValueError("single events cannot exceed seven days")
        return value

    @field_validator("start_at")
    @classmethod
    def start_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("event start must include a timezone offset")
        return value

    @model_validator(mode="after")
    def offsets_match_timezone(self) -> "EventCandidate":
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("candidate timezone must be a valid IANA identifier") from error
        for value in (self.start_at, self.end_at):
            if value.utcoffset() != value.astimezone(zone).utcoffset():
                raise ValueError("candidate timestamp offset does not match its timezone")
        return self


class PlannerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "needs_clarification", "unsupported"]
    candidates: list[EventCandidate] = Field(default_factory=list, max_length=10)
    questions: list[str] = Field(default_factory=list, max_length=10)
    message: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def status_matches_content(self) -> "PlannerResult":
        if self.status == "ready" and not self.candidates:
            raise ValueError("ready result requires at least one candidate")
        if self.status == "needs_clarification" and not self.questions:
            raise ValueError("clarification result requires a question")
        if self.status == "unsupported" and self.candidates:
            raise ValueError("unsupported result cannot contain candidates")
        return self


class Planner(Protocol):
    def parse(
        self,
        text: str,
        timezone: str,
        reference_now: datetime,
        answers: dict[str, str] | None = None,
    ) -> PlannerResult: ...
