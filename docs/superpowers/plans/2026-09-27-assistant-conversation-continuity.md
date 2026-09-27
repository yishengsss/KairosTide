# Assistant Conversation Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Persist owner-scoped assistant conversations and safely restore their messages and pending rigid-event drafts across long chats and page reloads.

**Architecture:** SQLite becomes the source of truth for conversation text, sequence/revision, action results, draft references, pending turns, and idempotent responses. A conversation application service reserves a user turn, calls the existing assistant outside the transaction, then commits the assistant response; retries reuse the reservation and existing action idempotency. The web session stores only the current conversation ID and restores messages/drafts through APIs. Images remain request-only and are never stored in conversation rows.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, Vue 3, TypeScript, generated OpenAPI TypeScript contract, pytest, Node test runner, `scripts/check.py`.

**Spec:** `docs/superpowers/specs/2026-09-27-assistant-conversation-continuity-design.md`

## Global Constraints

- Conversation rows are always scoped by the trusted `owner_id`; never accept an owner from the client.
- The server owns canonical conversation history; clients submit one new turn rather than replacing prior history.
- Persist full text history, but send at most 24 complete user/assistant messages and 32,000 total text characters to the model; do not silently drop the latest turn.
- Message retry with the same client message ID and same content returns its original result; a different request under that ID conflicts.
- A conversation accepts at most one unfinished turn; a different message receives 409 until the pending turn is retried or completed.
- Draft confirmation uses the latest server draft revision, candidate IDs, and confirmation digest.
- Typed confirmation still commits through the existing draft endpoint without model interpretation; after a successful commit, the conversation endpoint may persist a deterministic receipt only for an already committed, conversation-referenced draft, without invoking model/tools or changing schedule data.
- Image bytes and image URLs are never stored in SQLite, conversation history, or logs.
- Conversation reads do not invoke schedule, flexible-task, or weather tools.
- Keep the frozen legacy directories out of runtime, build, and dependency inputs.

## Review Focus

- The thirteenth and later chat turns must not fail at the old 24-message request ceiling; pin this in the conversation API test.
- A timed-out/pending message retry must not duplicate its turn or side effects; pin this in the repository/API idempotency test.
- A draft restored after reload must reflect committed/expired server state rather than stale browser state; pin this in the draft restore API and web tests.
- Cross-owner conversation IDs must not reveal messages or draft references; pin this in repository/API ownership tests.
- Image attachments must not be persisted or replayed after reload; pin this in the API storage integration test.

---

### Task 1: Conversation storage and transport contract

**Files:**
- Create: `services/api/src/kairos/domain/conversations.py`
- Create: `services/api/migrations/005_conversations.sql`
- Modify: `services/api/src/kairos/api/schemas.py`
- Modify: `services/api/src/kairos/adapters/persistence/sqlite.py`
- Test: `services/api/tests/integration/test_conversations.py`
- Modify: `services/api/tests/integration/test_tasks.py` (migration sequence expectation only)
- Generated: `contracts/openapi.json`, `contracts/backend-api.d.ts`

**Interfaces:**
- Consumes: existing `Conversation`, `MessageRequest`, `ConversationMessage`, `MessageResponse`, and `MessagePage` DTO names.
- Produces: pure domain records `ConversationRecord`, `ConversationMessageRecord`, `ConversationTurn`, and `ConversationPage`; owner-scoped repository methods `create_conversation(owner_id: str, idempotency_key: str, request_hash: str) -> ConversationRecord`, `get_conversation(owner_id: str, conversation_id: str) -> ConversationRecord | None`, `reserve_conversation_turn(owner_id: str, conversation_id: str, client_message_id: str, content: str, timezone: str, expected_sequence: int, request_hash: str) -> ConversationTurn`, `complete_conversation_turn(owner_id: str, conversation_id: str, client_message_id: str, assistant_content: str, action_results: list[dict], draft_refs: list[str]) -> ConversationTurn`, and `list_conversation_messages(owner_id: str, conversation_id: str, after_sequence: int, limit: int) -> ConversationPage`. Response DTOs carry sequence/revision, pending/completed status, persisted action results, and draft references.

- [x] **Step 1: Write failing storage tests** for create/read, ordered pages, owner isolation, unique per-conversation sequence, and idempotent same-ID retry versus changed-content conflict; update the migration ledger assertion to include migration 005.
- [x] **Step 2: Run the targeted tests** with `services/api/.venv/bin/python -m pytest services/api/tests/integration/test_conversations.py -q`; verify failures identify missing tables/repository APIs.
- [x] **Step 3: Add migration and repository methods**. Persist text-only user/assistant messages, action-result JSON, draft IDs, request hash, response payload, and conversation revision; use SQLite transactions for sequence and idempotency checks.
- [x] **Step 4: Extend DTOs** for create idempotency, one-turn requests with `expected_sequence`, paged history, and stored result metadata. Reject request history arrays from the persistent endpoint.
- [x] **Step 5: Regenerate OpenAPI types** with `services/api/.venv/bin/python scripts/generate_contracts.py` and inspect the diff; never edit generated files directly.
- [x] **Step 6: Run targeted storage/contract tests** and verify the same client ID cannot create two rows or mutate the stored response.

### Task 2: Conversation API and bounded context builder

**Files:**
- Create: `services/api/src/kairos/application/conversations.py`
- Modify: `services/api/src/kairos/main.py`
- Modify: `services/api/src/kairos/application/assistant_tasks.py`
- Test: `services/api/tests/integration/test_conversation_api.py`
- Test: `services/api/tests/integration/test_assistant_task_http.py`

**Interfaces:**
- Consumes: Task 1 repository methods and existing `AssistantService.handle(owner_id, client_message_id, timezone, messages, image)`.
- Produces: conversation create, append-turn, and paged-read routes. `ConversationService.append_turn(owner_id: str, conversation_id: str, client_message_id: str, content: str, timezone: str, expected_sequence: int, image: ValidatedImage | None) -> MessageResponse` reserves/loads canonical history, calls AssistantService outside the transaction, persists user/assistant turn plus tool/draft references, and returns the idempotent response.
- `ConversationService.build_model_context(messages: list[ConversationMessageRecord], latest_user_message_id: str) -> list[dict[str, str]]` returns only complete recent turns, at most 24 messages and 32,000 total characters, always including the latest user turn or raising a typed input-too-large error.

- [x] **Step 1: Add failing HTTP tests in `test_conversation_api.py`** for create→append→read, 13+ turns, same-ID retry after completion, same-ID pending-turn retry, changed-content conflict, a distinct message blocked while pending, expected-sequence conflict, and cross-owner rejection.
- [x] **Step 2: Run those tests** and confirm route behavior fails before implementation.
- [x] **Step 3: Implement the application coordinator**. Reserve one pending user turn in a short transaction, keep model calls outside SQLite transactions, and finalize the assistant response in a second short transaction; use the same stable client message ID for existing tool-side idempotency.
- [x] **Step 4: Build bounded model context** from whole user/assistant turns, with a maximum of 24 messages and 32,000 total text characters. Preserve the latest user turn and recent complete exchanges; store full history independently. Do not add an unverified AI summary.
- [x] **Step 5: Implement owner-checked create, append, and paginated read routes**. Return 404 for unknown or foreign conversation IDs; return 409 with current sequence/revision for stale sequence.
- [x] **Step 6: On read, return persisted draft references and any pending user turn plus its `client_message_id` without executing tools**; keep image attachment bytes out of the repository. Same-ID retries resume pending turns; completed retries return the stored response.
- [x] **Step 7: Preserve direct typed draft confirmation in canonical history**: after the existing commit endpoint succeeds, append the confirmation via a deterministic server receipt that verifies the referenced draft is already committed; verify no model call or schedule mutation occurs.
- [x] **Step 8: Run targeted API tests** including the original “10 minutes later / 20-minute duration / confirm” exchange through persisted turns.

### Task 3: Web session resume and draft restoration

**Files:**
- Modify: `apps/web/src/assistant/sessionStore.ts`
- Modify: `apps/web/src/App.vue`
- Create: `apps/web/src/assistant/conversationApi.ts`
- Modify: `apps/web/src/assistant/chatPayload.ts` to remove stateless-history transport if no other caller remains
- Test: `apps/web/tests/assistant/session.test.mjs`
- Test: `apps/web/tests/assistant/chat-payload.test.mjs`

**Interfaces:**
- Consumes: Task 1 generated conversation DTOs and Task 2 create/append/read/get-draft APIs.
- Produces: session commands `createConversation(idempotencyKey)`, `appendConversationTurn(conversationId, request, idempotencyKey, image?)`, `loadConversation(conversationId, cursor?)`, and `getDraft(draftId)`; session persistence stores only `conversation_id` in localStorage.

- [x] **Step 1: Add failing web tests** for resume on open, visible transcript restoration, current draft restoration from server reference, no image persistence, and preserving input/client ID after uncertain send.
- [x] **Step 2: Run focused Node tests** with `node --test apps/web/tests/assistant/session.test.mjs` and confirm expected failures.
- [x] **Step 3: Add current-conversation ID persistence** with guarded localStorage access; do not serialize messages, draft snapshots, or files.
- [x] **Step 4: Change send flow** to create a conversation when needed, then send only the new text turn plus a transient optional image. Append UI messages from the server response only after success.
- [x] **Step 5: Change resume flow** to load paged server messages and resolve the latest draft reference through `GET /drafts/{id}`. Restore DraftReview only from current server state; committed/expired drafts cannot be confirmed.
- [x] **Step 6: Handle unknown send outcome** by loading the current conversation before retrying with the original client message ID; if the server shows that message pending, retry exactly that ID/text. Preserve user input until state is resolved.
- [x] **Step 7: Run focused web tests** including refresh-style re-instantiation using the same fake storage and verify images are never written there.

### Task 4: End-to-end consistency and verification

**Files:**
- Create: `services/api/tests/integration/test_conversation_recovery.py`
- Create: `apps/web/tests/assistant/session-recovery.test.mjs`
- Modify: `docs/memory/PRODUCT_MEMORY.md`
- Modify: `docs/engineering/HARNESS.md` to add the next assistant-continuity requirement and map its minimum evidence
- Modify: `scripts/check.py` so the docs gate validates the added requirement

**Interfaces:**
- Consumes: Tasks 1–3 APIs and generated contract.
- Produces: verified cross-restart continuity evidence and explicit limits for bounded model context.

- [x] **Step 1: Write a failing migration-restart test** in `test_conversation_recovery.py`: persist multiple turns and an uncommitted draft reference, reopen the API against the same SQLite file, and assert ordering/state restoration.
- [x] **Step 2: Run that test** with `services/api/.venv/bin/python -m pytest services/api/tests/integration/test_conversation_recovery.py -q` and confirm it fails before implementation.
- [x] **Step 3: Write and run a failing stale-draft test** in `session-recovery.test.mjs`: commit or expire the referenced draft, reload the conversation, and assert the client cannot restore a confirmable stale draft.
- [x] **Step 4: Write and run a failing image-privacy test** in `test_conversation_recovery.py`: submit an image, inspect SQLite tables, and assert neither bytes nor data URLs occur in persisted fields.
- [x] **Step 5: Add the next sequential requirement ID** to the unique requirement table and evidence guidance in `docs/engineering/HARNESS.md`; update `scripts/check.py` to require that ID; map the requirement to durable messages, pending-turn idempotency, bounded context, draft recovery, and image non-persistence.
- [x] **Step 6: Run** `python3 scripts/check.py contracts`, `python3 scripts/check.py api`, `python3 scripts/check.py web`, `python3 scripts/check.py docs`, and `git diff --check`.
- [x] **Step 7: Review the full diff** for owner isolation, model-call/transaction separation, idempotency, persisted image content, and no regression to draft confirmation semantics.
- [x] **Step 8: Update product memory** to distinguish durable transcript storage, bounded model context, and the explicit image-payload retention limit; record verification scope without claiming browser E2E unless run.

## Self-review

- **Spec coverage:** storage, owner scoping, idempotency, sequence conflicts, bounded context, frontend resume, draft references, image privacy, and read-only restoration all have named tasks and tests.
- **Step scan:** each checkbox is one test, implementation, generation, or verification action with an exact command or observable result.
- **Type consistency:** Task 1 produces the repository/DTO boundary consumed by Task 2; Task 2 routes feed Task 3 commands; Task 4 verifies only those interfaces.
- **Review focus:** all five listed risk cases map to explicit tests in Tasks 1–4.
- **Proportion:** four tasks split by reviewable boundaries; no independent feature or unrelated UI work is included.
