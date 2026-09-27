CREATE TABLE IF NOT EXISTS flexible_tasks (
  task_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version >= 1),
  title TEXT NOT NULL,
  deadline_value TEXT,
  deadline_precision TEXT CHECK(deadline_precision IN ('date', 'instant') OR deadline_precision IS NULL),
  timezone TEXT NOT NULL,
  source_message_id TEXT,
  CHECK((deadline_precision IS NULL AND deadline_value IS NULL) OR
        (deadline_precision IS NOT NULL AND deadline_value IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_flexible_tasks_owner_title
  ON flexible_tasks(owner_id, title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_flexible_tasks_owner_deadline
  ON flexible_tasks(owner_id, deadline_precision, deadline_value, task_id);
