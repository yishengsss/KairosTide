ALTER TABLE events ADD COLUMN event_type TEXT NOT NULL DEFAULT 'single'
    CHECK (event_type IN ('single', 'recurring'));
ALTER TABLE events ADD COLUMN recurrence_start_date TEXT;
ALTER TABLE events ADD COLUMN local_start_time TEXT;
ALTER TABLE events ADD COLUMN local_end_time TEXT;
ALTER TABLE events ADD COLUMN end_day_offset INTEGER NOT NULL DEFAULT 0
    CHECK (end_day_offset IN (0, 1));
ALTER TABLE events ADD COLUMN frequency TEXT
    CHECK (frequency IS NULL OR frequency IN ('daily', 'weekly'));
ALTER TABLE events ADD COLUMN weekdays_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE events ADD COLUMN until_date TEXT;
ALTER TABLE events ADD COLUMN gap_policy TEXT
    CHECK (gap_policy IS NULL OR gap_policy = 'skip');
ALTER TABLE events ADD COLUMN fold_policy TEXT
    CHECK (fold_policy IS NULL OR fold_policy IN ('earlier', 'later'));

CREATE TABLE event_exceptions (
    id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    occurrence_key TEXT NOT NULL,
    exception_type TEXT NOT NULL CHECK (exception_type IN ('excused', 'cancelled')),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE (event_id, occurrence_key)
);

CREATE INDEX event_exceptions_event_idx ON event_exceptions (event_id);

INSERT OR IGNORE INTO schema_migrations (version, applied_at)
VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
