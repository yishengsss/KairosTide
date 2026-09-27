# Kairos Limited AI Flexible Task Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task and obtain an independent task review before proceeding.

**Goal:** Let Kairos users explicitly add, query, edit, and delete flexible tasks through MiMo while keeping all model operations inside a validated server-side allowlist.

**Architecture:** MiMo proposes typed tool calls. A backend assistant application service validates each tool name and argument, then invokes owner-scoped task use cases; the model never receives storage or arbitrary HTTP access. Explicit task writes return structured results, query answers cite saved task records, and the frontend displays server-confirmed results. Rigid event operations remain out of this plan and follow their own draft/confirmation workflow.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, `urllib` MiMo adapter, Vue 3, TypeScript, generated OpenAPI types, Node test runner.

**Spec:** [AI limited authority design](../specs/2026-09-26-ai-limited-authority-design.md)

## Global Constraints

- AI only acts during a user-initiated assistant turn; no background task reads, recommendations, or reminders.
- Model output is untrusted input. Only the four registered flexible-task actions are executable in this milestone.
- The API application owns validation and persistence; the model adapter and Vue UI have no database authority.
- Every task is owner-scoped and every mutation uses an idempotency key plus expected version where applicable.
- Flexible tasks remain outside `/state`, event occurrences, scene rendering, and reminder scheduling.
- Provider keys remain in the server process environment and never enter the browser, persisted task data, logs, or generated contracts.
- Do not stage, rewrite, or discard pre-existing dirty files. Shared contract and `main.py` integration is coordinator-owned and serial.

## Review Focus

1. A model attempts an unknown tool, invalid JSON, cross-owner ID, or malformed deadline; no mutation occurs.
2. The same client message is retried after a timeout; the task is not duplicated and the response is structurally recoverable.
3. Two tasks have the same title; edit/delete must ask for disambiguation and change neither task.
4. A greeting causes a fake model to call `list_flexible_tasks`; the response policy must not expose task records unless the turn is an explicit task query.
5. MiMo returns a successful write tool call followed by false free text; the UI must trust the structured API action result, not the model's success claim.

## File Ownership Map

| Owner | Files | Responsibility |
| --- | --- | --- |
| B: domain/storage | `services/api/src/kairos/domain/tasks.py`, `application/tasks.py`, `adapters/persistence/sqlite.py`, `services/api/migrations/002_flexible_tasks.sql`, task integration tests | Task facts, owner isolation, revision/idempotency and SQLite persistence |
| A: assistant orchestration | `services/api/src/kairos/application/assistant.py`, `application/assistant_tools.py`, `adapters/ai/mimo.py`, adapter/application tests | Tool schemas, allowlist, bounded tool loop, deterministic result mapping |
| C: API/contracts | `services/api/src/kairos/api/schemas.py`, `services/api/src/kairos/main.py`, `contracts/*` | HTTP boundary, dependency injection, generated contract; serial integration only |
| U: frontend | `apps/web/src/App.vue`, `assistant/sessionStore.ts`, `assistant/Conversation.vue`, `assistant/AssistantPanel.vue`, `apps/web/tests/assistant/*` | Send request context and display API-confirmed task action/query results |
| Q: independent verification | new `services/api/tests/integration/test_assistant_tasks.py`, test reports | Cross-layer adversarial checks; no implementation writes |

Tasks run in dependency order: B → A → C → U → Q. No two owners edit a shared file in the same step.

## Task 1: Flexible Task Domain and Persistence

**Owner:** B; **requirements:** K10, K11, K14; **depends on:** current event repository patterns.

**Files:**
- Create: `services/api/src/kairos/domain/tasks.py`
- Create: `services/api/src/kairos/application/tasks.py`
- Create: `services/api/migrations/002_flexible_tasks.sql`
- Modify: `services/api/src/kairos/adapters/persistence/sqlite.py`
- Create: `services/api/tests/integration/test_tasks.py`

**Interfaces:**
- `FlexibleTaskRecord(task_id, owner_id, version, title, deadline, deadline_precision, timezone, source_message_id)` is the internal task fact. Supported deadline precision is `None`, `date`, or `instant`; no status/completion lifecycle is introduced in this milestone.
- `FlexibleTaskService.create(owner_id, title, deadline, deadline_precision, timezone, source_message_id, idempotency_key)` returns a task record.
- `FlexibleTaskService.list(owner_id)` returns only that owner's saved tasks ordered by deadline then stable ID, with no filtering based on unsolicited schedule state.
- `FlexibleTaskService.update_by_title(owner_id, title, changes, source_message_id, idempotency_key)` and `delete_by_title(...)` resolve one exact, case-folded title and mutate it atomically inside `BEGIN IMMEDIATE`; zero or multiple matches return typed not-found/ambiguous results without mutation. Successful updates increment the task version.

- [ ] **Step 1: Write failing integration tests** for add/list persistence after repository recreation; date and instant deadline round trips; owner isolation; idempotent retry; same key/different payload conflict; version increment on update; unique-title update/delete; and duplicate-title ambiguity with no mutation.
- [ ] **Step 2: Run the task tests and verify the expected missing-table/service failures.** Run `services/api/.venv/bin/python -m pytest services/api/tests/integration/test_tasks.py -q` from repo root. Expected: FAIL before implementation.
- [ ] **Step 3: Implement task domain, service, migration and repository methods.** Migration runner must apply sorted migrations exactly once using a migration ledger; do not edit `001_initial.sql` for an already-existing database.
- [ ] **Step 4: Re-run task tests and `python3 scripts/check.py api`.** Expected: all task invariants and existing 33+ API tests pass.
- [ ] **Step 5: Independent review** checks transaction scope, owner filters on every SQL path, deadline precision, and task data exclusion from state/reminder queries.

## Task 2: MiMo Tool Calls and Assistant Application Service

**Owner:** A; **requirements:** K10, K11, K14, K16; **depends on:** Task 1.

**Files:**
- Create: `services/api/src/kairos/application/assistant.py`
- Create: `services/api/src/kairos/application/assistant_tools.py`
- Modify: `services/api/src/kairos/adapters/ai/mimo.py`
- Create: `services/api/tests/unit/test_assistant_tools.py`
- Create: `services/api/tests/unit/test_mimo_tools.py`

**Interfaces:**
- `AssistantModel.complete(messages, tools) -> ModelTurn` where `ModelTurn` contains optional text and zero or more `(tool_call_id, name, arguments_json)` calls.
- `AssistantService.handle(owner_id, client_message_id, timezone, messages) -> AssistantResult` executes at most three sequential model turns and at most one mutation per user turn; each tool result is returned to the model as a tool message.
- Exact allowed tool names: `create_flexible_task`, `query_flexible_tasks`, `update_flexible_task`, `delete_flexible_task`.
- Every tool argument is parsed against a strict Pydantic schema with forbidden extra fields. Tool operation IDs are deterministic hashes of owner, client message ID, call index, tool name, and canonical arguments.
- `AssistantResult` includes final answer and structured `action_results`; only backend action results indicate write success.

- [ ] **Step 1: Write failing unit tests** for strict tool schema parsing, explicit-intent query gating, unknown-tool rejection, malformed arguments, one-mutation limit, bounded model turns, correct task-service calls, stable idempotency across retries, and result separation from model prose.
- [ ] **Step 2: Run the new unit tests and verify expected missing-interface failures.** Run `services/api/.venv/bin/python -m pytest services/api/tests/unit/test_assistant_tools.py services/api/tests/unit/test_mimo_tools.py -q` from repo root. Expected: FAIL before implementation.
- [ ] **Step 3: Extend the MiMo adapter to decode OpenAI-compatible `tool_calls` without executing them.** Invalid JSON, missing IDs, and malformed provider responses raise sanitized `MimoError` with no key/body leakage.
- [ ] **Step 4: Implement the allowlisted assistant application service.** Calls to task queries are permitted only for an explicit user query intent; all mutations require explicit matching user intent. Ambiguous task titles return a clarification action, not a write.
- [ ] **Step 5: Re-run the focused tests plus `python3 scripts/check.py api`.** Expected: fake model tests prove exact service calls and that model-supplied answer text cannot forge action success.
- [ ] **Step 6: Independent review** attempts prompt injection, query-on-greeting, create-on-query, arbitrary tool names, tool argument smuggling, and repeated tool loops.

## Task 3: HTTP Contract and Composition Integration

**Owner:** C; **requirements:** K10, K11, K14, K15; **depends on:** Tasks 1–2.

**Files:**
- Modify: `services/api/src/kairos/api/schemas.py`
- Modify: `services/api/src/kairos/main.py`
- Modify/generated: `contracts/openapi.json`, `contracts/backend-api.d.ts`
- Create: `services/api/tests/integration/test_assistant_tasks.py`

**Interfaces:**
- `POST /api/v1/assistant/chat` accepts `client_message_id`, IANA `timezone`, and bounded `messages`; response includes `answer` and typed `action_results`.
- The handler injects an `AssistantService`; it translates domain outcomes to contract results and sanitized HTTP errors. API credentials and provider exceptions are never returned.
- Existing text-only `/assistant/chat` callers must be updated in the same contract revision; no compatibility shim may accept client-selected owner IDs or arbitrary tool lists.

- [ ] **Step 1: Write failing TestClient tests** for add/query/update/delete through fake MiMo, explicit query gating, missing provider, validation, retry idempotency, safe 502 responses, and zero flexible-task reads from `/state`.
- [ ] **Step 2: Run focused integration tests and observe expected route/schema failures.** Run `services/api/.venv/bin/python -m pytest services/api/tests/integration/test_assistant_tasks.py -q` from repo root. Expected: FAIL before implementation.
- [ ] **Step 3: Add strict request/response DTOs and compose the service in `create_app` with injectable fake model/store.** Preserve owner identity from the trusted application boundary; keep model provider config in server environment only.
- [ ] **Step 4: Regenerate contract artifacts** using `PYTHONPATH=services/api/src services/api/.venv/bin/python scripts/generate_contracts.py`; then run `python3 scripts/check.py contracts`.
- [ ] **Step 5: Run `python3 scripts/check.py api` and verify focused HTTP tests.** Expected: deterministic fake-model integration passes; live-provider check remains a separate online evaluation.
- [ ] **Step 6: Independent review** checks request bounds, owner isolation, idempotency scope, API error leakage and contract equivalence.

## Task 4: Frontend Structured Action Results

**Owner:** U; **requirements:** K10, K11, K12, K13, K16; **depends on:** Task 3.

**Files:**
- Modify: `apps/web/src/App.vue`
- Modify: `apps/web/src/assistant/sessionStore.ts`
- Modify: `apps/web/src/assistant/Conversation.vue`
- Modify: `apps/web/src/assistant/AssistantPanel.vue`
- Modify: `apps/web/tests/assistant/session.test.mjs`
- Create: `apps/web/tests/assistant/action-results.test.mjs`

**Interfaces:**
- Frontend sends a stable `client_message_id`, the browser IANA timezone, and bounded current-session user/assistant messages.
- `AssistantReply.action_results` uses generated `components['schemas']['AssistantActionResult']` types only.
- Render confirmed task adds/updates/deletes and query results from structured API data; never infer success from the model's answer string.
- Failed/ambiguous operations preserve the composer input and conversation and render a clarification/error result without claiming a write.

- [ ] **Step 1: Write failing session/component tests** for action-result rendering, successful task facts sourced only from structured fields, ambiguous operation retaining input, duplicate request ID on retry, and user timezone propagation.
- [ ] **Step 2: Run focused frontend tests and verify the expected missing action-result behavior.** Run `node --experimental-strip-types --test tests/assistant/action-results.test.mjs` from `apps/web`. Expected: FAIL before implementation.
- [ ] **Step 3: Connect generated request/response types and render structured action receipts/query cards.** Keep task data confined to the assistant conversation; do not add a default task panel or scene reminder.
- [ ] **Step 4: Run `python3 scripts/check.py web` and the focused UI tests.** Expected: Vue typecheck, all frontend tests and production build pass.
- [ ] **Step 5: Independent review** verifies no task data leaks into the scene, event-time refresh, or closed assistant accessibility tree.

## Task 5: Cross-Layer Verification and Handoff

**Owner:** Q; **requirements:** K01, K10, K11, K14, K15, K16; **depends on:** Tasks 1–4.

**Files:**
- Modify: `tests/e2e/` only if a real browser harness has been established; otherwise add API-backed journey tests under `services/api/tests/integration/` and clearly retain `e2e` as `NOT_RUN`.
- Create: `docs/evidence/<revision>/limited-ai-flexible-tasks.md`
- Modify: `docs/memory/PRODUCT_MEMORY.md`, `docs/exec-plans/active/2026-09-26-rebuild.md` only with actual verified progress.

- [ ] **Step 1: Add a journey proving** user explicitly asks to create “周日前完成操作系统实验”; task persists; after a fresh assistant session it is hidden until explicit query; query returns the persisted task; no event/reminder/state record is created.
- [ ] **Step 2: Add adversarial journeys** for a task name containing prompt injection, model-requested unsupported event deletion, ambiguous duplicate-title deletion, and a failed provider response. Assert storage invariants, not just answer copy.
- [ ] **Step 3: Run fresh `python3 scripts/check.py docs`, `architecture`, `contracts`, `api`, and `web`.** Record exact results and keep `e2e` marked `NOT_RUN` if no real browser journey exists.
- [ ] **Step 4: Q reviews changed files and evidence independently.** Resolve load-bearing findings before marking this milestone verified.
- [ ] **Step 5: Coordinator updates plan ledger and reports what remains.** Do not mark rigid event management complete; that is the next milestone.

## Follow-on Milestones (separate plans)

1. **Rigid event assistant:** event queries, draft creation/clarification/commit endpoint wiring, explicit modification/deletion proposal confirmations, and single-occurrence exception actions. Reuse DraftService/OccurrenceService; first verify current unsupported route behavior and add tests. No model call may commit a draft.
2. **Conflict presentation:** expose actual conflict sets and state revisions, add atomic user choice command and idempotency; keep this unavailable to AI so only direct user choice can mark other instances missed.
3. **Weather assistant:** only after a real weather provider and freshness contract are selected; AI can query provider facts, not fabricate weather or change scene inputs.

## Execution Notes

- This plan intentionally implements only the first allowed management slice. Completion does not mean all rigid event operations or weather queries are delivered.
- Existing dirty working-tree changes predate this plan. Review every diff and stage only files named in the current task; do not commit, reset, or format unrelated user work.
- Shared migrations, schemas, contracts, and `main.py` remain coordinator-serialized even when task-local modules are delegated.
- Live MiMo evaluation is separate from offline tests and must not print or log the API key or full user conversation.
