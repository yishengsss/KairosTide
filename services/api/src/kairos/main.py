"""Fresh API composition root; business endpoints are contract-only in T1."""

import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from kairos.api import schemas as s


def create_app(db_path: str | None = None) -> FastAPI:
    path = Path(db_path or os.environ.get("KAIROS_DB_PATH", "var/kairos.sqlite3"))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        yield

    app = FastAPI(title="Kairos API", version="0.1.0", lifespan=lifespan)
    router = APIRouter(prefix="/api/v1", responses={501: {"model": s.ErrorResponse}})

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        error = s.ErrorResponse(
            code="NOT_IMPLEMENTED" if exc.status_code == 501 else "HTTP_ERROR",
            message=str(exc.detail),
            request_id=str(uuid4()),
        )
        return JSONResponse(status_code=exc.status_code, content=error.model_dump())

    @router.get("/health", response_model=s.HealthResponse)
    def health() -> s.HealthResponse:
        with sqlite3.connect(path) as connection:
            connection.execute("SELECT 1 FROM runtime_metadata LIMIT 1").fetchone()
        return s.HealthResponse(status="ok")

    def unavailable() -> None:
        raise HTTPException(status_code=501, detail="This capability is not implemented in the T1 scaffold")

    @router.get("/state", response_model=s.StateResponse)
    def state() -> s.StateResponse:
        unavailable()

    @router.get("/events", response_model=s.EventPage)
    def events(cursor: str | None = None) -> s.EventPage:
        unavailable()

    @router.get("/occurrences", response_model=s.OccurrencePage)
    def occurrences(from_at: str = Query(alias="from"), to_at: str = Query(alias="to")) -> s.OccurrencePage:
        unavailable()

    @router.post("/reminders/{reminder_id}/ack", response_model=s.Reminder)
    def ack(reminder_id: str, body: s.ReminderAckRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> s.Reminder:
        unavailable()

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


app = create_app()
