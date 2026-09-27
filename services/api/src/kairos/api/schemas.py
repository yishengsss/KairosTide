"""Human-maintained transport contract. Product policies remain outside these DTOs."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorResponse(DTO):
    code: str
    message: str
    request_id: str
    field_errors: dict[str, str] | None = None
    current_revision: int | None = None


class HealthResponse(DTO):
    status: Literal["ok"]


class TemporalPhase(StrEnum):
    UPCOMING = "upcoming"
    ACTIVE = "active"
    ENDED = "ended"


class Disposition(StrEnum):
    SCHEDULED = "scheduled"
    EXCUSED = "excused"
    CANCELLED = "cancelled"
    MISSED = "missed"


class Recurrence(DTO):
    frequency: Literal["daily", "weekly"]
    timezone: str
    starts_on: str
    ends_on: str | None
    weekdays: list[int] | None
    dst_gap_policy: Literal["skip"] | None
    dst_fold_policy: Literal["earlier", "later"] | None


class Event(DTO):
    event_id: str
    version: int
    title: str
    location: str | None
    start_at: datetime
    end_at: datetime
    recurrence: Recurrence | None


class EventPage(DTO):
    items: list[Event]
    next_cursor: str | None


class Occurrence(DTO):
    occurrence_id: str
    event_id: str
    version: int
    title: str
    location: str | None
    temporal_phase: TemporalPhase
    disposition: Disposition
    start_at: datetime
    end_at: datetime


class OccurrencePage(DTO):
    items: list[Occurrence]
    next_cursor: str | None


class Reminder(DTO):
    reminder_id: str
    occurrence_id: str
    version: int
    schedule_revision: int
    acknowledged_at: datetime | None
    event_title: str
    location: str | None
    start_at: datetime
    minutes_until_start: int = Field(ge=0, le=5)


class Conflict(DTO):
    conflict_id: str
    member_ids: list[str] = Field(min_length=2)
    snapshot_revision: int
    selected_id: str | None


class StateResponse(DTO):
    server_now: datetime
    state_revision: int
    active_occurrences: list[Occurrence]
    due_reminders: list[Reminder]
    conflicts: list[Conflict]
    next_transition_at: datetime | None


class ReminderAckResponse(DTO):
    reminder_id: str
    occurrence_id: str
    version: int
    schedule_revision: int
    acknowledged_at: datetime


class ReminderAckRequest(DTO):
    expected_version: int
    schedule_revision: int


class ConflictDecisionRequest(DTO):
    member_ids: list[str] = Field(min_length=2)
    selected_id: str
    snapshot_revision: int
    source_action_id: str


class ConflictDecisionResponse(DTO):
    decision_id: str
    selected_id: str
    affected_occurrences: list[Occurrence]
    state_revision: int


class DraftStatus(StrEnum):
    NEEDS_CLARIFICATION = "needs_clarification"
    READY = "ready"
    COMMITTED = "committed"
    EXPIRED = "expired"


class DraftCandidate(DTO):
    candidate_id: str
    title: str | None
    location: str | None
    start_at: datetime | None
    end_at: datetime | None
    timezone: str | None
    recurrence: Recurrence | None
    missing_fields: list[str]


class DraftRequest(DTO):
    conversation_id: str
    source_message_id: str
    intent: str
    text: str
    timezone: str


class DraftResponse(DTO):
    draft_id: str
    revision: int
    status: DraftStatus
    reference_now: datetime
    expires_at: datetime
    candidates: list[DraftCandidate]
    questions: list[str]
    related_action_ids: list[str]
    confirmation_digest: str | None


class ClarificationRequest(DTO):
    revision: int
    answers: dict[str, str]


class CandidateOperation(DTO):
    action: Literal["update_candidate", "remove_candidate", "add_candidate"]
    candidate_id: str | None
    changes: dict[str, Any] | None


class DraftPatchRequest(DTO):
    revision: int
    operations: list[CandidateOperation] = Field(min_length=1)


class DraftCommitRequest(DTO):
    revision: int
    confirmed_candidate_ids: list[str] = Field(min_length=1)
    confirmation_digest: str
    conflict_acceptance: str | None


class CommittedResource(DTO):
    resource_type: Literal["event", "flexible_task"]
    resource_id: str
    version: int


class DraftCommitResponse(DTO):
    draft_id: str
    revision: int
    resources: list[CommittedResource]


class OccurrenceExceptionRequest(DTO):
    type: Literal["excused", "cancelled"]
    expected_version: int
    source_action_id: str


class ChangeProposalRequest(DTO):
    target_id: str
    scope: Literal["occurrence", "series"]
    expected_version: int
    action: Literal["update", "delete"]
    changes: dict[str, Any] | None
    source_message_id: str


class ChangeProposalResponse(DTO):
    proposal_id: str
    target_id: str
    scope: Literal["occurrence", "series"]
    revision: int
    action: Literal["update", "delete"]
    summary: str
    confirmation_digest: str
    status: Literal["pending", "committed"]


class ChangeProposalCommitRequest(DTO):
    revision: int
    confirmation_digest: str
    source_action_id: str


class ChangeProposalCommitResponse(DTO):
    proposal_id: str
    target_id: str
    scope: Literal["occurrence", "series"]
    action: Literal["update", "delete"]
    affected_ids: list[str]
    version: int
    status: Literal["committed"]


class FlexibleTaskRequest(DTO):
    title: str
    deadline: date | datetime | None
    deadline_precision: Literal["date", "instant"] | None
    timezone: str
    source_message_id: str

    @model_validator(mode="after")
    def validate_deadline_precision(self):
        validate_deadline_pair(self.deadline, self.deadline_precision)
        return self


class FlexibleTask(DTO):
    task_id: str
    version: int
    title: str
    deadline: date | datetime | None
    deadline_precision: Literal["date", "instant"] | None
    timezone: str
    lifecycle_status: Literal["planned", "active", "completed"]

    @model_validator(mode="after")
    def validate_deadline_precision(self):
        validate_deadline_pair(self.deadline, self.deadline_precision)
        return self


class FlexibleTaskLifecycleRequest(DTO):
    status: Literal["planned", "active", "completed"]
    expected_version: int


def validate_deadline_pair(deadline: date | datetime | None, precision: str | None) -> None:
    if deadline is None and precision is None:
        return
    if deadline is None or precision is None:
        raise ValueError("deadline and deadline_precision must be provided together")
    actual_precision = "instant" if isinstance(deadline, datetime) else "date"
    if precision != actual_precision:
        raise ValueError(f"deadline_precision must be {actual_precision} for this deadline value")


class FlexibleTaskQueryRequest(DTO):
    conversation_id: str
    source_message_id: str
    query_scope: str


class FlexibleTaskQueryResponse(DTO):
    items: list[FlexibleTask]
    source_message_id: str


class FlexibleTaskPage(DTO):
    items: list[FlexibleTask]


class Conversation(DTO):
    conversation_id: str
    revision: int


class AssistantImageAttachment(DTO):
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    data_base64: str = Field(min_length=1, max_length=14_000_000)


class MessageRequest(DTO):
    client_message_id: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=5000)
    timezone: str = Field(min_length=1)
    expected_sequence: int = Field(ge=0)
    image: AssistantImageAttachment | None = None


class ConversationMessage(DTO):
    message_id: str
    sequence: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    status: Literal["pending", "completed"]
    action_results: list[dict[str, Any]] = Field(default_factory=list)
    draft_refs: list[str] = Field(default_factory=list)


class MessageResponse(DTO):
    user_message: ConversationMessage
    answer: ConversationMessage | None
    status: Literal["pending", "completed"]
    tool_results: list[dict[str, Any]]
    draft_refs: list[str]
    revision: int


class MessagePage(DTO):
    items: list[ConversationMessage]
    next_cursor: str | None
    draft_refs: list[str]
    revision: int
    pending_client_message_id: str | None = None


class AssistantChatMessage(DTO):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=5000)


class AssistantChatRequest(DTO):
    client_message_id: str = Field(min_length=1, max_length=200)
    timezone: str = Field(min_length=1, max_length=100)
    messages: list[AssistantChatMessage] = Field(min_length=1, max_length=24)
    image: AssistantImageAttachment | None = None

    @model_validator(mode="after")
    def require_user_turn(self):
        if self.messages[-1].role != "user":
            raise ValueError("last message must be from the user")
        return self


class AssistantActionResult(DTO):
    action: str
    status: str
    data: Any | None = None
    message: str | None = None


class AssistantChatResponse(DTO):
    answer: str = Field(min_length=1)
    action_results: list[AssistantActionResult] = Field(default_factory=list)
    draft: DraftResponse | None = None
    retain_image: bool = False


class WeatherObservation(DTO):
    kind: Literal["current", "forecast"]
    condition: Literal["clear", "partly_cloudy", "overcast", "rain", "fog", "snow"] | None
    cloud_cover: float | None
    precipitation: float | None
    visibility: float | None
    observed_at: datetime | None
    valid_until: datetime | None


class WeatherPlaceChoice(DTO):
    name: str
    latitude: float
    longitude: float
    timezone: str
    country: str | None
    admin1: str | None


class WeatherResponse(DTO):
    location_id: str
    availability: Literal["available", "stale", "unavailable"]
    source: str | None
    fetched_at: datetime | None
    observations: list[WeatherObservation]
    location_label: str | None = None
    timezone: str | None = None
    attribution: str | None = None
    detail: str | None = None
    location_choices: list[WeatherPlaceChoice] = Field(default_factory=list)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
