from datetime import datetime, timedelta
from typing import Annotated, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from kairos.api.schemas import (
    DraftClarificationRequest,
    DraftCommitRequest,
    DraftCommitResponse,
    DraftCreateRequest,
    DraftResponse,
    EventListResponse,
    EventPatch,
    EventResponse,
    ExceptionRequest,
    PlanningPreviewRequest,
    PlanningPreviewResponse,
    StateResponse,
)
from kairos.application.drafts import (
    DraftCommands,
    DraftConflictError,
    DraftExpiredError,
    DraftIdempotencyConflictError,
    DraftNotFoundError,
    InvalidCandidateError,
    InvalidTimezoneError,
)
from kairos.application.events import (
    EventCommands,
    EventSeriesHasExceptions,
    EventUpdateConflict,
    EventUpdateNotFound,
    InvalidEventUpdate,
    OccurrenceDoesNotExist,
    OccurrenceExceptionConflict,
    RecurrenceNeedsConfirmation,
)
from kairos.application.planning import (
    ModelInvalidOutput,
    ModelTimeout,
    ModelUnavailable,
    Planner,
)
from kairos.application.state import EventQueries, StorageUnavailable

router = APIRouter(prefix="/api/v1")
MAX_QUERY_DAYS = 90


def _queries(request: Request) -> EventQueries:
    return cast(EventQueries, request.app.state.event_queries)


def _commands(request: Request) -> EventCommands:
    return cast(EventCommands, request.app.state.event_commands)


def _planner(request: Request) -> Planner | None:
    return cast(Planner | None, request.app.state.planner)


def _draft_commands(request: Request) -> DraftCommands | None:
    return cast(DraftCommands | None, request.app.state.draft_commands)


def _database_error(error: StorageUnavailable) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": "DATABASE_NOT_INITIALIZED", "message": "initialize the local database"},
    )


def _dst_policy_error() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "DST_POLICY_REQUIRED", "message": "confirm how this local time recurs"},
    )


def _model_error(error: Exception) -> HTTPException:
    if isinstance(error, ModelInvalidOutput):
        return HTTPException(
            status_code=502,
            detail={"code": "MODEL_INVALID_OUTPUT", "message": "planner returned invalid data"},
        )
    if isinstance(error, ModelTimeout):
        return HTTPException(
            status_code=504,
            detail={"code": "MODEL_TIMEOUT", "message": "planner timed out; retry the request"},
        )
    return HTTPException(
        status_code=503,
        detail={"code": "MODEL_UNAVAILABLE", "message": "planner service is unavailable"},
    )


def _validate_window(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_TIME", "message": "from and to must include a timezone"},
        )
    if start >= end:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_RANGE", "message": "from must be earlier than to"},
        )
    if end - start > timedelta(days=MAX_QUERY_DAYS):
        raise HTTPException(
            status_code=422,
            detail={"code": "RANGE_TOO_LARGE", "message": "query range cannot exceed 90 days"},
        )


@router.post("/planning/preview", response_model=PlanningPreviewResponse)
def preview_natural_language(
    payload: PlanningPreviewRequest, request: Request
) -> PlanningPreviewResponse:
    planner = _planner(request)
    if planner is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "MODEL_UNAVAILABLE", "message": "configure the planner service"},
        )
    try:
        ZoneInfo(payload.timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_TIMEZONE", "message": "timezone must be an IANA identifier"},
        ) from error
    reference_now = _queries(request).now()
    try:
        result = planner.parse(
            payload.text,
            payload.timezone,
            reference_now,
            payload.answers,
        )
    except ModelInvalidOutput as error:
        raise HTTPException(
            status_code=502,
            detail={"code": "MODEL_INVALID_OUTPUT", "message": "planner returned invalid data"},
        ) from error
    except ModelTimeout as error:
        raise HTTPException(
            status_code=504,
            detail={"code": "MODEL_TIMEOUT", "message": "planner timed out; retry the request"},
        ) from error
    except ModelUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "MODEL_UNAVAILABLE", "message": "planner service is unavailable"},
        ) from error
    for candidate in result.candidates:
        try:
            ZoneInfo(candidate.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "MODEL_INVALID_OUTPUT", "message": "planner returned invalid data"},
            ) from error
        if candidate.timezone != payload.timezone:
            raise HTTPException(
                status_code=502,
                detail={"code": "MODEL_INVALID_OUTPUT", "message": "planner returned invalid data"},
            )
    return PlanningPreviewResponse(**result.model_dump(), reference_now=reference_now)


@router.post("/drafts", response_model=DraftResponse, status_code=201)
def create_draft(payload: DraftCreateRequest, request: Request) -> DraftResponse:
    commands = _draft_commands(request)
    if commands is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "MODEL_UNAVAILABLE", "message": "configure the planner service"},
        )
    try:
        result = commands.create(payload.text, payload.timezone)
    except (ModelInvalidOutput, ModelTimeout, ModelUnavailable) as error:
        raise _model_error(error) from error
    except InvalidCandidateError as error:
        raise HTTPException(
            status_code=502,
            detail={"code": "MODEL_INVALID_OUTPUT", "message": "planner returned invalid data"},
        ) from error
    except InvalidTimezoneError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_TIMEZONE", "message": "timezone must be an IANA identifier"},
        ) from error
    except StorageUnavailable as error:
        raise _database_error(error) from error
    return DraftResponse.model_validate(result)


@router.post("/drafts/{draft_id}/clarifications", response_model=DraftResponse)
def clarify_draft(
    draft_id: str, payload: DraftClarificationRequest, request: Request
) -> DraftResponse:
    commands = _draft_commands(request)
    if commands is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "MODEL_UNAVAILABLE", "message": "configure the planner service"},
        )
    try:
        result = commands.clarify(draft_id, payload.revision, payload.answers)
    except DraftNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "DRAFT_NOT_FOUND", "message": "draft was not found"},
        ) from error
    except DraftExpiredError as error:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "DRAFT_EXPIRED",
                "message": "create a new draft from the original text",
            },
        ) from error
    except DraftConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "DRAFT_VERSION_CONFLICT", "message": "reload the draft before editing"},
        ) from error
    except InvalidCandidateError as error:
        raise HTTPException(
            status_code=502,
            detail={"code": "MODEL_INVALID_OUTPUT", "message": "planner returned invalid data"},
        ) from error
    except (ModelInvalidOutput, ModelTimeout, ModelUnavailable) as error:
        raise _model_error(error) from error
    except StorageUnavailable as error:
        raise _database_error(error) from error
    return DraftResponse.model_validate(result)


@router.post("/drafts/{draft_id}/commit", response_model=DraftCommitResponse)
def commit_draft(
    draft_id: str, payload: DraftCommitRequest, request: Request
) -> DraftCommitResponse:
    commands = _draft_commands(request)
    if commands is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "MODEL_UNAVAILABLE", "message": "configure the planner service"},
        )
    try:
        result = commands.commit(draft_id, payload.revision, payload.idempotency_key)
    except DraftNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "DRAFT_NOT_FOUND", "message": "draft was not found"},
        ) from error
    except DraftExpiredError as error:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "DRAFT_EXPIRED",
                "message": "create a new draft from the original text",
            },
        ) from error
    except DraftConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "DRAFT_VERSION_CONFLICT", "message": "draft changed or is not ready"},
        ) from error
    except DraftIdempotencyConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": "use a new idempotency key for a different commit request",
            },
        ) from error
    except StorageUnavailable as error:
        raise _database_error(error) from error
    return DraftCommitResponse.model_validate(result)


@router.get("/state", response_model=StateResponse)
def get_state(request: Request) -> StateResponse:
    try:
        state = _queries(request).get_state()
    except StorageUnavailable as error:
        raise _database_error(error) from error
    except RecurrenceNeedsConfirmation as error:
        raise _dst_policy_error() from error
    return StateResponse(
        server_now=state.server_now,
        active_occurrences=[
            EventResponse.model_validate(item) for item in state.active_occurrences
        ],
        next_transition_at=state.next_transition_at,
    )


@router.get("/events", response_model=EventListResponse)
def get_events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> EventListResponse:
    try:
        events = _queries(request).get_events(limit, offset)
    except StorageUnavailable as error:
        raise _database_error(error) from error
    except RecurrenceNeedsConfirmation as error:
        raise _dst_policy_error() from error
    return EventListResponse(items=[EventResponse.model_validate(event) for event in events])


@router.get("/occurrences", response_model=EventListResponse)
def get_occurrences(
    request: Request,
    start: Annotated[datetime, Query(alias="from")],
    end: Annotated[datetime, Query(alias="to")],
) -> EventListResponse:
    _validate_window(start, end)
    try:
        events = _queries(request).get_occurrences(start, end)
    except StorageUnavailable as error:
        raise _database_error(error) from error
    except RecurrenceNeedsConfirmation as error:
        raise _dst_policy_error() from error
    return EventListResponse(items=[EventResponse.model_validate(event) for event in events])


@router.post("/occurrences/{occurrence_id}/exceptions", response_model=EventResponse)
def add_occurrence_exception(
    occurrence_id: str, payload: ExceptionRequest, request: Request
) -> EventResponse:
    try:
        occurrence = _commands(request).add_exception(
            occurrence_id,
            payload.exception_type,
            payload.idempotency_key,
        )
    except OccurrenceDoesNotExist as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "OCCURRENCE_NOT_FOUND", "message": "event instance was not found"},
        ) from error
    except OccurrenceExceptionConflict as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "EXCEPTION_CONFLICT",
                "message": "this instance already has a different exception",
            },
        ) from error
    except RecurrenceNeedsConfirmation as error:
        raise _dst_policy_error() from error
    return EventResponse.model_validate(occurrence)


@router.patch("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def update_event(event_id: str, payload: EventPatch, request: Request) -> Response:
    try:
        _commands(request).update_event(
            event_id,
            payload.version,
            payload.model_dump(exclude={"version"}, exclude_unset=True),
        )
    except EventUpdateNotFound as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "EVENT_NOT_FOUND", "message": "event was not found"},
        ) from error
    except EventUpdateConflict as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "VERSION_CONFLICT", "message": "event changed; reload before editing"},
        ) from error
    except EventSeriesHasExceptions as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SERIES_HAS_EXCEPTIONS",
                "message": "resolve this series' exceptions before changing its schedule",
            },
        ) from error
    except InvalidEventUpdate as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_EVENT", "message": "updated fields do not form a valid event"},
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: str,
    request: Request,
    version: int = Query(ge=1),
) -> Response:
    try:
        _commands(request).delete_event(event_id, version)
    except EventUpdateNotFound as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "EVENT_NOT_FOUND", "message": "event was not found"},
        ) from error
    except EventUpdateConflict as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "VERSION_CONFLICT", "message": "event changed; reload before deleting"},
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
