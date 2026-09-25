PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS drafts (
  draft_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK(revision >= 1),
  source_message_id TEXT NOT NULL,
  reference_now TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('needs_clarification', 'ready', 'committed')),
  confirmation_digest TEXT NOT NULL,
  candidates_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drafts_owner ON drafts(owner_id);

CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version >= 1),
  title TEXT NOT NULL,
  location TEXT,
  timezone TEXT NOT NULL,
  start_at TEXT NOT NULL,
  end_at TEXT NOT NULL,
  recurrence_json TEXT,
  CHECK(end_at > start_at)
);
CREATE INDEX IF NOT EXISTS idx_events_owner ON events(owner_id);

CREATE TABLE IF NOT EXISTS occurrences (
  occurrence_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  event_id TEXT NOT NULL REFERENCES events(event_id),
  original_slot TEXT NOT NULL,
  start_at TEXT NOT NULL,
  end_at TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version >= 1),
  schedule_revision INTEGER NOT NULL CHECK(schedule_revision >= 1),
  disposition TEXT NOT NULL DEFAULT 'scheduled' CHECK(disposition IN ('scheduled', 'excused', 'cancelled', 'missed')),
  source_action_id TEXT,
  UNIQUE(owner_id, event_id, original_slot),
  CHECK(end_at > start_at)
);
CREATE INDEX IF NOT EXISTS idx_occurrences_window ON occurrences(owner_id, start_at, end_at);

CREATE TABLE IF NOT EXISTS idempotency (
  owner_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  result_json TEXT NOT NULL,
  PRIMARY KEY(owner_id, operation, key)
);

CREATE TABLE IF NOT EXISTS operation_audit (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  source_action_id TEXT,
  occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_operation_audit_owner ON operation_audit(owner_id, operation);
