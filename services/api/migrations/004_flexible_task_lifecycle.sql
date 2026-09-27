ALTER TABLE flexible_tasks ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'planned'
  CHECK(lifecycle_status IN ('planned', 'active', 'completed'));
