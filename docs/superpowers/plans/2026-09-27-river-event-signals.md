# River Event Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show confirmed rigid events as a red river ring that dissolves when the event ends, and occasionally surface a saved flexible task as a yellow encouragement ring during FREE.

**Architecture:** Add an owner-scoped read-only API for saved flexible tasks. Keep real event/task state in the app and pass only visual signals into a presentation overlay anchored to the river; visual timers never change business state. The yellow cue is session-local and chooses only from persisted user tasks.

**Tech Stack:** Vue 3, TypeScript, Canvas-adjacent HTML/SVG presentation, FastAPI, existing generated OpenAPI types.

**Spec:** `docs/memory/PRODUCT_MEMORY.md` (new user-approved rule, 2026-09-27); `docs/design/VISUAL_QUALITY.md`.

## Global Constraints

- K06 reminder acknowledgement closes the reminder; unacknowledged reminder visuals may intensify without displaying a countdown.
- K07 rigid events enter and leave by actual event boundaries, independently of acknowledgement.
- K10 flexible tasks are user-authored and persisted.
- K11 new approval: existing flexible tasks may be randomly surfaced as encouragement only during FREE; no task is created, scheduled, started, or modified by the cue.
- K16 motion remains interruptible, low-intensity, and reduced-motion aware.
- No clocks, timeline, next-event preview, numeric countdown, progress, or task list is introduced.
- Only `apps/web/**`, `services/api/**`, `contracts/**`, `docs/memory/PRODUCT_MEMORY.md`, `docs/design/VISUAL_QUALITY.md`, `docs/engineering/HARNESS.md`, and this plan may change. Legacy directories remain read-only.
- No automated tests are added or run in this task; behavior claims must stay bounded to static/build checks and visual review.

## Review Focus

- Refresh or API failure must not invent flexible tasks or treat unavailable data as an empty list.
- A fixed event ending or being excused removes only its own red ring; delayed stale state cannot keep it alive.
- Yellow cues never show while a rigid event is active, a conflict is unresolved, or the assistant is open.
- Reduced-motion mode must show stable signals without pulsing or animated erosion.
- Multiple simultaneous events must continue to honor the existing explicit conflict choice.

## File Map

- `services/api/src/kairos/main.py` and API schema source: add an owner-scoped GET list route for persisted flexible tasks.
- `contracts/openapi.json`, `contracts/backend-api.d.ts`: regenerate from the API schema; coordinator only.
- `apps/web/src/presentation/ActiveEventLayer.vue`: central, restrained rigid-event prompt inspired by the reference overlay; its actions remain available.
- `apps/web/src/presentation/SceneEventSignals.vue`: render a river-anchored red or yellow ring and transient yellow task text.
- `apps/web/src/App.vue`: fetch and reconcile saved flexible tasks, apply FREE/session cadence, and pass active signal state.
- `docs/memory/PRODUCT_MEMORY.md`: record the superseding 2026-09-27 user decision.
- `docs/engineering/HARNESS.md`: align K10/K11 acceptance with the superseding behavior.
- `docs/superpowers/plans/2026-09-27-river-event-signals.md`: track this execution.

## Tasks

### Task 1: Persisted flexible-task read route

**Files:** API route/schema sources only; do not edit generated contracts or web files.

- [x] Add `GET /api/v1/flexible-tasks` returning the current authenticated owner’s saved tasks using existing `FlexibleTask` fields; no writes or new task status semantics.
- [x] Route ownership derives from the trusted request context and repository errors remain errors rather than an empty task list.

### Task 2: River signal presentation

**Files:** `apps/web/src/presentation/ActiveEventLayer.vue`, `apps/web/src/presentation/SceneEventSignals.vue` only.

- [x] Use a centered, low-contrast anchor prompt for rigid event details; after about 3.2 seconds it yields to a quiet river ring, while actions remain reopenable.
- [x] Implement props for the active rigid signal and optional selected flexible-task signal.
- [x] Red ring remains while the rigid occurrence is active and dissolves only on actual end/state removal. Yellow ring is momentary encouragement with no action/state transition.
- [x] Use viewport-relative lower-scene placement aligned with the existing 78% waterline, restrained opacity/scale, and a reduced-motion static state. Do not use canvas demo event seeding or demo clocks.

### Task 3: Contract and app state integration

**Files:** generated contracts (coordinator), `apps/web/src/App.vue`.

- [x] Regenerate OpenAPI and TypeScript contract artifacts from the API schema.
- [x] Load saved flexible tasks through the read-only route; preserve unavailable vs empty states, refresh at mount/known flexible-task writes and after stale page focus, never on animation frames.
- [x] During FREE only, choose an existing task at a randomized 45–90 minute interval, capped at one cue per hour; pause while assistant/reminder/conflict/rigid event is active. Selection cadence is session-local and never mutates the saved task.
- [x] Bind rigid occurrence identity and actual active interval to the red signal. Keep reminder acknowledge/exception behavior and existing conflict choice intact.

### Task 4: Product memory and bounded verification

**Files:** `docs/memory/PRODUCT_MEMORY.md`, `docs/design/VISUAL_QUALITY.md`, `docs/engineering/HARNESS.md`, this plan.

- [x] Supersede the prior “flexible tasks stay hidden unless asked” rule with the approved low-frequency random encouragement behavior while retaining no auto-scheduling/no task mutation; align K10/K11 and visual guidance.
- [x] Record exact code paths changed and run non-test static/build checks. Live page loaded and showed no console errors; no active-event fixture existed, so the event ring's appearance still needs hands-on visual review.

## Execution Evidence

- Changed: `services/api/src/kairos/main.py`, `services/api/src/kairos/api/schemas.py`, generated `contracts/openapi.json` and `contracts/backend-api.d.ts`, `apps/web/src/App.vue`, `apps/web/src/presentation/ActiveEventLayer.vue`, `apps/web/src/presentation/SceneEventSignals.vue`, `docs/memory/PRODUCT_MEMORY.md`, `docs/design/VISUAL_QUALITY.md`, and `docs/engineering/HARNESS.md`.
- `npm run build` — PASS (Vue typecheck and Vite production build).
- `python3 scripts/check.py docs` — PASS.
- `services/api/.venv/bin/python -m compileall -q services/api/src/kairos` — PASS.
- `git diff --check` — PASS.
- Automated tests were neither added nor run. The live page was visually inspected at 319 × 683; it was a FREE night scene with no active event or saved-task cue, so ring-state visual acceptance remains outstanding.
