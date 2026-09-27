import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import cast

from kairos.domain.errors import (
    DatabaseNotInitialized,
    DraftNotFound,
    DraftVersionConflict,
    EventNotFound,
    EventVersionConflict,
    ExceptionConflict,
    IdempotencyKeyReused,
    SeriesHasExceptions,
)
from kairos.domain.models import Event, EventException

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("database timestamps must include a timezone")
    return parsed.astimezone(UTC)


def _event_from_row(row: sqlite3.Row) -> Event:
    recurrence_start_date = row["recurrence_start_date"]
    local_start_time = row["local_start_time"]
    local_end_time = row["local_end_time"]
    until_date = row["until_date"]
    return Event(
        id=row["id"],
        title=row["title"],
        location=row["location"],
        notes=row["notes"],
        timezone=row["timezone"],
        start_at=_as_utc(row["start_at"]),
        end_at=_as_utc(row["end_at"]),
        version=row["version"],
        event_type=row["event_type"],
        recurrence_start_date=date.fromisoformat(recurrence_start_date)
        if recurrence_start_date
        else None,
        local_start_time=time.fromisoformat(local_start_time) if local_start_time else None,
        local_end_time=time.fromisoformat(local_end_time) if local_end_time else None,
        end_day_offset=row["end_day_offset"],
        frequency=row["frequency"],
        weekdays=tuple(json.loads(row["weekdays_json"])),
        until_date=date.fromisoformat(until_date) if until_date else None,
        gap_policy=row["gap_policy"],
        fold_policy=row["fold_policy"],
    )


class SQLiteStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path, timeout=2.0)) as connection:
            for migration_path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
                version = int(migration_path.name.split("_", 1)[0])
                applied = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
                ).fetchone()
                if (
                    applied is not None
                    and connection.execute(
                        "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
                    ).fetchone()
                ):
                    continue
                connection.executescript(migration_path.read_text(encoding="utf-8"))
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise DatabaseNotInitialized
        connection = sqlite3.connect(self.database_path, timeout=2.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _event_select() -> str:
        return """
            SELECT id, title, location, notes, timezone, start_at, end_at, version,
                   event_type, recurrence_start_date, local_start_time, local_end_time,
                   end_day_offset, frequency, weekdays_json, until_date, gap_policy, fold_policy
            FROM events
        """

    def list_events(self, start_before: datetime, end_after: datetime) -> list[Event]:
        start_before = start_before.astimezone(UTC)
        end_after = end_after.astimezone(UTC)
        lower_date = (end_after.date()).isoformat()
        upper_date = (start_before.date()).isoformat()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                self._event_select()
                + """
                WHERE (event_type = 'single' AND start_at < ? AND end_at > ?)
                   OR (event_type = 'recurring'
                       AND recurrence_start_date <= date(?, '+1 day')
                       AND (until_date IS NULL OR until_date >= date(?, '-1 day')))
                ORDER BY start_at, id
                """,
                (start_before.isoformat(), end_after.isoformat(), upper_date, lower_date),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def get_events(self, limit: int, offset: int) -> list[Event]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                self._event_select() + " ORDER BY start_at, id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def get_event(self, event_id: str) -> Event | None:
        with closing(self._connect()) as connection:
            row = connection.execute(self._event_select() + " WHERE id = ?", (event_id,)).fetchone()
        return _event_from_row(row) if row is not None else None

    def get_exceptions(self, event_ids: list[str]) -> list[EventException]:
        if not event_ids:
            return []
        placeholders = ",".join("?" for _ in event_ids)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT event_id, occurrence_key, exception_type FROM event_exceptions "
                f"WHERE event_id IN ({placeholders})",
                event_ids,
            ).fetchall()
        return [
            EventException(row["event_id"], row["occurrence_key"], row["exception_type"])
            for row in rows
        ]

    def get_event_exception(self, event_id: str, occurrence_key: str) -> EventException | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT event_id, occurrence_key, exception_type FROM event_exceptions "
                "WHERE event_id = ? AND occurrence_key = ?",
                (event_id, occurrence_key),
            ).fetchone()
        if row is None:
            return None
        return EventException(row["event_id"], row["occurrence_key"], row["exception_type"])

    def add_exception(
        self,
        event_id: str,
        occurrence_key: str,
        exception_type: str,
        idempotency_key: str,
        created_at: datetime,
    ) -> EventException:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous_request = connection.execute(
                "SELECT event_id, occurrence_key, exception_type FROM event_exceptions "
                "WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if previous_request is not None:
                if (
                    previous_request["event_id"] == event_id
                    and previous_request["occurrence_key"] == occurrence_key
                    and previous_request["exception_type"] == exception_type
                ):
                    connection.commit()
                    return EventException(event_id, occurrence_key, exception_type)
                connection.rollback()
                raise ExceptionConflict
            existing = connection.execute(
                "SELECT exception_type FROM event_exceptions "
                "WHERE event_id = ? AND occurrence_key = ?",
                (event_id, occurrence_key),
            ).fetchone()
            if existing is not None:
                if existing["exception_type"] == exception_type:
                    connection.commit()
                    return EventException(event_id, occurrence_key, exception_type)
                connection.rollback()
                raise ExceptionConflict
            connection.execute(
                "INSERT INTO event_exceptions "
                "(event_id, occurrence_key, exception_type, idempotency_key, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    event_id,
                    occurrence_key,
                    exception_type,
                    idempotency_key,
                    created_at.astimezone(UTC).isoformat(),
                ),
            )
            connection.commit()
        return EventException(event_id, occurrence_key, exception_type)

    def update_event(self, event_id: str, version: int, fields: dict[str, object]) -> Event:
        allowed_columns = {
            "title",
            "location",
            "notes",
            "timezone",
            "start_at",
            "end_at",
            "event_type",
            "recurrence_start_date",
            "local_start_time",
            "local_end_time",
            "end_day_offset",
            "frequency",
            "weekdays_json",
            "until_date",
            "gap_policy",
            "fold_policy",
        }
        if not fields or set(fields) - allowed_columns:
            raise ValueError("event update contains no fields or an unsupported field")
        temporal_fields = allowed_columns - {"title", "location", "notes"}
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT version FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise EventNotFound
            if row["version"] != version:
                connection.rollback()
                raise EventVersionConflict
            if temporal_fields.intersection(fields):
                count = connection.execute(
                    "SELECT count(*) FROM event_exceptions WHERE event_id = ?", (event_id,)
                ).fetchone()[0]
                if count:
                    connection.rollback()
                    raise SeriesHasExceptions
            assignments = ", ".join(f"{column} = ?" for column in fields)
            values = [self._serialize_event_value(value) for value in fields.values()]
            connection.execute(
                f"UPDATE events SET {assignments}, version = version + 1, updated_at = ? "
                "WHERE id = ? AND version = ?",
                (*values, datetime.now(UTC).isoformat(), event_id, version),
            )
            connection.commit()
        updated = self.get_event(event_id)
        if updated is None:
            raise EventNotFound
        return updated

    def delete_event(self, event_id: str, version: int) -> None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT version FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise EventNotFound
            if row["version"] != version:
                connection.rollback()
                raise EventVersionConflict
            connection.execute("DELETE FROM events WHERE id = ?", (event_id,))
            connection.commit()

    def save_draft(self, draft: dict[str, object]) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO planning_drafts
                   (id, revision, status, text, timezone, reference_now, expires_at,
                    answers_json, result_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    draft["id"],
                    draft["revision"],
                    draft["status"],
                    draft["text"],
                    draft["timezone"],
                    self._serialize_event_value(draft["reference_now"]),
                    self._serialize_event_value(draft["expires_at"]),
                    json.dumps(draft.get("answers", {}), ensure_ascii=False),
                    json.dumps(draft["result"], ensure_ascii=False),
                ),
            )
            connection.commit()

    def get_draft(self, draft_id: str) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM planning_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "revision": row["revision"],
            "status": row["status"],
            "text": row["text"],
            "timezone": row["timezone"],
            "reference_now": _as_utc(row["reference_now"]),
            "expires_at": _as_utc(row["expires_at"]),
            "answers": json.loads(row["answers_json"]),
            "result": json.loads(row["result_json"]),
            "committed_key": row["committed_key"],
            "committed_hash": row["committed_hash"],
            "committed_event_ids": json.loads(row["committed_event_ids_json"])
            if row["committed_event_ids_json"]
            else None,
        }

    def update_draft(self, draft: dict[str, object], expected_revision: int) -> bool:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """UPDATE planning_drafts
                   SET revision = ?, status = ?, answers_json = ?, result_json = ?
                   WHERE id = ? AND revision = ? AND status != 'committed'""",
                (
                    draft["revision"],
                    draft["status"],
                    json.dumps(draft.get("answers", {}), ensure_ascii=False),
                    json.dumps(draft["result"], ensure_ascii=False),
                    draft["id"],
                    expected_revision,
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def commit_draft(
        self,
        draft_id: str,
        revision: int,
        idempotency_key: str,
        candidates: list[dict[str, object]],
        created_at: datetime,
    ) -> list[str]:
        request_hash = hashlib.sha256(
            json.dumps(
                {"draft_id": draft_id, "revision": revision, "candidates": candidates},
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ).encode()
        ).hexdigest()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            retry = connection.execute(
                """SELECT request_hash, event_ids_json FROM planning_idempotency
                   WHERE idempotency_key = ?""",
                (idempotency_key,),
            ).fetchone()
            if retry is not None:
                if retry["request_hash"] != request_hash:
                    connection.rollback()
                    raise IdempotencyKeyReused
                connection.commit()
                return cast(list[str], json.loads(retry["event_ids_json"]))
            draft = connection.execute(
                "SELECT revision, status FROM planning_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            if draft is None:
                connection.rollback()
                raise DraftNotFound
            if draft["revision"] != revision or draft["status"] != "ready":
                connection.rollback()
                raise DraftVersionConflict
            now_value = self._serialize_event_value(created_at)
            event_ids: list[str] = []
            for index, candidate in enumerate(candidates):
                event_id = f"{draft_id}-{index + 1}"
                connection.execute(
                    """INSERT INTO events
                       (id, title, location, notes, timezone, start_at, end_at,
                        version, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (
                        event_id,
                        candidate["title"],
                        candidate.get("location"),
                        candidate.get("notes"),
                        candidate["timezone"],
                        self._serialize_event_value(candidate["start_at"]),
                        self._serialize_event_value(candidate["end_at"]),
                        now_value,
                        now_value,
                    ),
                )
                event_ids.append(event_id)
            ids_json = json.dumps(event_ids)
            connection.execute(
                """UPDATE planning_drafts SET status = 'committed', committed_key = ?,
                   committed_hash = ?, committed_event_ids_json = ? WHERE id = ?""",
                (idempotency_key, request_hash, ids_json, draft_id),
            )
            connection.execute(
                """INSERT INTO planning_idempotency
                   (idempotency_key, request_hash, event_ids_json) VALUES (?, ?, ?)""",
                (idempotency_key, request_hash, ids_json),
            )
            connection.commit()
        return event_ids

    @staticmethod
    def _serialize_event_value(value: object) -> object:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("event timestamps must include a timezone")
            return value.astimezone(UTC).isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, time):
            return value.isoformat()
        if isinstance(value, tuple | list):
            return json.dumps(value)
        return value
