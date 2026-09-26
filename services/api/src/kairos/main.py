"""Fresh API composition root; business endpoints are contract-only in T1."""

import os
import sqlite3
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kairos.api import schemas as s
from kairos.adapters.clock import SystemClock
from kairos.adapters.persistence.sqlite import SqliteRepository
from kairos.application.reminders import ReminderService, ReminderConflict
from kairos.application.state import StateService
from kairos.domain.state import temporal_phase


def create_app(db_path: str | None = None, *, clock=None, owner_id: str | None = None) -> FastAPI:
    path = Path(db_path or os.environ.get("KAIROS_DB_PATH", "var/kairos.sqlite3"))
    trusted_owner_id = owner_id or os.environ.get("KAIROS_LOCAL_OWNER_ID", "local")
    runtime_clock = clock or SystemClock()
    repository = SqliteRepository(path)
    reminder_service = ReminderService(repository, runtime_clock)

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

    def unavailable() -> None:
        raise HTTPException(status_code=501, detail="This capability is not implemented in the T1 scaffold")

    @router.get("/state", response_model=s.StateResponse)
    def state() -> s.StateResponse:
        snapshot = StateService(repository, runtime_clock, reminder_service).snapshot(trusted_owner_id)
        active = [s.Occurrence(occurrence_id=item.occurrence_id, event_id=item.event_id, version=item.version,
            title=item.title, location=item.location, temporal_phase="active", disposition=item.disposition,
            start_at=item.start_at, end_at=item.end_at) for item in snapshot.active_occurrences]
        due = [s.Reminder(**item) for item in snapshot.due_reminders]
        next_transition = min((item.end_at for item in snapshot.active_occurrences), default=None)
        return s.StateResponse(server_now=snapshot.server_now, state_revision=1, active_occurrences=active,
            due_reminders=due, conflicts=[], next_transition_at=next_transition)

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
        unavailable()

    @router.post("/drafts", response_model=s.DraftResponse)
    def create_draft(body: s.DraftRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.DraftResponse:
        unavailable()

    @router.get("/drafts/{draft_id}", response_model=s.DraftResponse)
    def get_draft(draft_id: str) -> s.DraftResponse:
        unavailable()

    @router.post("/drafts/{draft_id}/clarifications", response_model=s.DraftResponse)
    def clarify(draft_id: str, body: s.ClarificationRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.DraftResponse:
        unavailable()

    @router.patch("/drafts/{draft_id}", response_model=s.DraftResponse)
    def patch_draft(draft_id: str, body: s.DraftPatchRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.DraftResponse:
        unavailable()

    @router.post("/drafts/{draft_id}/commit", response_model=s.DraftCommitResponse)
    def commit_draft(draft_id: str, body: s.DraftCommitRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.DraftCommitResponse:
        unavailable()

    @router.post("/occurrences/{occurrence_id}/exceptions", response_model=s.Occurrence)
    def occurrence_exception(occurrence_id: str, body: s.OccurrenceExceptionRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.Occurrence:
        unavailable()

    @router.post("/event-change-proposals", response_model=s.ChangeProposalResponse)
    def change_proposal(body: s.ChangeProposalRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.ChangeProposalResponse:
        unavailable()

    @router.post("/flexible-tasks", response_model=s.FlexibleTask)
    def flexible_task(body: s.FlexibleTaskRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.FlexibleTask:
        unavailable()

    @router.post("/flexible-task-queries", response_model=s.FlexibleTaskQueryResponse)
    def flexible_query(body: s.FlexibleTaskQueryRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.FlexibleTaskQueryResponse:
        unavailable()

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
    def weather(location_id: str, from_at: str | None = Query(default=None, alias="from"), to_at: str | None = Query(default=None, alias="to")) -> s.WeatherResponse:
        unavailable()

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


app = create_app()
