# Kairos Assistant Decision Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Let MiMo choose naturally among Kairos-authorized assistant actions and manage rigid-event changes through reviewable proposals, while the user keeps final control.

**Architecture:** The model chooses from a finite tool list. The API validates typed arguments, owner-scoped targets, user-grounded event details, and confirmation boundaries before calling existing application/repository operations. Rigid changes return structured proposals; the web client commits them only after an explicit review action. Conflict choice and the scene exception button remain direct user actions.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite; Vue 3, TypeScript; generated OpenAPI client types.

**Spec:** `docs/superpowers/specs/2026-09-26-ai-limited-authority-design.md`; confirmed product decisions in `docs/memory/PRODUCT_MEMORY.md`; acceptance evidence in `docs/engineering/HARNESS.md`.

## Global Constraints

- The model chooses only among fixed, typed Kairos tools; it never receives database, arbitrary HTTP, scene, clock, reminder, or conflict-decision control.
- Rigid event creation is a draft until the user explicitly confirms it.
- Rigid event updates and deletions are proposals until the user reviews and confirms them.
- A repeated event defaults to the current occurrence; a series operation requires the user to name the series scope.
- An occurrence exception changes only that occurrence; conflict decisions remain explicit user actions.
- Flexible tasks are written only for user-requested creation or changes, queried only on user request, and never scheduled into free time.
- Weather is read-only, requires a city named in the current user turn, and reports source/freshness or unavailability.
- The server injects owner identity and checks ownership, version, idempotency, and grounded event details.
- `python3 scripts/check.py e2e` remains `NOT_RUN`; API and Web checks do not substitute for browser evidence.

## Review Focus

- A negated, hypothetical, or quoted event command must not create a draft or proposal.
- A model-selected read can access only the current user's records and must not run for unrelated chat.
- A fabricated/stale event ID or version cannot produce a proposal.
- A repeated event edit defaults to one occurrence; series scope needs explicit user wording.
- A proposal card must show the exact change and cannot commit without an explicit user action.

## File Ownership

- API implementer: `services/api/src/kairos/application/assistant_tasks.py`, `services/api/tests/unit/test_assistant_actions.py`, `services/api/tests/integration/test_assistant_task_http.py`.
- Contract coordinator: `services/api/src/kairos/api/schemas.py`, `services/api/src/kairos/main.py`, `contracts/openapi.json`, `contracts/backend-api.d.ts`, `docs/memory/PRODUCT_MEMORY.md`.
- Web implementer: `apps/web/src/assistant/sessionStore.ts`, `apps/web/src/assistant/Conversation.vue`, `apps/web/src/assistant/AssistantPanel.vue`, `apps/web/src/App.vue`, matching assistant tests.
- No two workers edit the same file. The coordinator owns shared schemas and generated contracts and completes that work before dispatching dependent implementation.

## Tasks

### Task 1: Model-selected actions with request-grounded server validation

**Files:** API ownership paths above.

- [ ] Add tests proving the model can choose a rigid-event draft from natural event wording that does not match the legacy rigid-event keyword list.
- [ ] Add negative tests for a greeting, unrelated question, explicit denial, hypothetical wording, and quoted command; assert no write or owner data read occurs.
- [ ] Remove deterministic query short-circuits so the model chooses the authorized query tool; preserve server-derived query responses and owner scope.
- [ ] Replace action-name equality as the sole gate with action-specific validation: bounded reads, current-user grounding for task titles and weather city, strict server parsing for event date/time/title, and explicit denial protection for all writes.
- [ ] Keep every rigid-create result uncommitted; run focused tests, then `python3 scripts/check.py api`.

### Task 2: Rigid-event change proposal action and chat confirmation contract

**Files:** contract coordinator paths plus API ownership paths above.

- [ ] Add failing tests for model-selected occurrence update/delete proposals, explicit series scope, missing/ambiguous target, stale version, and proposal data containing the exact proposed fields.
- [ ] Add one typed `propose_rigid_event_change` tool that accepts an owner-scoped target ID, scope, expected version, action, and changes; server defaults to occurrence scope and rejects series scope without explicit user wording.
- [ ] Let a successful `query_rigid_events` tool result continue through the model tool loop as trusted tool output, so a natural-language change request can query its owner-scoped target and then propose a change in the same API turn. Attach the owner event's series version to query records so the model can propose a series operation only when the user explicitly named that scope.
- [ ] Return exactly `{proposal_id, target_id, scope, revision, action, summary, confirmation_digest, status, target_title, changes}` as structured action data. `target_title` is resolved from the owner-scoped event; `changes` contains the exact validated proposed values. Never commit from a model tool call.
- [ ] Add integration tests against a temporary SQLite database; verify the proposal exists but the event is unchanged until the commit endpoint is called.
- [ ] Regenerate and verify OpenAPI/types only if the public response schema changes; run `python3 scripts/check.py contracts` and `python3 scripts/check.py api`.

### Task 3: Review and commit rigid-event proposals in the assistant panel

**Files:** Web ownership paths above.

- [ ] Add tests for rendering exact occurrence/series scope and changed field values, and for no commit until the user presses the confirmation control.
- [ ] Add a session command matching `POST /api/v1/event-change-proposals/{proposal_id}/commit` with a stable idempotency key and revision/digest binding.
- [ ] Render proposal status distinctly from successful completed actions; emit confirmation only from the explicit button; show success only from the commit response and preserve the proposal on conflict/error.
- [ ] Add tests for rejected/expired proposals and duplicate submission; run `python3 scripts/check.py web`.

### Task 4: Documentation and integrated verification

**Files:** `docs/memory/PRODUCT_MEMORY.md`, relevant assistant tests, task evidence under `docs/evidence/` if required by the active Harness workflow.

- [ ] Record the user's decision that model tool selection is semantic and flexible while server execution stays bounded.
- [ ] Add requirement-to-test mapping for model action selection, proposal confirmation, and the explicitly unsupported conflict-decision tool.
- [ ] Run `python3 scripts/check.py docs`, `python3 scripts/check.py contracts`, `python3 scripts/check.py api`, and `python3 scripts/check.py web`.
- [ ] Record live MiMo semantic evaluation as `NOT_RUN` unless executed with a versioned evaluation set; do not claim browser acceptance until a real browser journey is captured.
