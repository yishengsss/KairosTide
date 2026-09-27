"""Fresh API composition root; business endpoints are contract-only in T1."""

import os
import sqlite3
from hashlib import sha256
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kairos.api import schemas as s
from kairos.adapters.clock import SystemClock
from kairos.adapters.persistence.sqlite import SqliteRepository, _occurrence_from_data
from kairos.adapters.ai.mimo import MimoClient, MimoError
from kairos.adapters.ai.assistant_model import MimoToolModel
from kairos.adapters.weather.open_meteo import OpenMeteoWeatherProvider
from kairos.application.weather import WeatherLocationAmbiguous, WeatherService
from kairos.application.tasks import FlexibleTaskService
from kairos.application.assistant_tasks import AssistantService
from kairos.domain.tasks import (IdempotencyConflict as TaskIdempotencyConflict,
                                 InvalidTaskTransition, TaskNotFound, TaskVersionConflict)
from kairos.application.reminders import ReminderService, ReminderConflict
from kairos.application.state import StateService
from kairos.application.occurrence_commands import OccurrenceService
from kairos.application.drafts import DraftService
from kairos.application.draft_commit import DraftCommitService, ConflictReviewRequired
from kairos.application.rigid_input import parse_event_candidate
from kairos.application.image_input import ImageValidationError, validate_image
from kairos.application.event_changes import normalized_changes
from kairos.domain.drafts import Candidate, DraftNotReady, IdempotencyConflict, RevisionConflict
from kairos.domain.events import RecurrenceRule
from kairos.domain.time_rules import overlaps
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from datetime import date, time
from kairos.domain.state import temporal_phase


def create_app(db_path: str | None = None, *, clock=None, owner_id: str | None = None,
               assistant_client=None, assistant_task_model=None, weather_provider=None) -> FastAPI:
    path = Path(db_path or os.environ.get("KAIROS_DB_PATH", "var/kairos.sqlite3"))
    trusted_owner_id = owner_id or os.environ.get("KAIROS_LOCAL_OWNER_ID", "local")
    runtime_clock = clock or SystemClock()
    repository = SqliteRepository(path)
    reminder_service = ReminderService(repository, runtime_clock)
    occurrence_service = OccurrenceService(repository, runtime_clock)
    draft_service = DraftService(repository, runtime_clock)
    draft_commit_service = DraftCommitService(repository, runtime_clock)
    runtime_task_model = assistant_task_model
    if runtime_task_model is None and os.environ.get("MIMO_API_KEY", "").strip():
        runtime_task_model = MimoToolModel(
            os.environ["MIMO_API_KEY"].strip(),
            base_url=os.environ.get("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"),
            model=os.environ.get("MIMO_MODEL", "mimo-v2.6-pro"),
        )
    runtime_task_assistant = AssistantService(runtime_task_model, FlexibleTaskService(repository),
        clock=runtime_clock.now, drafts=draft_service, rigid_events=repository) if runtime_task_model else None
    runtime_assistant = assistant_client if assistant_client is not None else (
        MimoClient.from_environment() if runtime_task_assistant is None else None)
    runtime_weather = WeatherService(weather_provider or OpenMeteoWeatherProvider(), clock=runtime_clock.now)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        yield

    app = FastAPI(title="Kairos API", version="0.1.0", lifespan=lifespan)
    router = APIRouter(prefix="/api/v1", responses={422: {"model": s.ErrorResponse}, 501: {"model": s.ErrorResponse}})

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        error = s.ErrorResponse(
            code="NOT_IMPLEMENTED" if exc.status_code == 501 else "HTTP_ERROR",
            message=str(exc.detail),
            request_id=str(uuid4()),
        )
        return JSONResponse(status_code=exc.status_code, content=error.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        fields: dict[str, str] = {}
        for error in exc.errors():
            path_parts = [str(part) for part in error.get("loc", ()) if part not in {"body", "query", "path", "header", "cookie"}]
            field = ".".join(path_parts) or "request"
            fields[field] = error.get("msg", "Invalid value")
        error = s.ErrorResponse(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            request_id=str(uuid4()),
            field_errors=fields,
        )
        return JSONResponse(status_code=422, content=error.model_dump())

    @router.get("/health", response_model=s.HealthResponse)
    def health() -> s.HealthResponse:
        with sqlite3.connect(path) as connection:
            connection.execute("SELECT 1 FROM runtime_metadata LIMIT 1").fetchone()
        return s.HealthResponse(status="ok")

    @router.post("/assistant/chat", response_model=s.AssistantChatResponse, response_model_exclude_unset=True)
    def assistant_chat(body: s.AssistantChatRequest) -> s.AssistantChatResponse:
        image = None
        if body.image is not None:
            try:
                image = validate_image(body.image.mime_type, body.image.data_base64)
            except ImageValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from None
            if runtime_task_assistant is None:
                raise HTTPException(status_code=503, detail="Image understanding is not configured")
        if runtime_task_assistant is None and runtime_assistant is None:
            raise HTTPException(status_code=503, detail="MiMo is not configured")
        if runtime_task_assistant is not None:
            try:
                result = runtime_task_assistant.handle(trusted_owner_id, body.client_message_id,
                    body.timezone, [item.model_dump() for item in body.messages], image=image)
            except MimoError:
                raise HTTPException(status_code=502, detail="MiMo request failed; please retry") from None
            return s.AssistantChatResponse(answer=result.answer, action_results=[
                {"action": item.action, "status": item.status, "data": item.data, "message": item.message}
                for item in result.action_results],
                draft=_draft_dto(result.draft, runtime_clock.now()) if result.draft is not None else None,
                **({"retain_image": True} if result.retain_image else {}))
        try:
            answer = runtime_assistant.reply([item.model_dump() for item in body.messages])
        except MimoError:
            raise HTTPException(status_code=502, detail="MiMo request failed; please retry") from None
        return s.AssistantChatResponse(answer=answer, action_results=[], draft=None)

    def unavailable() -> None:
        raise HTTPException(status_code=501, detail="This capability is not implemented in the T1 scaffold")

    @router.get("/state", response_model=s.StateResponse)
    def state() -> s.StateResponse:
        snapshot = StateService(repository, runtime_clock, reminder_service).snapshot(trusted_owner_id)
        active = [s.Occurrence(occurrence_id=item.occurrence_id, event_id=item.event_id, version=item.version,
            title=item.title, location=item.location, temporal_phase="active", disposition=item.disposition,
            start_at=item.start_at, end_at=item.end_at) for item in snapshot.active_occurrences]
        due = [s.Reminder(**item) for item in snapshot.due_reminders]
        conflicts = [s.Conflict(
            conflict_id="conf_" + sha256("|".join(member_ids).encode()).hexdigest()[:24],
            member_ids=list(member_ids), snapshot_revision=snapshot.state_revision, selected_id=None,
        ) for member_ids in snapshot.conflicts]
        return s.StateResponse(server_now=snapshot.server_now, state_revision=snapshot.state_revision, active_occurrences=active,
            due_reminders=due, conflicts=conflicts, next_transition_at=snapshot.next_transition_at)

    @router.get("/events", response_model=s.EventPage)
    def events(cursor: str | None = None) -> s.EventPage:
        offset = _decode_cursor(cursor)
        all_events = repository.list_events(trusted_owner_id)
        page = all_events[offset:offset + 50]
        items = [s.Event(event_id=item.event_id, version=item.version, title=item.title, location=item.location,
            start_at=item.start_at, end_at=item.end_at, recurrence=_recurrence_dto(item.recurrence, item.timezone)) for item in page]
        next_cursor = _encode_cursor(offset + 50) if offset + 50 < len(all_events) else None
        return s.EventPage(items=items, next_cursor=next_cursor)

    @router.get("/occurrences", response_model=s.OccurrencePage)
    def occurrences(from_at: datetime = Query(alias="from"), to_at: datetime = Query(alias="to"), cursor: str | None = None) -> s.OccurrencePage:
        if from_at.tzinfo is None or to_at.tzinfo is None or to_at <= from_at or to_at - from_at > timedelta(days=62):
            raise HTTPException(status_code=422, detail="Query window must be aware, ordered, and no wider than 62 days")
        now = runtime_clock.now()
        items = repository.list_occurrences(trusted_owner_id, from_at, to_at)
        visible = [item for item in items if item.disposition == "scheduled"]
        offset = _decode_cursor(cursor)
        page = visible[offset:offset + 100]
        results = [s.Occurrence(occurrence_id=item.occurrence_id, event_id=item.event_id, version=item.version,
            title=item.title, location=item.location, temporal_phase=temporal_phase(item, now),
            disposition=item.disposition, start_at=item.start_at, end_at=item.end_at) for item in page]
        next_cursor = _encode_cursor(offset + 100) if offset + 100 < len(visible) else None
        return s.OccurrencePage(items=results, next_cursor=next_cursor)

    @router.post("/reminders/{reminder_id}/ack", response_model=s.ReminderAckResponse)
    def ack(reminder_id: str, body: s.ReminderAckRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.Reminder:
        try:
            result = reminder_service.acknowledge(trusted_owner_id, reminder_id, body.expected_version,
                                                  body.schedule_revision, idempotency_key)
        except KeyError:
            raise HTTPException(status_code=404, detail="Reminder not found")
        except ReminderConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return s.ReminderAckResponse(**result)

    @router.post("/conflict-decisions", response_model=s.ConflictDecisionResponse)
    def decide_conflict(body: s.ConflictDecisionRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.ConflictDecisionResponse:
        if len(set(body.member_ids)) != len(body.member_ids):
            raise HTTPException(status_code=422, detail="Conflict members must be unique")
        try:
            result = repository.decide_conflict(trusted_owner_id, body.member_ids, body.selected_id,
                body.snapshot_revision, body.source_action_id, idempotency_key, runtime_clock.now())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        affected = [s.Occurrence(
            occurrence_id=item.occurrence_id, event_id=item.event_id, version=item.version,
            title=item.title, location=item.location, temporal_phase=temporal_phase(item, runtime_clock.now()),
            disposition=item.disposition, start_at=item.start_at, end_at=item.end_at,
        ) for item in (_occurrence_from_data(data) for data in result["affected_occurrences"])]
        return s.ConflictDecisionResponse(decision_id=result["decision_id"], selected_id=result["selected_id"],
            affected_occurrences=affected, state_revision=result["state_revision"])

    @router.post("/drafts", response_model=s.DraftResponse)
    def create_draft(body: s.DraftRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.DraftResponse:
        if body.intent != "create_rigid_event":
            raise HTTPException(status_code=422, detail="Only an explicit fixed-event creation request can open a rigid draft")
        try:
            candidate = parse_event_candidate(body.text, body.timezone, runtime_clock.now())
            digest = sha256(f"{body.conversation_id}|{body.source_message_id}|{body.intent}|{body.text}|{body.timezone}".encode()).hexdigest()
            draft = draft_service.create(trusted_owner_id, [candidate], body.source_message_id,
                                         idempotency_key, digest)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return _draft_dto(draft, runtime_clock.now())

    @router.get("/drafts/{draft_id}", response_model=s.DraftResponse)
    def get_draft(draft_id: str) -> s.DraftResponse:
        draft = repository.get_draft(trusted_owner_id, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        return _draft_dto(draft, runtime_clock.now())

    @router.post("/drafts/{draft_id}/clarifications", response_model=s.DraftResponse)
    def clarify(draft_id: str, body: s.ClarificationRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.DraftResponse:
        draft = repository.get_draft(trusted_owner_id, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        if len(draft.candidates) != 1:
            raise HTTPException(status_code=422, detail="Clarification must identify a candidate in a multi-event draft")
        try:
            changes = _candidate_changes(body.answers)
            updated = draft_service.update_candidate(trusted_owner_id, draft_id, body.revision,
                                                      draft.candidates[0].candidate_id, **changes)
        except RevisionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return _draft_dto(updated, runtime_clock.now())

    @router.patch("/drafts/{draft_id}", response_model=s.DraftResponse)
    def patch_draft(draft_id: str, body: s.DraftPatchRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.DraftResponse:
        try:
            if len(body.operations) != 1:
                raise ValueError("Submit one targeted candidate operation per request")
            operation = body.operations[0]
            if operation.action == "update_candidate":
                if not operation.candidate_id:
                    raise ValueError("candidate_id is required")
                updated = draft_service.update_candidate(trusted_owner_id, draft_id, body.revision,
                    operation.candidate_id, **_candidate_changes(operation.changes or {}))
            elif operation.action == "remove_candidate":
                if not operation.candidate_id:
                    raise ValueError("candidate_id is required")
                updated = draft_service.remove_candidate(trusted_owner_id, draft_id, body.revision,
                                                         operation.candidate_id)
            else:
                if not operation.changes or not operation.candidate_id:
                    raise ValueError("candidate_id and candidate fields are required")
                values = _candidate_changes(operation.changes)
                updated = draft_service.add_candidate(trusted_owner_id, draft_id, body.revision,
                    Candidate(operation.candidate_id, values.get("title"), values.get("location"),
                              values.get("start_at"), values.get("end_at"), values.get("timezone"),
                              values.get("recurrence")))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except RevisionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return _draft_dto(updated, runtime_clock.now())

    @router.post("/drafts/{draft_id}/commit", response_model=s.DraftCommitResponse)
    def commit_draft(draft_id: str, body: s.DraftCommitRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.DraftCommitResponse:
        try:
            result = draft_commit_service.commit(trusted_owner_id, draft_id, body.revision,
                body.confirmed_candidate_ids, body.confirmation_digest, idempotency_key,
                body.conflict_acceptance)
        except KeyError:
            raise HTTPException(status_code=404, detail="Draft not found") from None
        except ConflictReviewRequired as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc),
                "conflict_pairs": exc.conflict_pairs, "conflict_acceptance": exc.acceptance_token}) from None
        except (RevisionConflict, IdempotencyConflict) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except (DraftNotReady, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return s.DraftCommitResponse(draft_id=result.draft_id, revision=result.revision,
            resources=[s.CommittedResource(resource_type="event", resource_id=event_id, version=1)
                       for event_id in result.event_ids])

    @router.post("/occurrences/{occurrence_id}/exceptions", response_model=s.Occurrence)
    def occurrence_exception(occurrence_id: str, body: s.OccurrenceExceptionRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.Occurrence:
        try:
            item = occurrence_service.set_exception(trusted_owner_id, occurrence_id, body.type,
                body.expected_version, body.source_action_id, idempotency_key)
        except KeyError:
            raise HTTPException(status_code=404, detail="Occurrence not found") from None
        except RevisionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return _occurrence_dto(item, runtime_clock.now())

    @router.post("/event-change-proposals", response_model=s.ChangeProposalResponse)
    def change_proposal(body: s.ChangeProposalRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.ChangeProposalResponse:
        try:
            changes = normalized_changes(body.action, body.scope, body.changes)
            result = repository.propose_event_change(trusted_owner_id, body.target_id, body.scope,
                body.expected_version, body.action, changes, body.source_message_id,
                idempotency_key, runtime_clock.now())
        except KeyError:
            raise HTTPException(status_code=404, detail="Event or occurrence not found") from None
        except (RevisionConflict, IdempotencyConflict) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return s.ChangeProposalResponse(**result)

    @router.get("/event-change-proposals/{proposal_id}", response_model=s.ChangeProposalResponse)
    def get_change_proposal(proposal_id: str) -> s.ChangeProposalResponse:
        result = repository.get_event_change_proposal(trusted_owner_id, proposal_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Change proposal not found")
        return s.ChangeProposalResponse(**result)

    @router.post("/event-change-proposals/{proposal_id}/commit", response_model=s.ChangeProposalCommitResponse)
    def commit_change_proposal(proposal_id: str, body: s.ChangeProposalCommitRequest,
                               idempotency_key: str = Header(alias="Idempotency-Key")) -> s.ChangeProposalCommitResponse:
        try:
            result = repository.commit_event_change(trusted_owner_id, proposal_id, body.revision,
                body.confirmation_digest, body.source_action_id, idempotency_key, runtime_clock.now())
        except KeyError:
            raise HTTPException(status_code=404, detail="Change proposal not found") from None
        except (RevisionConflict, IdempotencyConflict) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return s.ChangeProposalCommitResponse(**result)

    @router.post("/flexible-tasks", response_model=s.FlexibleTask)
    def flexible_task(body: s.FlexibleTaskRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.FlexibleTask:
        try:
            record = FlexibleTaskService(repository).create(trusted_owner_id, body.title, body.deadline,
                body.deadline_precision, body.timezone, body.source_message_id, idempotency_key)
        except TaskIdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return _flexible_task_dto(record)

    @router.get("/flexible-tasks", response_model=s.FlexibleTaskPage)
    def list_flexible_tasks() -> s.FlexibleTaskPage:
        records = FlexibleTaskService(repository).list(trusted_owner_id)
        return s.FlexibleTaskPage(items=[_flexible_task_dto(item) for item in records])

    @router.post("/flexible-tasks/{task_id}/lifecycle", response_model=s.FlexibleTask)
    def transition_flexible_task(task_id: str, body: s.FlexibleTaskLifecycleRequest,
                                 idempotency_key: str = Header(alias="Idempotency-Key")) -> s.FlexibleTask:
        try:
            record = FlexibleTaskService(repository).transition(trusted_owner_id, task_id,
                body.status, body.expected_version, idempotency_key)
        except TaskNotFound:
            raise HTTPException(status_code=404, detail="Task not found") from None
        except (TaskIdempotencyConflict, TaskVersionConflict, InvalidTaskTransition) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return _flexible_task_dto(record)

    @router.post("/flexible-task-queries", response_model=s.FlexibleTaskQueryResponse)
    def flexible_query(body: s.FlexibleTaskQueryRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.FlexibleTaskQueryResponse:
        records = FlexibleTaskService(repository).list(trusted_owner_id)
        return s.FlexibleTaskQueryResponse(items=[_flexible_task_dto(item) for item in records],
                                           source_message_id=body.source_message_id)

    @router.post("/conversations", response_model=s.Conversation)
    def conversation(idempotency_key: str = Header(alias="Idempotency-Key")) -> s.Conversation:
        unavailable()

    @router.post("/conversations/{conversation_id}/messages", response_model=s.MessageResponse)
    def send_message(conversation_id: str, body: s.MessageRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.MessageResponse:
        unavailable()

    @router.get("/conversations/{conversation_id}/messages", response_model=s.MessagePage)
    def get_messages(conversation_id: str, cursor: str | None = None) -> s.MessagePage:
        unavailable()

    @router.get("/weather", response_model=s.WeatherResponse)
    def weather(location_id: str, from_at: datetime | None = Query(default=None, alias="from"),
                to_at: datetime | None = Query(default=None, alias="to")) -> s.WeatherResponse:
        if not location_id.strip():
            raise HTTPException(status_code=422, detail="An explicit city is required")
        try:
            result = runtime_weather.query(location_id, from_at, to_at)
        except WeatherLocationAmbiguous as exc:
            return s.WeatherResponse(
                location_id=location_id, availability="unavailable", source="Open-Meteo",
                fetched_at=runtime_clock.now(), observations=[],
                attribution="Weather data by Open-Meteo (CC BY 4.0)",
                detail="多个地点名称匹配，请选择一个地点。",
                location_choices=[s.WeatherPlaceChoice(name=choice.name, latitude=choice.latitude,
                    longitude=choice.longitude, timezone=choice.timezone, country=choice.country,
                    admin1=choice.admin1) for choice in exc.choices],
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        observations = [s.WeatherObservation(
            kind="current" if from_at is None else "forecast", condition=item.condition,
            cloud_cover=item.cloud_cover, precipitation=item.precipitation, visibility=item.visibility,
            observed_at=item.observed_at, valid_until=item.valid_until,
        ) for item in result.observations]
        location_label = None
        timezone_name = None
        if result.location is not None:
            location_label = ", ".join(value for value in
                (result.location.name, result.location.admin1, result.location.country) if value)
            timezone_name = result.location.timezone
        return s.WeatherResponse(
            location_id=result.location.name if result.location else location_id,
            availability=result.availability, source=result.source, fetched_at=result.fetched_at,
            observations=observations, location_label=location_label, timezone=timezone_name,
            attribution=result.attribution, detail=result.detail, location_choices=[],
        )

    app.include_router(router)
    return app


def _encode_cursor(offset: int) -> str:
    return f"p{offset}"


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.startswith("p") or not cursor[1:].isdigit():
        raise HTTPException(status_code=422, detail="Invalid cursor")
    return int(cursor[1:])


def _recurrence_dto(rule, timezone: str):
    if rule is None:
        return None
    return s.Recurrence(frequency=rule.frequency, timezone=timezone, starts_on=rule.starts_on.isoformat(),
        ends_on=rule.ends_on.isoformat() if rule.ends_on else None,
        weekdays=list(rule.weekdays) if rule.frequency == "weekly" else None,
        dst_gap_policy=rule.gap_policy, dst_fold_policy=rule.fold_policy)


def _occurrence_dto(item, now: datetime):
    return s.Occurrence(occurrence_id=item.occurrence_id, event_id=item.event_id, version=item.version,
        title=item.title, location=item.location, temporal_phase=temporal_phase(item, now),
        disposition=item.disposition, start_at=item.start_at, end_at=item.end_at)


def _flexible_task_dto(item):
    return s.FlexibleTask(task_id=item.task_id, version=item.version, title=item.title,
        deadline=item.deadline, deadline_precision=item.deadline_precision, timezone=item.timezone,
        lifecycle_status=item.lifecycle_status)


def _draft_dto(draft, now: datetime) -> s.DraftResponse:
    status = "expired" if draft.status != "committed" and draft.expires_at <= now else draft.status
    questions = []
    for candidate in draft.candidates:
        for field in candidate.missing_fields:
            questions.append(f"{candidate.candidate_id}: 请补充 {field}")
    return s.DraftResponse(draft_id=draft.draft_id, revision=draft.revision, status=status,
        reference_now=draft.reference_now, expires_at=draft.expires_at,
        candidates=[s.DraftCandidate(candidate_id=item.candidate_id, title=item.title,
            location=item.location, start_at=item.start_at, end_at=item.end_at,
            timezone=item.timezone, recurrence=_recurrence_dto(item.recurrence, item.timezone or "UTC"),
            missing_fields=list(item.missing_fields)) for item in draft.candidates],
        questions=questions, related_action_ids=[], confirmation_digest=draft.confirmation_digest)


def _candidate_changes(values: dict) -> dict:
    allowed = {"title", "location", "start_at", "end_at", "timezone", "recurrence"}
    if not values or set(values) - allowed:
        raise ValueError("Unsupported or empty candidate changes")
    changes = dict(values)
    for field in ("start_at", "end_at"):
        if field in changes and changes[field] is not None:
            if not isinstance(changes[field], str):
                raise ValueError(f"{field} must be an ISO timestamp")
            changes[field] = datetime.fromisoformat(changes[field])
            if changes[field].tzinfo is None:
                raise ValueError(f"{field} must include a timezone offset")
    if "timezone" in changes and changes["timezone"]:
        ZoneInfo(changes["timezone"])
    if "recurrence" in changes and changes["recurrence"] is not None:
        value = changes["recurrence"]
        if not isinstance(value, dict):
            raise ValueError("recurrence must be an object")
        changes["recurrence"] = RecurrenceRule(value["frequency"], date.fromisoformat(value["starts_on"]),
            date.fromisoformat(value["ends_on"]) if value.get("ends_on") else None,
            tuple(value.get("weekdays") or ()), time.fromisoformat(value["local_start"]),
            time.fromisoformat(value["local_end"]), int(value.get("end_day_offset", 0)),
            value.get("gap_policy"), value.get("fold_policy"))
    return changes


app = create_app()
