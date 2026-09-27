# 河面柔性任务生命周期实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持多个无提醒黄圈在水线下随机避让，用户可接受、暂停或完成柔性任务，任务生命周期由后端持久化。

**Architecture:** 后端为柔性任务增加 `planned | active | completed` 状态和 owner/version/idempotency 校验；前端使用独立纯布局协调器根据逐点动态水线放置红黄圈，并用直接 API 操作任务状态。短时提示寿命只属于展示层，进行中状态从后端恢复；预览页使用隔离样例演示多圈、避让和交互。

**Tech Stack:** Vue 3、TypeScript、Canvas 2D、FastAPI、Pydantic、SQLite、Node test runner、pytest、OpenAPI TypeScript generator。

**Spec:** `docs/superpowers/specs/2026-09-27-flexible-task-river-lifecycle-design.md`

## Global Constraints

- 场景信号全部位于实时水线下方，随机落位并彼此不重叠；没有合法空间时暂缓新圈。
- 黄色临时圈不伴随文案或通知；每次显示随机持续 5–10 分钟，详情打开时继续计时。
- 用户接受、暂停、完成是直接 UI 操作，不经过 AI；AI 不获得新的生命周期写权限。
- 暂停回到 `planned` 并留在规划列表；完成持久化且不再参加候选。
- 只读参考 `XiAnHacker-view-v1/` 与 `XiAnHacker-backend-v1/`，不导入或依赖其中代码、数据、密钥或环境。
- Web `e2e` 检查仍是 `NOT_RUN`，不得将构建/API 检查表述为浏览器端到端验收。

## Review Focus

1. 候选水线取样需使用 Canvas 的 CSS 像素与当前视口坐标；测试不同 x 上的线高和圈位转换。
2. 多个活动圈挤满狭窄水域时，新增临时圈延后，不遮叠已有圈；测试无合法插槽时返回 `null`。
3. 状态请求发生并发/重试时，旧版本或跨 owner 写入不能改变任务；测试 409、404 与幂等重放。
4. 临时圈到期时若详情仍打开，圈消失但详情保留且用户仍可接受；使用注入计时器测试。
5. 页面隐藏、助手打开、提醒/冲突出现期间不新建提示；恢复时不补播已过期提示，并保留后端 `active` 圈。

---

## 文件与负责人

| Workstream | 唯一写入负责人 | 写入路径 |
| --- | --- | --- |
| 后端生命周期 | Backend agent | `services/api/src/kairos/domain/tasks.py`, `application/tasks.py`, `api/schemas.py`, `main.py`, `adapters/persistence/sqlite.py`, new migration, `services/api/tests/**` |
| 场景几何与组件 | Scene agent | `apps/web/src/scene/flow/**`, new marker layout module, `apps/web/src/presentation/SceneEventSignals.vue`, related scene/presentation tests |
| App/任务详情/预览 | Coordinator | `apps/web/src/App.vue`, new flexible-task detail component, `apps/web/src/presentation/event-signals-preview.html`, `.ts`, relevant tests |
| Shared contract | Coordinator, serial after backend schema | `contracts/openapi.json`, `contracts/backend-api.d.ts`, `scripts/verify_contract_http.py` if required |
| Product/visual docs | Coordinator | `docs/memory/PRODUCT_MEMORY.md`, `docs/design/VISUAL_QUALITY.md` |

Parallel work starts only after the backend schema and scene sampling interfaces are agreed. No two workers edit the same file. Contract files and App integration remain coordinator-owned.

### Task 1: Persist lifecycle state for flexible tasks

**Requirements:** planned-to-active acceptance; active-to-planned pause; active-to-completed completion; owner/version/idempotency; existing records default to planned.

**Files:**
- Modify: `services/api/src/kairos/domain/tasks.py`
- Modify: `services/api/src/kairos/application/tasks.py`
- Modify: `services/api/src/kairos/adapters/persistence/sqlite.py`
- Modify: `services/api/src/kairos/api/schemas.py`
- Modify: `services/api/src/kairos/main.py`
- Create: `services/api/migrations/004_flexible_task_lifecycle.sql`
- Create: `services/api/tests/integration/test_task_lifecycle.py`
- Modify: `services/api/tests/integration/test_tasks.py` (update recorded migration list and retain legacy-upgrade assertion)

**Interfaces:**
- `TaskLifecycleStatus = Literal["planned", "active", "completed"]`.
- `FlexibleTaskRecord.lifecycle_status: TaskLifecycleStatus`, default `"planned"` for old rows.
- `FlexibleTaskService.transition(owner_id: str, task_id: str, target: TaskLifecycleStatus, expected_version: int, idempotency_key: str) -> FlexibleTaskRecord`.
- `POST /api/v1/flexible-tasks/{task_id}/lifecycle` accepts `{status, expected_version}` and `Idempotency-Key`; returns the complete task DTO.
- Valid transitions: `planned -> active`, `active -> planned`, `active -> completed`; repeated identical idempotent requests return the original response, stale versions return 409, unknown/foreign task IDs return 404.

- [x] **Step 1: Write failing integration tests** for default lifecycle state, all valid transitions, invalid transitions, version conflict, owner isolation, and idempotent replay.
- [x] **Step 2: Run the focused pytest file and confirm failures** are caused by missing lifecycle behavior.
- [x] **Step 3: Implement the domain transition validator, SQLite migration/atomic update, application method, DTO field, and owner-scoped endpoint.** Increment task version once per accepted transition.
- [x] **Step 4: Rerun the focused tests and the API check.** Run `python3 scripts/check.py api`; expect PASS.

### Task 2: Generate and verify the lifecycle contract

**Requirements:** GET/list/assistant query DTOs expose lifecycle state; browser code uses generated types, not hand-written duplicate contracts.

**Files:**
- Modify: `contracts/openapi.json`
- Modify: `contracts/backend-api.d.ts`
- Modify: `scripts/verify_contract_http.py` only if its expected endpoint behavior needs a focused assertion.
- Test: `python3 scripts/check.py contracts`

**Interfaces:**
- `FlexibleTask.lifecycle_status` is exactly `planned | active | completed`.
- Lifecycle request body is `{status, expected_version}`; status response is `FlexibleTask`.

- [x] **Step 1: Add a contract assertion** that lifecycle state and the task lifecycle path exist with matching request/response schemas.
- [x] **Step 2: Run `python3 scripts/check.py contracts` and confirm the missing generated contract is detected.**
- [x] **Step 3: Run `python3 scripts/generate_contracts.py`; do not hand-edit generated types.**
- [x] **Step 4: Rerun the contracts check and verify generated files are stable.**

### Task 3: Place multiple markers below the sampled waterline

**Requirements:** random x/offset placement beneath local dynamic waterline; no overlap among rigid and flexible markers; defer when no available slot.

**Files:**
- Create: `apps/web/src/presentation/markerLayout.ts`
- Modify: `apps/web/src/scene/flow/painter.ts`
- Modify: `apps/web/src/scene/flow/mount.ts`
- Modify: `apps/web/src/scene/flow/ContinuousFlowScene.vue`
- Modify: `apps/web/src/presentation/SceneEventSignals.vue`
- Create: `apps/web/tests/presentation/marker-layout.test.mjs`
- Modify: `apps/web/tests/presentation/event-layers.test.mjs`

**Interfaces:**
- `type SceneMarker = { id: string; kind: "rigid" | "flexible"; diameter: number; x: number; offsetBelowWaterline: number }`.
- `type SceneSignal = { id: string; kind: "rigid" | "flexible"; accessibleName: string; x: number; y: number; diameter: number }`, with x/y in scene-local CSS pixels.
- `findMarkerPosition(input: { id: string; kind: SceneMarker["kind"]; width: number; height: number; diameter: number; minGap: number; waterlineAt: (x: number) => number; existing: SceneMarker[]; random: () => number; attempts?: number }): SceneMarker | null`.
- `screenYForMarker(marker: SceneMarker, waterlineAt: (x: number) => number): number`.
- `ContinuousFlowScene` emits `waterlineAt(x: number) => number` in scene-local CSS pixels for the current wave; geometry sampling remains sourced from exported `waterSurfaceYAt(x, height, tide, elapsedSeconds)`.
- `SceneEventSignals` consumes positioned `SceneSignal[]` and emits `select(signalId)`; it contains no task mutation logic or temporary prompt copy.
- New random positions are assigned only when a marker enters/exits or viewport geometry changes; active marker positions stay stable between those operations.

- [x] **Step 1: Write failing geometry tests** for below-waterline placement, collision avoidance, deterministic injected randomness, stable existing positions, and `null` when no slot fits.
- [x] **Step 2: Run `node --experimental-strip-types --test tests/presentation/marker-layout.test.mjs` and confirm expected failures.**
- [x] **Step 3: Implement bounded candidate sampling and actual per-x waterline sampling in CSS pixels.**
- [x] **Step 4: Bind `SceneEventSignals` to positioned `SceneSignal[]`, emit ring selection, and remove centered/paired fixed positions and all flexible prompt copy.**
- [x] **Step 5: Rerun geometry and event-layer tests.**

### Task 4: Add task detail actions and independent cue lifetimes

**Requirements:** multiple yellow cues, each 5–10 minute timer; detail timer continues; accept makes durable ring; pause returns to planned and removes ring; complete removes and records; no AI round trip.

**Files:**
- Create: `apps/web/src/presentation/FlexibleTaskDetail.vue`
- Create: `apps/web/src/presentation/flexibleTaskSignals.ts`
- Modify: `apps/web/src/App.vue`
- Modify: `apps/web/src/presentation/sceneMode.ts` only if marker visibility cannot be represented by current state.
- Create/modify: `apps/web/tests/presentation/flexible-task-lifecycle.test.mjs`
- Modify: `apps/web/tests/assistant/**` only to assert UI lifecycle operations do not use assistant commands if an existing boundary fixture supports this.

**Interfaces:**
- UI task types use generated `FlexibleTask` including `lifecycle_status`.
- Detail component receives `task`, `cueExpiresAt`, `busy`, and `error`; emits `accept(taskId, version)`, `pause(taskId, version)`, `complete(taskId, version)`, `close`.
- `App.vue` performs the lifecycle POST with a fresh idempotency key for each user intent, updates task state only from a successful response, and reconciles from GET after mutation.
- Temporary cue starts with an injected random lifetime in `[300_000, 600_000]` milliseconds; timers use wall clock and continue while details are open. On expiry, remove only the scene marker, not the open detail.
- Only `planned` tasks are random candidates; all `active` tasks restore persistent yellow markers on page load; `completed` tasks are excluded from all scene candidates.

- [x] **Step 1: Write failing UI/state tests** for silent ring appearance, multiple independent expiry timers, detail remaining open on expiry, accept, pause, completion, refresh restoration, API failure, and no AI call.
- [x] **Step 2: Run the focused Node tests and confirm failures for missing state/actions.**
- [x] **Step 3: Implement task detail actions and direct lifecycle API synchronization.**
- [x] **Step 4: Run the focused frontend tests and `npm run build`; expect PASS.**

### Task 5: Extend the development preview and visual verification

**Requirements:** preview can show several flexible markers, collision-free random placement, real waterline tracking, and lifecycle actions without touching backend data.

**Files:**
- Modify: `apps/web/src/presentation/event-signals-preview.html`
- Modify: `apps/web/src/presentation/event-signals-preview.ts`
- Modify: `docs/design/VISUAL_QUALITY.md`
- Modify: `docs/memory/PRODUCT_MEMORY.md`

- [x] **Step 1: Add local fixtures** for one red marker, multiple temporary yellow markers with separate expiries, and accepted persistent markers; add accept/pause/complete actions backed only by preview-local state.
- [x] **Step 2: Run `npm run build` and reload `/src/presentation/event-signals-preview.html`.**
- [x] **Step 3: Visually inspect a desktop and narrow phone viewport**; verify markers stay below the moving line, never overlap, and are deferred when placement fails.
- [x] **Step 4: Verify yellow rings appear without copy, detail click works, timer continues while detail is open, accepted rings persist, pause removes the ring but retains the task, and completed tasks do not reappear.**
- [x] **Step 5: Record exact viewports and tested behavior in `VISUAL_QUALITY.md`; keep untested viewports explicitly pending.**

### Task 6: Integrated checks and final review

**Files:** all workstream files above; no additional broad refactors.

- [x] Run `python3 scripts/check.py contracts`, `python3 scripts/check.py api`, and `python3 scripts/check.py web`.
- [x] Run focused lifecycle, placement, and presentation tests; run the full project suites if the scoped checks pass.
- [x] Confirm preview does not call APIs or mutate real task/event records.
- [x] Review `git diff --check`, inspect all modified files, preserve unrelated pre-existing changes, and report browser e2e as `NOT_RUN` unless actually exercised.

## Dependency Order

Task 1 defines service lifecycle semantics. The coordinator then generates the shared contract in Task 2. Tasks 3 and 4 can proceed independently after their TypeScript/API seams are agreed; Task 5 integrates both preview and UI behavior. Task 6 runs after all workstreams finish.

## Execution Method

Use subagent-driven implementation after approval of this plan: one backend agent owns Task 1; one frontend scene agent owns Task 3; coordinator owns Tasks 2, 4, 5 and 6, serializing shared contract generation after Task 1. A fresh reviewer inspects the complete change at the end. No agent may edit files owned by another workstream.
