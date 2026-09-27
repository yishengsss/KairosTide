CREATE TABLE conversations (
  conversation_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(owner_id, conversation_id)
);
CREATE INDEX idx_conversations_owner ON conversations(owner_id);

CREATE TABLE conversation_messages (
  message_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK(sequence >= 1),
  role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending', 'completed')),
  action_results_json TEXT NOT NULL DEFAULT '[]',
  draft_refs_json TEXT NOT NULL DEFAULT '[]',
  UNIQUE(conversation_id, sequence),
  FOREIGN KEY(owner_id, conversation_id) REFERENCES conversations(owner_id, conversation_id)
);
CREATE INDEX idx_conversation_messages_page ON conversation_messages(owner_id, conversation_id, sequence);

CREATE TABLE conversation_turns (
  owner_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  client_message_id TEXT NOT NULL,
  user_message_id TEXT NOT NULL REFERENCES conversation_messages(message_id),
  assistant_message_id TEXT REFERENCES conversation_messages(message_id),
  request_hash TEXT NOT NULL,
  request_content TEXT NOT NULL,
  timezone TEXT NOT NULL,
  expected_sequence INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending', 'completed')),
  response_json TEXT,
  PRIMARY KEY(owner_id, conversation_id, client_message_id),
  FOREIGN KEY(owner_id, conversation_id) REFERENCES conversations(owner_id, conversation_id)
);
CREATE UNIQUE INDEX idx_conversation_pending_turn ON conversation_turns(owner_id, conversation_id)
  WHERE status = 'pending';
