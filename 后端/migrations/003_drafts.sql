CREATE TABLE planning_drafts (
    id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision > 0),
    status TEXT NOT NULL CHECK (status IN ('needs_clarification', 'ready', 'unsupported', 'committed')),
    text TEXT NOT NULL,
    timezone TEXT NOT NULL,
    reference_now TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    answers_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL,
    committed_key TEXT,
    committed_hash TEXT,
    committed_event_ids_json TEXT
);

CREATE TABLE planning_idempotency (
    idempotency_key TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    event_ids_json TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_migrations (version, applied_at)
VALUES (3, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
