"""Owner-scoped SQLite store with atomic draft commit and stable occurrences."""

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from kairos.application.draft_commit import CommitResult, ConflictReviewRequired
from kairos.domain.conflicts import pairs
from kairos.domain.drafts import Candidate, Draft, DraftNotReady, IdempotencyConflict, RevisionConflict, make_draft
from kairos.domain.events import EventSeries, Occurrence, RecurrenceRule
from kairos.domain.occurrence_identity import new_occurrence_id
from kairos.domain.recurrence import expand_slots
from kairos.domain.time_rules import overlaps


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
        migration = Path(__file__).resolve().parents[4] / "migrations/001_initial.sql"
        with self._connect() as connection:
            connection.executescript(migration.read_text())

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
                "SELECT * FROM events WHERE owner_id = ? ORDER BY event_id", (owner_id,)).fetchall()]

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
        for row in connection.execute("SELECT * FROM events WHERE owner_id = ?", (owner_id,)).fetchall():
            self._register_slots(connection, _event_from_row(row), start, end)
        rows = connection.execute(
            """SELECT o.*, e.title, e.location FROM occurrences o JOIN events e ON e.event_id = o.event_id
               WHERE o.owner_id = ? AND o.start_at < ? AND ? < o.end_at
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
                    "event_title": row["title"], "location": row["location"], "minutes_until_start": minutes}

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
                    "INSERT INTO events VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)",
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
            """SELECT o.*, e.title, e.location FROM occurrences o JOIN events e ON e.event_id = o.event_id
               WHERE o.owner_id = ? AND o.occurrence_id = ?""", (owner_id, occurrence_id),
        ).fetchone()
        if row is None:
            raise KeyError(occurrence_id)
        return _occurrence_from_row(row)

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
