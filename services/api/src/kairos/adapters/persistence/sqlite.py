"""Owner-scoped SQLite store with atomic draft commit and stable occurrences."""

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from kairos.application.draft_commit import CommitResult, ConflictReviewRequired
from kairos.domain.conflicts import pairs
from kairos.domain.attention import conflict_groups, state_revision
from kairos.domain.drafts import Candidate, Draft, DraftNotReady, IdempotencyConflict, RevisionConflict, make_draft
from kairos.domain.events import EventSeries, Occurrence, RecurrenceRule
from kairos.domain.occurrence_identity import new_occurrence_id
from kairos.domain.recurrence import expand_slots
from kairos.domain.time_rules import overlaps
from kairos.domain.tasks import (AmbiguousTaskTitle, FlexibleTaskRecord, IdempotencyConflict as TaskIdempotencyConflict,
                                 InvalidTaskTransition, TaskLifecycleStatus, TaskNotFound,
                                 TaskVersionConflict, normalized_title, validate_task_transition)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must be aware")
    return value.astimezone(UTC).isoformat()


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(data) -> str:
    return hashlib.sha256(_json(data).encode()).hexdigest()


def _recurrence_to_data(rule: RecurrenceRule | None):
    if rule is None:
        return None
    return {
        "frequency": rule.frequency, "starts_on": rule.starts_on.isoformat(),
        "ends_on": rule.ends_on.isoformat() if rule.ends_on else None,
        "weekdays": list(rule.weekdays), "local_start": rule.local_start.isoformat(),
        "local_end": rule.local_end.isoformat(), "end_day_offset": rule.end_day_offset,
        "gap_policy": rule.gap_policy, "fold_policy": rule.fold_policy,
    }


def _recurrence_from_data(value) -> RecurrenceRule | None:
    if value is None:
        return None
    return RecurrenceRule(value["frequency"], date.fromisoformat(value["starts_on"]),
                          date.fromisoformat(value["ends_on"]) if value["ends_on"] else None,
                          tuple(value["weekdays"]), time.fromisoformat(value["local_start"]),
                          time.fromisoformat(value["local_end"]), value["end_day_offset"],
                          value["gap_policy"], value["fold_policy"])


def _candidate_to_data(candidate: Candidate) -> dict:
    return {
        "candidate_id": candidate.candidate_id, "title": candidate.title, "location": candidate.location,
        "start_at": _iso(candidate.start_at) if candidate.start_at else None,
        "end_at": _iso(candidate.end_at) if candidate.end_at else None,
        "timezone": candidate.timezone, "recurrence": _recurrence_to_data(candidate.recurrence),
    }


def _candidate_from_data(data: dict) -> Candidate:
    return Candidate(data["candidate_id"], data["title"], data["location"],
                     datetime.fromisoformat(data["start_at"]) if data["start_at"] else None,
                     datetime.fromisoformat(data["end_at"]) if data["end_at"] else None,
                     data["timezone"], _recurrence_from_data(data["recurrence"]))


def _event_from_row(row: sqlite3.Row) -> EventSeries:
    return EventSeries(row["event_id"], row["owner_id"], row["version"], row["title"], row["location"],
                       row["timezone"], datetime.fromisoformat(row["start_at"]),
                       datetime.fromisoformat(row["end_at"]),
                       _recurrence_from_data(json.loads(row["recurrence_json"]) if row["recurrence_json"] else None))


def _occurrence_from_row(row: sqlite3.Row) -> Occurrence:
    return Occurrence(row["occurrence_id"], row["event_id"], row["owner_id"], row["original_slot"],
                      datetime.fromisoformat(row["start_at"]), datetime.fromisoformat(row["end_at"]),
                      row["title"], row["location"], row["version"], row["schedule_revision"], row["disposition"])


def _occurrence_to_data(item: Occurrence) -> dict:
    return {
        "occurrence_id": item.occurrence_id, "event_id": item.event_id, "owner_id": item.owner_id,
        "original_slot": item.original_slot, "start_at": _iso(item.start_at), "end_at": _iso(item.end_at),
        "title": item.title, "location": item.location, "version": item.version,
        "schedule_revision": item.schedule_revision, "disposition": item.disposition,
    }


def _occurrence_from_data(value: dict) -> Occurrence:
    return Occurrence(value["occurrence_id"], value["event_id"], value["owner_id"], value["original_slot"],
                      datetime.fromisoformat(value["start_at"]), datetime.fromisoformat(value["end_at"]),
                      value["title"], value["location"], value["version"], value["schedule_revision"],
                      value["disposition"])


def _candidate_event_id(draft_id: str, candidate_id: str) -> str:
    return f"evt_{uuid5(NAMESPACE_URL, f'kairos/draft/{draft_id}/{candidate_id}').hex}"


class SqliteRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._apply_migrations()

    def _apply_migrations(self) -> None:
        migration_dir = Path(__file__).resolve().parents[4] / "migrations"
        files = sorted(migration_dir.glob("[0-9][0-9][0-9]_*.sql"))
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)")
            applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
            for migration in files:
                version = migration.name
                if version in applied:
                    continue
                # 001 is idempotent and also bootstraps databases created before the
                # migration ledger existed. Later migrations are only applied once.
                connection.executescript(migration.read_text())
                connection.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> FlexibleTaskRecord:
        precision = row["deadline_precision"]
        value = row["deadline_value"]
        if precision == "date":
            deadline = date.fromisoformat(value)
        elif precision == "instant":
            deadline = datetime.fromisoformat(value)
        else:
            deadline = None
        return FlexibleTaskRecord(row["task_id"], row["owner_id"], row["version"], row["title"],
                                  deadline, precision, row["timezone"], row["source_message_id"],
                                  row["lifecycle_status"])

    @staticmethod
    def _task_data(task: FlexibleTaskRecord) -> dict:
        return {"task_id": task.task_id, "owner_id": task.owner_id, "version": task.version,
                "title": task.title, "deadline": task.deadline.isoformat() if task.deadline else None,
                "deadline_precision": task.deadline_precision, "timezone": task.timezone,
                "source_message_id": task.source_message_id, "lifecycle_status": task.lifecycle_status}

    @staticmethod
    def _task_from_data(data: dict) -> FlexibleTaskRecord:
        precision = data["deadline_precision"]
        value = data["deadline"]
        deadline = date.fromisoformat(value) if precision == "date" else (
            datetime.fromisoformat(value) if precision == "instant" else None)
        return FlexibleTaskRecord(data["task_id"], data["owner_id"], data["version"], data["title"],
                                  deadline, precision, data["timezone"], data["source_message_id"],
                                  data.get("lifecycle_status", "planned"))

    def create_flexible_task(self, record: FlexibleTaskRecord, idempotency_key: str,
                             request_hash: str) -> FlexibleTaskRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                previous = self._idempotent(connection, record.owner_id, "flexible_task_create", idempotency_key,
                                            request_hash)
            except IdempotencyConflict as exc:
                raise TaskIdempotencyConflict(str(exc)) from exc
            if previous is not None:
                return self._task_from_data(previous)
            connection.execute("""INSERT INTO flexible_tasks
                (task_id, owner_id, version, title, deadline_value, deadline_precision, timezone, source_message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (record.task_id, record.owner_id, record.version, record.title,
                 record.deadline.isoformat() if record.deadline else None, record.deadline_precision,
                 record.timezone, record.source_message_id))
            self._save_idempotent(connection, record.owner_id, "flexible_task_create", idempotency_key,
                                  request_hash, self._task_data(record))
            return record

    def list_flexible_tasks(self, owner_id: str) -> list[FlexibleTaskRecord]:
        with self._connect() as connection:
            rows = connection.execute("""SELECT * FROM flexible_tasks WHERE owner_id = ?
                ORDER BY CASE deadline_precision WHEN 'date' THEN deadline_value
                     WHEN 'instant' THEN deadline_value ELSE '9999-12-31' END, task_id""", (owner_id,)).fetchall()
            return [self._task_from_row(row) for row in rows]

    def update_flexible_task_by_title(self, owner_id: str, title: str, changes: dict,
                                      source_message_id: str | None, idempotency_key: str,
                                      request_hash: str) -> FlexibleTaskRecord:
        return self._mutate_flexible_task(owner_id, title, changes, source_message_id, idempotency_key,
                                          request_hash, delete=False)

    def delete_flexible_task_by_title(self, owner_id: str, title: str, source_message_id: str | None,
                                     idempotency_key: str, request_hash: str) -> FlexibleTaskRecord:
        return self._mutate_flexible_task(owner_id, title, {}, source_message_id, idempotency_key,
                                          request_hash, delete=True)

    def _mutate_flexible_task(self, owner_id: str, title: str, changes: dict,
                              source_message_id: str | None, idempotency_key: str,
                              request_hash: str, *, delete: bool) -> FlexibleTaskRecord:
        operation = "flexible_task_delete" if delete else "flexible_task_update"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                previous = self._idempotent(connection, owner_id, operation, idempotency_key, request_hash)
            except IdempotencyConflict as exc:
                raise TaskIdempotencyConflict(str(exc)) from exc
            if previous is not None:
                return self._task_from_data(previous)
            rows = connection.execute("SELECT * FROM flexible_tasks WHERE owner_id = ?", (owner_id,)).fetchall()
            matches = [row for row in rows if normalized_title(row["title"]) == normalized_title(title)]
            if not matches:
                raise TaskNotFound(title)
            if len(matches) > 1:
                raise AmbiguousTaskTitle(title)
            current = self._task_from_row(matches[0])
            if delete:
                connection.execute("DELETE FROM flexible_tasks WHERE owner_id = ? AND task_id = ?",
                                   (owner_id, current.task_id))
                result = current
            else:
                values = {"title": current.title, "deadline": current.deadline,
                          "deadline_precision": current.deadline_precision, "timezone": current.timezone}
                values.update(changes)
                updated = FlexibleTaskRecord(current.task_id, owner_id, current.version + 1,
                    values["title"], values["deadline"], values["deadline_precision"], values["timezone"],
                    source_message_id or current.source_message_id, current.lifecycle_status)
                connection.execute("""UPDATE flexible_tasks SET version = ?, title = ?, deadline_value = ?,
                    deadline_precision = ?, timezone = ?, source_message_id = ?
                    WHERE owner_id = ? AND task_id = ? AND version = ?""",
                    (updated.version, updated.title, updated.deadline.isoformat() if updated.deadline else None,
                     updated.deadline_precision, updated.timezone, updated.source_message_id,
                     owner_id, current.task_id, current.version))
                result = updated
            self._save_idempotent(connection, owner_id, operation, idempotency_key, request_hash,
                                  self._task_data(result))
            return result

    def transition_flexible_task(self, owner_id: str, task_id: str, target: TaskLifecycleStatus,
                                 expected_version: int, idempotency_key: str,
                                 request_hash: str) -> FlexibleTaskRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                previous = self._idempotent(connection, owner_id, "flexible_task_lifecycle",
                                            idempotency_key, request_hash)
            except IdempotencyConflict as exc:
                raise TaskIdempotencyConflict(str(exc)) from exc
            if previous is not None:
                return self._task_from_data(previous)
            row = connection.execute("SELECT * FROM flexible_tasks WHERE owner_id = ? AND task_id = ?",
                                     (owner_id, task_id)).fetchone()
            if row is None:
                raise TaskNotFound(task_id)
            current = self._task_from_row(row)
            if current.version != expected_version:
                raise TaskVersionConflict("task version changed")
            validate_task_transition(current.lifecycle_status, target)
            updated = FlexibleTaskRecord(current.task_id, owner_id, current.version + 1,
                current.title, current.deadline, current.deadline_precision, current.timezone,
                current.source_message_id, target)
            cursor = connection.execute("""UPDATE flexible_tasks SET version = ?, lifecycle_status = ?
                WHERE owner_id = ? AND task_id = ? AND version = ?""",
                (updated.version, target, owner_id, task_id, expected_version))
            if cursor.rowcount != 1:
                raise TaskVersionConflict("task version changed")
            self._save_idempotent(connection, owner_id, "flexible_task_lifecycle", idempotency_key,
                                  request_hash, self._task_data(updated))
            return updated

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def save_draft(self, draft: Draft) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO drafts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (draft.draft_id, draft.owner_id, draft.revision, draft.source_message_id, _iso(draft.reference_now),
                 _iso(draft.expires_at), draft.status, draft.confirmation_digest,
                 _json([_candidate_to_data(candidate) for candidate in draft.candidates])),
            )

    def create_draft_idempotent(self, draft: Draft, idempotency_key: str, request_hash: str) -> Draft:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._idempotent(connection, draft.owner_id, "draft_create", idempotency_key, request_hash)
            if previous is not None:
                row = connection.execute("SELECT * FROM drafts WHERE owner_id = ? AND draft_id = ?",
                                         (draft.owner_id, previous["draft_id"])).fetchone()
                if row is None:
                    raise RevisionConflict("saved draft no longer exists")
                return self._draft_from_row(row)
            connection.execute(
                "INSERT INTO drafts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (draft.draft_id, draft.owner_id, draft.revision, draft.source_message_id, _iso(draft.reference_now),
                 _iso(draft.expires_at), draft.status, draft.confirmation_digest,
                 _json([_candidate_to_data(candidate) for candidate in draft.candidates])),
            )
            self._save_idempotent(connection, draft.owner_id, "draft_create", idempotency_key,
                                  request_hash, {"draft_id": draft.draft_id})
            return draft

    @staticmethod
    def _draft_from_row(row: sqlite3.Row) -> Draft:
        return Draft(row["draft_id"], row["owner_id"], row["revision"], row["source_message_id"],
                     datetime.fromisoformat(row["reference_now"]), datetime.fromisoformat(row["expires_at"]),
                     tuple(_candidate_from_data(item) for item in json.loads(row["candidates_json"])),
                     row["status"], row["confirmation_digest"])

    def get_draft(self, owner_id: str, draft_id: str) -> Draft | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM drafts WHERE owner_id = ? AND draft_id = ?", (owner_id, draft_id)).fetchone()
            return self._draft_from_row(row) if row else None

    def update_draft(self, draft: Draft, expected_revision: int) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE drafts SET revision = ?, status = ?, confirmation_digest = ?, candidates_json = ?
                   WHERE draft_id = ? AND owner_id = ? AND revision = ? AND status != 'committed'""",
                (draft.revision, draft.status, draft.confirmation_digest,
                 _json([_candidate_to_data(candidate) for candidate in draft.candidates]), draft.draft_id,
                 draft.owner_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RevisionConflict("draft changed during edit")

    def list_events(self, owner_id: str) -> list[EventSeries]:
        with self._connect() as connection:
            return [_event_from_row(row) for row in connection.execute(
                "SELECT * FROM events WHERE owner_id = ? AND deleted = 0 ORDER BY event_id", (owner_id,)).fetchall()]

    @staticmethod
    def _register_slots(connection: sqlite3.Connection, event: EventSeries, start: datetime, end: datetime) -> None:
        for slot in expand_slots(event, start, end):
            connection.execute(
                """INSERT OR IGNORE INTO occurrences
                   (occurrence_id, owner_id, event_id, original_slot, start_at, end_at, version, schedule_revision, disposition)
                   VALUES (?, ?, ?, ?, ?, ?, 1, 1, 'scheduled')""",
                (new_occurrence_id(event.event_id, slot.original_slot), event.owner_id, event.event_id,
                 slot.original_slot, _iso(slot.start_at), _iso(slot.end_at)),
            )

    def _occurrences_in(self, connection: sqlite3.Connection, owner_id: str, start: datetime, end: datetime) -> list[Occurrence]:
        for row in connection.execute("SELECT * FROM events WHERE owner_id = ? AND deleted = 0", (owner_id,)).fetchall():
            self._register_slots(connection, _event_from_row(row), start, end)
        rows = connection.execute(
            """SELECT o.*, COALESCE(o.title_override, e.title) AS title,
                      CASE WHEN o.location_override_set = 1 THEN o.location_override ELSE e.location END AS location
               FROM occurrences o JOIN events e ON e.event_id = o.event_id
               WHERE o.owner_id = ? AND e.deleted = 0 AND o.start_at < ? AND ? < o.end_at
               ORDER BY o.start_at, o.occurrence_id""", (owner_id, _iso(end), _iso(start)),
        ).fetchall()
        return [_occurrence_from_row(row) for row in rows]

    def list_occurrences(self, owner_id: str, start: datetime, end: datetime) -> list[Occurrence]:
        if end <= start or start.tzinfo is None or end.tzinfo is None:
            raise ValueError("invalid aware query window")
        with self._connect() as connection:
            return self._occurrences_in(connection, owner_id, start, end)

    def ensure_reminder(self, owner_id: str, occurrence: Occurrence, now: datetime) -> dict:
        reminder_id = f"rem_{uuid5(NAMESPACE_URL, f'kairos/reminder/{owner_id}/{occurrence.occurrence_id}/{occurrence.schedule_revision}').hex}"
        with self._connect() as connection:
            connection.execute("""INSERT OR IGNORE INTO reminders
                (reminder_id, owner_id, occurrence_id, occurrence_version, schedule_revision)
                VALUES (?, ?, ?, ?, ?)""", (reminder_id, owner_id, occurrence.occurrence_id,
                                                occurrence.version, occurrence.schedule_revision))
            row = connection.execute("""SELECT r.*, o.version AS current_version, o.schedule_revision AS current_schedule,
                e.title, e.location, o.start_at FROM reminders r JOIN occurrences o ON o.occurrence_id = r.occurrence_id
                JOIN events e ON e.event_id = o.event_id WHERE r.owner_id = ? AND r.reminder_id = ?""",
                (owner_id, reminder_id)).fetchone()
            if row is None or row["current_version"] != row["occurrence_version"] or row["current_schedule"] != row["schedule_revision"]:
                if row is not None:
                    connection.execute("UPDATE reminders SET acknowledged_at = ? WHERE reminder_id = ? AND acknowledged_at IS NULL",
                                       (_iso(now), reminder_id))
                return None
            start = datetime.fromisoformat(row["start_at"])
            minutes = max(0, int((start - now).total_seconds() // 60))
            return {"reminder_id": row["reminder_id"], "occurrence_id": row["occurrence_id"],
                    "version": row["occurrence_version"], "schedule_revision": row["schedule_revision"],
                    "acknowledged_at": datetime.fromisoformat(row["acknowledged_at"]) if row["acknowledged_at"] else None,
                    "event_title": row["title"], "location": row["location"], "start_at": start,
                    "minutes_until_start": minutes}

    def acknowledge_reminder(self, owner_id: str, reminder_id: str, expected_version: int,
                             schedule_revision: int, idempotency_key: str, now: datetime) -> dict:
        request_hash = _hash([reminder_id, expected_version, schedule_revision])
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._idempotent(connection, owner_id, "reminder_ack", idempotency_key, request_hash)
            if previous is not None:
                return previous
            row = connection.execute("""SELECT r.*, o.version AS current_version, o.schedule_revision AS current_schedule
                FROM reminders r JOIN occurrences o ON o.occurrence_id = r.occurrence_id
                WHERE r.owner_id = ? AND r.reminder_id = ?""", (owner_id, reminder_id)).fetchone()
            if row is None:
                raise KeyError(reminder_id)
            if (row["occurrence_version"] != expected_version or row["schedule_revision"] != schedule_revision
                or row["current_version"] != expected_version or row["current_schedule"] != schedule_revision):
                raise ValueError("reminder schedule changed")
            if row["acknowledged_at"] is None:
                connection.execute("UPDATE reminders SET acknowledged_at = ? WHERE owner_id = ? AND reminder_id = ?",
                                   (_iso(now), owner_id, reminder_id))
                connection.execute("INSERT INTO operation_audit (owner_id, operation, subject_id, source_action_id, occurred_at) VALUES (?, ?, ?, ?, ?)",
                                   (owner_id, "reminder_ack", row["occurrence_id"], reminder_id, _iso(now)))
            result = {"reminder_id": reminder_id, "occurrence_id": row["occurrence_id"], "version": expected_version,
                      "schedule_revision": schedule_revision, "acknowledged_at": _iso(now)}
            self._save_idempotent(connection, owner_id, "reminder_ack", idempotency_key, request_hash, result)
            return result

    def list_active_reminders(self, owner_id: str, now: datetime) -> list[dict]:
        with self._connect() as connection:
            # Materialize the occurrence window first so all recurring instances in
            # the five-minute horizon have stable IDs before reminder selection.
            self._occurrences_in(connection, owner_id, now, now + timedelta(days=1))
            rows = connection.execute("""SELECT r.*, o.version AS current_version, o.schedule_revision AS current_schedule,
                e.title, e.location, o.start_at FROM reminders r JOIN occurrences o ON o.occurrence_id = r.occurrence_id
                JOIN events e ON e.event_id = o.event_id WHERE r.owner_id = ? AND r.acknowledged_at IS NULL""", (owner_id,)).fetchall()
            result = []
            for row in rows:
                if row["current_version"] != row["occurrence_version"] or row["current_schedule"] != row["schedule_revision"]:
                    connection.execute("UPDATE reminders SET acknowledged_at = ? WHERE reminder_id = ? AND acknowledged_at IS NULL",
                                       (_iso(now), row["reminder_id"]))
                    continue
                start = datetime.fromisoformat(row["start_at"])
                if timedelta(0) < start - now <= timedelta(minutes=5):
                    result.append({"reminder_id": row["reminder_id"], "occurrence_id": row["occurrence_id"],
                        "version": row["occurrence_version"], "schedule_revision": row["schedule_revision"],
                        "acknowledged_at": None, "event_title": row["title"], "location": row["location"],
                        "start_at": start,
                        "minutes_until_start": max(0, int((start - now).total_seconds() // 60))})
            return result

    @staticmethod
    def _idempotent(connection: sqlite3.Connection, owner: str, operation: str, key: str, request_hash: str):
        row = connection.execute("SELECT request_hash, result_json FROM idempotency WHERE owner_id = ? AND operation = ? AND key = ?",
                                 (owner, operation, key)).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise IdempotencyConflict("idempotency key reused for different payload")
        return json.loads(row["result_json"])

    @staticmethod
    def _save_idempotent(connection: sqlite3.Connection, owner: str, operation: str, key: str,
                         request_hash: str, result) -> None:
        connection.execute("INSERT INTO idempotency VALUES (?, ?, ?, ?, ?)",
                           (owner, operation, key, request_hash, _json(result)))

    def commit_draft(self, owner_id: str, draft_id: str, revision: int, confirmed_ids: tuple[str, ...],
                     confirmation_digest: str, idempotency_key: str, conflict_acceptance: str | None,
                     now: datetime) -> CommitResult:
        operation = "draft_commit"
        request_hash = _hash([draft_id, revision, confirmed_ids, confirmation_digest, conflict_acceptance])
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._idempotent(connection, owner_id, operation, idempotency_key, request_hash)
            if previous is not None:
                return CommitResult(previous["draft_id"], previous["revision"], tuple(previous["event_ids"]))
            row = connection.execute("SELECT * FROM drafts WHERE owner_id = ? AND draft_id = ?", (owner_id, draft_id)).fetchone()
            if row is None:
                raise KeyError(draft_id)
            draft = self._draft_from_row(row)
            if draft.revision != revision or draft.status == "committed":
                raise RevisionConflict("draft revision is stale")
            if now >= draft.expires_at:
                raise DraftNotReady("draft expired; review again")
            if draft.status != "ready" or draft.confirmation_digest != confirmation_digest:
                raise DraftNotReady("draft is not ready or confirmation changed")
            expected_ids = tuple(candidate.candidate_id for candidate in draft.candidates)
            if len(confirmed_ids) != len(expected_ids) or set(confirmed_ids) != set(expected_ids):
                raise DraftNotReady("confirmation must include every candidate")
            for candidate in draft.candidates:
                candidate.validate_ready()

            # Existing instances and candidate slots are compared under the same write lock.
            event_ids = tuple(_candidate_event_id(draft_id, candidate.candidate_id) for candidate in draft.candidates)
            projected: list[Occurrence] = []
            for candidate, event_id in zip(draft.candidates, event_ids):
                assert candidate.start_at and candidate.end_at and candidate.title and candidate.timezone
                event = EventSeries(event_id, owner_id, 1, candidate.title, candidate.location,
                                    candidate.timezone, candidate.start_at, candidate.end_at, candidate.recurrence)
                if candidate.recurrence:
                    rule = candidate.recurrence
                    assert rule.ends_on is not None
                    range_start = datetime.combine(rule.starts_on, time.min, tzinfo=UTC) - timedelta(days=2)
                    range_end = datetime.combine(rule.ends_on + timedelta(days=2), time.min, tzinfo=UTC)
                    cursor = range_start
                    while cursor < range_end:
                        boundary = min(cursor + timedelta(days=300), range_end)
                        for slot in expand_slots(event, cursor, boundary):
                            projected.append(Occurrence(new_occurrence_id(event_id, slot.original_slot), event_id,
                                                        owner_id, slot.original_slot, slot.start_at, slot.end_at,
                                                        candidate.title, candidate.location, 1, 1, "scheduled"))
                        cursor = boundary
                else:
                    projected.append(Occurrence(new_occurrence_id(event_id, "single"), event_id, owner_id,
                                                "single", candidate.start_at, candidate.end_at,
                                                candidate.title, candidate.location, 1, 1, "scheduled"))
            existing: dict[str, Occurrence] = {}
            for item in projected:
                for active in self._occurrences_in(connection, owner_id, item.start_at, item.end_at):
                    existing[active.occurrence_id] = active
            conflicts = pairs(projected, existing.values())
            if conflicts:
                fingerprint = sorted((item.occurrence_id, item.schedule_revision, _iso(item.start_at), _iso(item.end_at))
                                     for item in existing.values())
                token = _hash([draft.confirmation_digest, conflicts, fingerprint])
                if conflict_acceptance != token:
                    raise ConflictReviewRequired(conflicts, token)

            for candidate, event_id in zip(draft.candidates, event_ids):
                assert candidate.start_at and candidate.end_at and candidate.title and candidate.timezone
                connection.execute(
                    """INSERT INTO events
                       (event_id, owner_id, version, title, location, timezone, start_at, end_at, recurrence_json)
                       VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)""",
                    (event_id, owner_id, candidate.title, candidate.location, candidate.timezone,
                     _iso(candidate.start_at), _iso(candidate.end_at),
                     _json(_recurrence_to_data(candidate.recurrence)) if candidate.recurrence else None),
                )
                if candidate.recurrence is None:
                    self._register_slots(connection, EventSeries(event_id, owner_id, 1, candidate.title,
                                         candidate.location, candidate.timezone, candidate.start_at,
                                         candidate.end_at), candidate.start_at, candidate.end_at)
            changed = connection.execute("UPDATE drafts SET status = 'committed' WHERE owner_id = ? AND draft_id = ? AND revision = ? AND status = 'ready'",
                                         (owner_id, draft_id, revision))
            if changed.rowcount != 1:
                raise RevisionConflict("draft changed during commit")
            result = {"draft_id": draft_id, "revision": revision, "event_ids": list(event_ids)}
            self._save_idempotent(connection, owner_id, operation, idempotency_key, request_hash, result)
            connection.execute("INSERT INTO operation_audit (owner_id, operation, subject_id, source_action_id, occurred_at) VALUES (?, ?, ?, ?, ?)",
                               (owner_id, operation, draft_id, draft.source_message_id, _iso(now)))
            return CommitResult(draft_id, revision, event_ids)

    def _get_occurrence(self, connection: sqlite3.Connection, owner_id: str, occurrence_id: str) -> Occurrence:
        row = connection.execute(
            """SELECT o.*, COALESCE(o.title_override, e.title) AS title,
                      CASE WHEN o.location_override_set = 1 THEN o.location_override ELSE e.location END AS location
               FROM occurrences o JOIN events e ON e.event_id = o.event_id
               WHERE o.owner_id = ? AND e.deleted = 0 AND o.occurrence_id = ?""", (owner_id, occurrence_id),
        ).fetchone()
        if row is None:
            raise KeyError(occurrence_id)
        return _occurrence_from_row(row)

    def decide_conflict(self, owner_id: str, member_ids: list[str], selected_id: str,
                        snapshot_revision: int, source_action_id: str, idempotency_key: str,
                        now: datetime) -> dict:
        canonical_members = sorted(set(member_ids))
        request_hash = _hash([canonical_members, selected_id, snapshot_revision, source_action_id])
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._idempotent(connection, owner_id, "conflict_decision", idempotency_key, request_hash)
            if previous is not None:
                return previous
            window = self._occurrences_in(connection, owner_id, now - timedelta(days=1), now + timedelta(days=1))
            active = tuple(item for item in window if item.disposition == "scheduled" and item.start_at <= now < item.end_at)
            current_revision = state_revision(active)
            if current_revision != snapshot_revision:
                raise RevisionConflict("active conflict snapshot changed; review the current state")
            groups = conflict_groups(active)
            selected_group = next((group for group in groups if list(group) == canonical_members), None)
            if selected_group is None or selected_id not in canonical_members or len(canonical_members) < 2:
                raise RevisionConflict("conflict members are no longer a current conflict group")
            decision_id = f"decision_{uuid4().hex}"
            for identity in canonical_members:
                if identity == selected_id:
                    continue
                cursor = connection.execute(
                    """UPDATE occurrences SET disposition = 'missed', version = version + 1, source_action_id = ?
                       WHERE owner_id = ? AND occurrence_id = ? AND disposition = 'scheduled'""",
                    (source_action_id, owner_id, identity),
                )
                if cursor.rowcount != 1:
                    raise RevisionConflict("a conflict member changed while applying the decision")
            affected = [self._get_occurrence(connection, owner_id, identity) for identity in canonical_members]
            active_after = tuple(item for item in self._occurrences_in(
                connection, owner_id, now - timedelta(days=1), now + timedelta(days=1))
                if item.disposition == "scheduled" and item.start_at <= now < item.end_at)
            result = {
                "decision_id": decision_id,
                "selected_id": selected_id,
                "affected_occurrences": [_occurrence_to_data(item) for item in affected],
                "state_revision": state_revision(active_after),
            }
            self._save_idempotent(connection, owner_id, "conflict_decision", idempotency_key, request_hash, result)
            connection.execute(
                """INSERT INTO operation_audit (owner_id, operation, subject_id, source_action_id, occurred_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (owner_id, "conflict_decision", decision_id, source_action_id, _iso(now)),
            )
            return result

    def set_exception(self, owner_id: str, occurrence_id: str, disposition: str, expected_version: int,
                      source_action_id: str, idempotency_key: str, now: datetime) -> Occurrence:
        request_hash = _hash([occurrence_id, disposition, expected_version, source_action_id])
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._idempotent(connection, owner_id, "occurrence_exception", idempotency_key, request_hash)
            if previous is not None:
                return _occurrence_from_data(previous)
            current = self._get_occurrence(connection, owner_id, occurrence_id)
            if current.version != expected_version:
                raise RevisionConflict("occurrence changed")
            if current.disposition != "scheduled":
                raise RevisionConflict("occurrence already has a disposition")
            connection.execute("""UPDATE occurrences SET disposition = ?, version = version + 1, source_action_id = ?
                                  WHERE owner_id = ? AND occurrence_id = ? AND version = ?""",
                               (disposition, source_action_id, owner_id, occurrence_id, expected_version))
            result = self._get_occurrence(connection, owner_id, occurrence_id)
            self._save_idempotent(connection, owner_id, "occurrence_exception", idempotency_key, request_hash,
                                  _occurrence_to_data(result))
            connection.execute("INSERT INTO operation_audit (owner_id, operation, subject_id, source_action_id, occurred_at) VALUES (?, ?, ?, ?, ?)",
                               (owner_id, "occurrence_exception", occurrence_id, source_action_id, _iso(now)))
            return result

    def reschedule_single(self, owner_id: str, occurrence_id: str, expected_version: int,
                          start_at: datetime, end_at: datetime) -> Occurrence:
        if not overlaps(start_at, end_at, start_at, end_at):
            raise ValueError("invalid interval")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._get_occurrence(connection, owner_id, occurrence_id)
            if current.version != expected_version:
                raise RevisionConflict("occurrence changed")
            event_row = connection.execute("SELECT recurrence_json FROM events WHERE owner_id = ? AND event_id = ?",
                                           (owner_id, current.event_id)).fetchone()
            if event_row["recurrence_json"] is not None:
                from kairos.application.event_commands import UnsupportedEditScope
                raise UnsupportedEditScope("series slot remapping is not implemented")
            connection.execute("""UPDATE occurrences SET start_at = ?, end_at = ?, version = version + 1,
                                  schedule_revision = schedule_revision + 1
                                  WHERE owner_id = ? AND occurrence_id = ?""",
                               (_iso(start_at), _iso(end_at), owner_id, occurrence_id))
            connection.execute("""UPDATE events SET start_at = ?, end_at = ?, version = version + 1
                                  WHERE owner_id = ? AND event_id = ?""",
                               (_iso(start_at), _iso(end_at), owner_id, current.event_id))
            return self._get_occurrence(connection, owner_id, occurrence_id)

    @staticmethod
    def _proposal_from_row(row: sqlite3.Row) -> dict:
        return {"proposal_id": row["proposal_id"], "target_id": row["target_id"],
                "scope": row["scope"], "revision": row["revision"], "action": row["action"],
                "summary": row["summary"], "confirmation_digest": row["confirmation_digest"],
                "status": row["status"]}

    def get_event_change_proposal(self, owner_id: str, proposal_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM event_change_proposals WHERE owner_id = ? AND proposal_id = ?",
                                     (owner_id, proposal_id)).fetchone()
            return self._proposal_from_row(row) if row else None

    def propose_event_change(self, owner_id: str, target_id: str, scope: str, expected_version: int,
                             action: str, changes: dict, source_message_id: str,
                             idempotency_key: str, now: datetime) -> dict:
        request_hash = _hash([target_id, scope, expected_version, action, changes, source_message_id])
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._idempotent(connection, owner_id, "event_change_propose", idempotency_key, request_hash)
            if previous is not None:
                return previous
            if scope == "occurrence":
                current = self._get_occurrence(connection, owner_id, target_id)
                version = current.version
                title = current.title
                if current.disposition != "scheduled":
                    raise RevisionConflict("only a scheduled occurrence can be changed")
            else:
                row = connection.execute("SELECT * FROM events WHERE owner_id = ? AND event_id = ? AND deleted = 0",
                                         (owner_id, target_id)).fetchone()
                if row is None:
                    raise KeyError(target_id)
                version = row["version"]
                title = row["title"]
            if version != expected_version:
                raise RevisionConflict("event changed before proposal review")
            summary = (f"删除{'本次' if scope == 'occurrence' else '整个系列'}：{title}" if action == "delete" else
                       f"修改{'本次' if scope == 'occurrence' else '整个系列'}：{title}；变更 {', '.join(changes)}")
            proposal_id = f"proposal_{uuid4().hex}"
            digest = _hash([proposal_id, target_id, scope, expected_version, action, changes, title])
            connection.execute("""INSERT INTO event_change_proposals
                (proposal_id, owner_id, target_id, scope, expected_version, action, changes_json,
                 source_message_id, summary, confirmation_digest, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (proposal_id, owner_id, target_id, scope, expected_version, action, _json(changes),
                 source_message_id, summary, digest, _iso(now), _iso(now + timedelta(hours=24))))
            result = {"proposal_id": proposal_id, "target_id": target_id, "scope": scope,
                      "revision": 1, "action": action, "summary": summary,
                      "confirmation_digest": digest, "status": "pending"}
            self._save_idempotent(connection, owner_id, "event_change_propose", idempotency_key, request_hash, result)
            return result

    def commit_event_change(self, owner_id: str, proposal_id: str, revision: int,
                            confirmation_digest: str, source_action_id: str,
                            idempotency_key: str, now: datetime) -> dict:
        request_hash = _hash([proposal_id, revision, confirmation_digest, source_action_id])
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._idempotent(connection, owner_id, "event_change_commit", idempotency_key, request_hash)
            if previous is not None:
                return previous
            row = connection.execute("SELECT * FROM event_change_proposals WHERE owner_id = ? AND proposal_id = ?",
                                     (owner_id, proposal_id)).fetchone()
            if row is None:
                raise KeyError(proposal_id)
            if (row["status"] != "pending" or row["revision"] != revision or
                row["confirmation_digest"] != confirmation_digest or
                datetime.fromisoformat(row["expires_at"]) <= now):
                raise RevisionConflict("proposal changed or expired; review again")
            target_id, scope, action = row["target_id"], row["scope"], row["action"]
            changes = json.loads(row["changes_json"])
            if scope == "occurrence":
                current = self._get_occurrence(connection, owner_id, target_id)
                if current.version != row["expected_version"] or current.disposition != "scheduled":
                    raise RevisionConflict("occurrence changed; review again")
                event_row = connection.execute("SELECT * FROM events WHERE owner_id = ? AND event_id = ?",
                                               (owner_id, current.event_id)).fetchone()
                if event_row is None or event_row["deleted"]:
                    raise RevisionConflict("event series changed; review again")
                if action == "delete":
                    connection.execute("""UPDATE occurrences SET disposition = 'cancelled', version = version + 1,
                        source_action_id = ? WHERE owner_id = ? AND occurrence_id = ?""",
                        (source_action_id, owner_id, target_id))
                else:
                    sets = ["version = version + 1", "source_action_id = ?"]
                    params = [source_action_id]
                    if "start_at" in changes:
                        sets += ["start_at = ?", "end_at = ?", "schedule_revision = schedule_revision + 1"]
                        params += [_iso(datetime.fromisoformat(changes["start_at"])),
                                   _iso(datetime.fromisoformat(changes["end_at"]))]
                    if event_row["recurrence_json"] is not None:
                        if "title" in changes:
                            sets.append("title_override = ?")
                            params.append(changes["title"])
                        if "location" in changes:
                            sets += ["location_override = ?", "location_override_set = 1"]
                            params.append(changes["location"])
                    params += [owner_id, target_id]
                    connection.execute(f"UPDATE occurrences SET {', '.join(sets)} WHERE owner_id = ? AND occurrence_id = ?",
                                       params)
                    if event_row["recurrence_json"] is None:
                        event_sets = ["version = version + 1"]
                        event_params = []
                        for key in ("title", "location", "start_at", "end_at"):
                            if key in changes:
                                event_sets.append(f"{key} = ?")
                                event_params.append(_iso(datetime.fromisoformat(changes[key])) if key.endswith("_at") else changes[key])
                        connection.execute(f"UPDATE events SET {', '.join(event_sets)} WHERE owner_id = ? AND event_id = ?",
                                           event_params + [owner_id, current.event_id])
                affected_ids = [target_id]
                updated_version = current.version + 1
            else:
                event_row = connection.execute("SELECT * FROM events WHERE owner_id = ? AND event_id = ? AND deleted = 0",
                                               (owner_id, target_id)).fetchone()
                if event_row is None:
                    raise KeyError(target_id)
                if event_row["version"] != row["expected_version"]:
                    raise RevisionConflict("series changed; review again")
                affected_ids = [item["occurrence_id"] for item in connection.execute(
                    "SELECT occurrence_id FROM occurrences WHERE owner_id = ? AND event_id = ?",
                    (owner_id, target_id)).fetchall()]
                if action == "delete":
                    connection.execute("UPDATE events SET deleted = 1, version = version + 1 WHERE owner_id = ? AND event_id = ?",
                                       (owner_id, target_id))
                    connection.execute("""UPDATE occurrences SET disposition = 'cancelled', version = version + 1,
                        source_action_id = ? WHERE owner_id = ? AND event_id = ? AND disposition = 'scheduled'""",
                        (source_action_id, owner_id, target_id))
                else:
                    sets = ["version = version + 1"]
                    params = []
                    for key in ("title", "location"):
                        if key in changes:
                            sets.append(f"{key} = ?")
                            params.append(changes[key])
                    connection.execute(f"UPDATE events SET {', '.join(sets)} WHERE owner_id = ? AND event_id = ?",
                                       params + [owner_id, target_id])
                    connection.execute("UPDATE occurrences SET version = version + 1 WHERE owner_id = ? AND event_id = ?",
                                       (owner_id, target_id))
                updated_version = event_row["version"] + 1
            connection.execute("UPDATE event_change_proposals SET status = 'committed' WHERE proposal_id = ?",
                               (proposal_id,))
            result = {"proposal_id": proposal_id, "target_id": target_id, "scope": scope,
                      "action": action, "affected_ids": affected_ids, "version": updated_version,
                      "status": "committed"}
            self._save_idempotent(connection, owner_id, "event_change_commit", idempotency_key, request_hash, result)
            connection.execute("""INSERT INTO operation_audit (owner_id, operation, subject_id, source_action_id, occurred_at)
                VALUES (?, ?, ?, ?, ?)""", (owner_id, "event_change_commit", proposal_id, source_action_id, _iso(now)))
            return result
