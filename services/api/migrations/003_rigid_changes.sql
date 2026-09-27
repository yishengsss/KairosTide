ALTER TABLE events ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0, 1));
ALTER TABLE occurrences ADD COLUMN title_override TEXT;
ALTER TABLE occurrences ADD COLUMN location_override TEXT;
ALTER TABLE occurrences ADD COLUMN location_override_set INTEGER NOT NULL DEFAULT 0 CHECK(location_override_set IN (0, 1));

CREATE TABLE event_change_proposals (
  proposal_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  scope TEXT NOT NULL CHECK(scope IN ('occurrence', 'series')),
  expected_version INTEGER NOT NULL,
  action TEXT NOT NULL CHECK(action IN ('update', 'delete')),
  changes_json TEXT NOT NULL,
  source_message_id TEXT NOT NULL,
  summary TEXT NOT NULL,
  confirmation_digest TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'committed')),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX idx_event_change_proposals_owner ON event_change_proposals(owner_id, status);
