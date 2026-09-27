<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import ContinuousFlowScene from './scene/flow/ContinuousFlowScene.vue'
import { RealClock } from './platform/clocks.ts'
import { SceneEnvironmentSession } from './scene/session.ts'
import AssistantPanel from './assistant/AssistantPanel.vue'
import { toAssistantChatMessages } from './assistant/chatPayload.ts'
import { assistantSession } from './assistant/sessionStore.ts'
import ReminderLayer from './presentation/ReminderLayer.vue'
import { bindTimePeek } from './platform/timePeek.ts'
import { sceneModeForActiveCount } from './presentation/sceneMode.ts'
import ActiveEventLayer from './presentation/ActiveEventLayer.vue'
import ConflictChoice from './presentation/ConflictChoice.vue'
import SceneEventSignals from './presentation/SceneEventSignals.vue'
import FlexibleTaskDetail from './presentation/FlexibleTaskDetail.vue'
import { activeFlexibleTasks, FlexibleTaskSignals, eligibleFlexibleTasks } from './presentation/flexibleTaskSignals.ts'
import { transitionFlexibleTaskRequest } from './presentation/flexibleTaskClient.ts'
import { findMarkerPosition, screenYForMarker, type SceneMarker, type SceneSignal } from './presentation/markerLayout.ts'
import type { components } from '../../../contracts/backend-api.d.ts'

const connection = ref<'checking' | 'connected' | 'failed'>('checking')
const realClock = new RealClock()
const environment = new SceneEnvironmentSession(realClock)
const frame = shallowRef(environment.frame)
const sceneMode = computed(() => sceneModeForActiveCount(assistantSession.state.activeOccurrences.length))
const activeOccurrence = computed(() => assistantSession.state.activeOccurrences[0] ?? null)
const activeEventVisible = ref(true)
const signalOccurrence = computed(() => assistantSession.state.conflicts.length ? null : activeOccurrence.value)
const rigidSignalReady = ref(false)
const flexibleTasks = shallowRef<components['schemas']['FlexibleTaskPage']['items']>([])
const flexibleTasksReady = ref(false)
const pageVisible = ref(document.visibilityState !== 'hidden')
const flexibleCueRevision = ref(0)
const flexibleSignals = new FlexibleTaskSignals(Date.now, Math.random, () => {
  flexibleCueRevision.value++
  queueMicrotask(() => { syncSceneMarkers(); scheduleFlexibleCue() })
})
const detailTaskId = ref<string | null>(null)
const taskActionBusy = ref(false)
const taskActionError = ref('')
const sceneMarkers = shallowRef<SceneMarker[]>([])
const waterlineSampler = shallowRef<(x: number) => number>(() => Number.NaN)
const sceneSurface = ref<HTMLElement | null>(null)
const timePeekOutput = ref<HTMLElement | null>(null)
let refreshTimer = 0
let stateTimer = 0
let transitionTimer = 0
let activePromptTimer = 0
let flexibleCueTimer = 0
let lastFlexibleTasksFetch = 0
let nextFlexibleCueAt = 0
let lastFlexibleCueAt = 0
let flexibleTasksFetching = false
let resizeObserver: ResizeObserver | undefined
let wasCueSuppressed = false
let unbindTimePeek: (() => void) | undefined

const cueScheduleKey = 'kairos.flexible-cue.v1'
try {
  const raw = sessionStorage.getItem(cueScheduleKey)
  if (raw) {
    const saved = JSON.parse(raw) as { next?: unknown; last?: unknown }
    if (typeof saved.next === 'number' && Number.isFinite(saved.next)) nextFlexibleCueAt = saved.next
    if (typeof saved.last === 'number' && Number.isFinite(saved.last)) lastFlexibleCueAt = saved.last
  }
} catch { /* Session cadence is optional and never affects event/task data. */ }

function persistFlexibleCueSchedule() {
  try { sessionStorage.setItem(cueScheduleKey, JSON.stringify({ next: nextFlexibleCueAt, last: lastFlexibleCueAt })) }
  catch { /* Keep the visual cue functional when session storage is unavailable. */ }
}

function cueIsAllowed() {
  return flexibleTasksReady.value && eligibleFlexibleTasks(flexibleTasks.value, new Set(flexibleSignals.cues.keys())).length > 0 &&
    !assistantSession.state.open && assistantSession.state.activeOccurrences.length === 0 &&
    assistantSession.state.conflicts.length === 0 && assistantSession.state.reminder === null &&
    pageVisible.value
}

function scheduleFlexibleCue() {
  window.clearTimeout(flexibleCueTimer)
  flexibleCueTimer = 0
  if (!cueIsAllowed()) return
  const now = Date.now()
  if (!nextFlexibleCueAt) {
    nextFlexibleCueAt = now + (45 + Math.floor(Math.random() * 46)) * 60_000
    persistFlexibleCueSchedule()
  }
  const dueAt = lastFlexibleCueAt && now - lastFlexibleCueAt < 60 * 60_000
    ? Math.max(nextFlexibleCueAt, lastFlexibleCueAt + 60 * 60_000)
    : nextFlexibleCueAt
  flexibleCueTimer = window.setTimeout(() => {
    flexibleCueTimer = 0
    if (!cueIsAllowed()) return
    const currentTime = Date.now()
    if (lastFlexibleCueAt && currentTime - lastFlexibleCueAt < 60 * 60_000) {
      nextFlexibleCueAt = lastFlexibleCueAt + 60 * 60_000
      persistFlexibleCueSchedule()
      scheduleFlexibleCue()
      return
    }
    const choices = eligibleFlexibleTasks(flexibleTasks.value, new Set(flexibleSignals.cues.keys()))
      .sort(() => Math.random() - 0.5)
    let placed = 0
    for (const task of choices) {
      if (placed >= 3) break
      if (addFlexibleMarker(task.task_id)) { flexibleSignals.show(task.task_id); placed++ }
    }
    if (!placed) { nextFlexibleCueAt = currentTime + 60_000; persistFlexibleCueSchedule(); scheduleFlexibleCue(); return }
    lastFlexibleCueAt = currentTime
    nextFlexibleCueAt = currentTime + (45 + Math.floor(Math.random() * 46)) * 60_000
    persistFlexibleCueSchedule()
    scheduleFlexibleCue()
  }, Math.max(0, dueAt - now))
}

async function loadFlexibleTasks() {
  if (flexibleTasksFetching) return
  flexibleTasksFetching = true
  try {
    const response = await fetch('/api/v1/flexible-tasks', { cache: 'no-store' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const page = await response.json() as components['schemas']['FlexibleTaskPage']
    if (!Array.isArray(page.items) || page.items.some(task => typeof task.task_id !== 'string' || typeof task.title !== 'string')) {
      throw new Error('Invalid flexible task response')
    }
    const hadTasks = flexibleTasks.value.length > 0
    flexibleTasks.value = page.items
    flexibleTasksReady.value = true
    lastFlexibleTasksFetch = Date.now()
    if (!hadTasks && page.items.some(task => task.lifecycle_status === 'planned')) nextFlexibleCueAt = Date.now() + (45 + Math.floor(Math.random() * 46)) * 60_000
    if (!page.items.length) {
      nextFlexibleCueAt = 0
    }
    for (const taskId of [...flexibleSignals.cues.keys()]) if (!page.items.some(task => task.task_id === taskId && task.lifecycle_status === 'planned')) flexibleSignals.remove(taskId)
    if (detailTaskId.value && !page.items.some(task => task.task_id === detailTaskId.value)) detailTaskId.value = null
    syncSceneMarkers()
    persistFlexibleCueSchedule()
    scheduleFlexibleCue()
  } catch {
    flexibleTasksReady.value = false
    window.clearTimeout(flexibleCueTimer)
    flexibleCueTimer = 0
  } finally {
    flexibleTasksFetching = false
  }
}

function refreshFlexibleTasksIfStale() {
  if (Date.now() - lastFlexibleTasksFetch > 5 * 60_000) void loadFlexibleTasks()
}

function onVisibilityChange() {
  pageVisible.value = document.visibilityState !== 'hidden'
  if (document.visibilityState === 'visible') {
    flexibleSignals.expireDue()
    refreshFlexibleTasksIfStale()
  }
  syncFlexibleCue()
}

function syncFlexibleCue() {
  const suppressed = cueIsSuppressed()
  if (suppressed && !wasCueSuppressed) {
    window.clearTimeout(flexibleCueTimer)
    flexibleCueTimer = 0
    nextFlexibleCueAt = Date.now() + (45 + Math.floor(Math.random() * 46)) * 60_000
    persistFlexibleCueSchedule()
  }
  wasCueSuppressed = suppressed
  scheduleFlexibleCue()
}

function cueIsSuppressed() {
  return assistantSession.state.open || assistantSession.state.conflicts.length > 0 || assistantSession.state.reminder !== null || !pageVisible.value
}

function addFlexibleMarker(taskId: string): boolean {
  if (!sceneSurface.value) return false
  const task = flexibleTasks.value.find(item => item.task_id === taskId)
  if (!task) return false
  const existing = sceneMarkers.value
  const marker = findMarkerPosition({ id: `task:${taskId}`, kind: 'flexible', width: sceneSurface.value.clientWidth,
    height: sceneSurface.value.clientHeight, diameter: 54, minGap: 22, waterlineAt: waterlineSampler.value,
    existing, random: Math.random })
  if (!marker) return false
  sceneMarkers.value = [...existing, marker]
  return true
}

function syncSceneMarkers() {
  const required = new Set<string>()
  for (const task of activeFlexibleTasks(flexibleTasks.value)) required.add(`task:${task.task_id}`)
  if (signalOccurrence.value && rigidSignalReady.value) required.add(`rigid:${signalOccurrence.value.occurrence_id}`)
  for (const taskId of flexibleSignals.cues.keys()) required.add(`task:${taskId}`)
  let markers = sceneMarkers.value.filter(marker => required.has(marker.id))
  for (const taskId of required) {
    if (markers.some(marker => marker.id === taskId)) continue
    const kind = taskId.startsWith('rigid:') ? 'rigid' : 'flexible'
    const marker = findMarkerPosition({ id: taskId, kind, width: sceneSurface.value?.clientWidth ?? 0,
      height: sceneSurface.value?.clientHeight ?? 0, diameter: kind === 'rigid' ? 62 : 54, minGap: 22,
      waterlineAt: waterlineSampler.value, existing: markers, random: Math.random })
    if (marker) markers = [...markers, marker]
  }
  sceneMarkers.value = markers
}

function updateSceneWaterline(sample: (x: number) => number) {
  waterlineSampler.value = sample
  if (!sceneMarkers.value.length) syncSceneMarkers()
}

const sceneSignals = computed(() => {
  void flexibleCueRevision.value
  const suppressed = cueIsSuppressed()
  return sceneMarkers.value.flatMap<SceneSignal>(marker => {
    if (marker.id.startsWith('task:')) {
      const taskId = marker.id.slice(5)
      const task = flexibleTasks.value.find(item => item.task_id === taskId)
      if (!task || (task.lifecycle_status === 'planned' && (suppressed || !flexibleSignals.cues.has(taskId)))) return []
      return [{ id: marker.id, kind: 'flexible' as const, accessibleName: task.title,
        x: marker.x, y: screenYForMarker(marker, waterlineSampler.value), diameter: marker.diameter }]
    }
    const occurrence = signalOccurrence.value
    if (!occurrence || marker.id !== `rigid:${occurrence.occurrence_id}` || activeEventVisible.value) return []
    return [{ id: marker.id, kind: 'rigid' as const, accessibleName: occurrence.title,
      x: marker.x, y: screenYForMarker(marker, waterlineSampler.value), diameter: marker.diameter }]
  })
})

async function transitionFlexibleTask(taskId: string, status: 'active' | 'planned' | 'completed', version: number) {
  taskActionBusy.value = true; taskActionError.value = ''
  try {
    const updated = await transitionFlexibleTaskRequest(taskId, status, version)
    flexibleSignals.remove(taskId)
    flexibleTasks.value = flexibleTasks.value.map(task => task.task_id === taskId ? updated : task)
    syncSceneMarkers()
    if (status === 'active') detailTaskId.value = null
    if (status === 'completed' || status === 'planned') detailTaskId.value = null
    void loadFlexibleTasks()
  } catch (error) {
    taskActionError.value = error instanceof Error ? error.message : '保存失败，请稍后重试。'
  } finally { taskActionBusy.value = false }
}

watch(() => [assistantSession.state.open, assistantSession.state.activeOccurrences.length,
  assistantSession.state.conflicts.length, assistantSession.state.reminder?.reminder_id,
  flexibleTasksReady.value, flexibleTasks.value.length], syncFlexibleCue)

watch(() => [signalOccurrence.value?.occurrence_id, rigidSignalReady.value, flexibleCueRevision.value,
  ...flexibleTasks.value.map(task => `${task.task_id}:${task.lifecycle_status}`)], syncSceneMarkers)

watch(() => activeOccurrence.value?.occurrence_id, (occurrenceId) => {
  window.clearTimeout(activePromptTimer)
  activeEventVisible.value = !!occurrenceId
  rigidSignalReady.value = false
  if (!occurrenceId) return
  activePromptTimer = window.setTimeout(() => {
    if (activeOccurrence.value?.occurrence_id === occurrenceId) {
      activeEventVisible.value = false
      rigidSignalReady.value = true
      syncSceneMarkers()
    }
  }, 3_200)
})

async function encodeImage(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  const chunkSize = 0x8000
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize))
  }
  return btoa(binary)
}

assistantSession.setCommands({
  sendMessage: async (_text, clientMessageId, messages, image) => {
    const imageAttachment = image ? { mime_type: image.type, data_base64: await encodeImage(image) } : undefined
    const response = await fetch('/api/v1/assistant/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_message_id: clientMessageId,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
         messages: toAssistantChatMessages(messages), ...(imageAttachment ? { image: imageAttachment } : {}) }),
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const reply = await response.json()
    if (reply.action_results?.some((result: { action?: string; status?: string }) =>
      ['create_flexible_task', 'update_flexible_task', 'delete_flexible_task'].includes(result.action ?? '') && result.status === 'succeeded')) {
      void loadFlexibleTasks()
    }
    return reply
  },
  confirmDraft: async (draftId, request, idempotencyKey) => {
    const response = await fetch(`/api/v1/drafts/${encodeURIComponent(draftId)}/commit`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(request),
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      const detail = payload && typeof payload === 'object' ? payload.detail as unknown : null
      if (response.status === 409 && detail && typeof detail === 'object') {
        const conflict = detail as { conflict_acceptance?: unknown; conflict_pairs?: unknown }
        if (typeof conflict.conflict_acceptance === 'string' && Array.isArray(conflict.conflict_pairs)) {
          throw Object.assign(new Error('Schedule conflict requires review'), {
            conflictAcceptance: conflict.conflict_acceptance, conflictPairs: conflict.conflict_pairs,
          })
        }
      }
      throw new Error(`HTTP ${response.status}`)
    }
    const result = await response.json()
    if (result.resources?.some((resource: { resource_type?: string }) => resource.resource_type === 'flexible_task')) {
      void loadFlexibleTasks()
    }
    return result
  },
  commitProposal: async (proposalId, request, idempotencyKey) => {
    const response = await fetch(`/api/v1/event-change-proposals/${encodeURIComponent(proposalId)}/commit`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(request),
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return response.json()
  },
  getState: async () => {
    const response = await fetch('/api/v1/state', { cache: 'no-store' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return response.json()
  },
  acknowledgeReminder: async (reminder, idempotencyKey) => {
    const response = await fetch(`/api/v1/reminders/${encodeURIComponent(reminder.reminder_id)}/ack`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ expected_version: reminder.version, schedule_revision: reminder.schedule_revision }),
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
  },
  decideConflict: async (request, idempotencyKey) => {
    const response = await fetch('/api/v1/conflict-decisions', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(request),
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return response.json()
  },
  excuseOccurrence: async (occurrence, sourceActionId) => {
    const response = await fetch(`/api/v1/occurrences/${encodeURIComponent(occurrence.occurrence_id)}/exceptions`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': sourceActionId },
      body: JSON.stringify({ type: 'excused', expected_version: occurrence.version, source_action_id: sourceActionId }),
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return response.json()
  },
})

async function checkConnection() {
  connection.value = 'checking'
  try {
    const response = await fetch('/api/v1/health', { cache: 'no-store' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const body: unknown = await response.json()
    if (typeof body !== 'object' || body === null || !('status' in body) || body.status !== 'ok') throw new Error('Invalid health response')
    connection.value = 'connected'
  } catch {
    connection.value = 'failed'
  }
}

function refreshEnvironment() {
  frame.value = environment.refresh()
}

function scheduleStateTransition() {
  window.clearTimeout(transitionTimer)
  transitionTimer = 0
  const boundary = assistantSession.state.nextTransitionAt
  if (!boundary) return
  const delay = Date.parse(boundary) - Date.now()
  if (delay <= 0) return
  transitionTimer = window.setTimeout(() => {
    transitionTimer = 0
    void refreshState()
  }, delay + 30)
}

async function refreshState() {
  await assistantSession.refreshState()
  scheduleStateTransition()
}

onMounted(() => {
  if (sceneSurface.value && timePeekOutput.value) unbindTimePeek = bindTimePeek(sceneSurface.value, timePeekOutput.value, realClock)
  if (sceneSurface.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => { sceneMarkers.value = []; syncSceneMarkers() })
    resizeObserver.observe(sceneSurface.value)
  }
  void checkConnection()
  refreshState()
  void loadFlexibleTasks()
  stateTimer = window.setInterval(() => { void refreshState() }, 15_000)
  refreshTimer = window.setInterval(refreshEnvironment, 1_000)
  window.addEventListener('focus', refreshFlexibleTasksIfStale)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  window.clearInterval(refreshTimer)
  window.clearInterval(stateTimer)
  window.clearTimeout(transitionTimer)
  window.clearTimeout(activePromptTimer)
  window.clearTimeout(flexibleCueTimer)
  flexibleSignals.dispose()
  resizeObserver?.disconnect()
  window.removeEventListener('focus', refreshFlexibleTasksIfStale)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  unbindTimePeek?.()
})
</script>

<template>
  <main ref="sceneSurface" class="app-shell" aria-label="Kairos 自然场景">
    <ContinuousFlowScene class="scene-backdrop" :frame="frame" :mode="sceneMode" @waterline-at="updateSceneWaterline" />
    <SceneEventSignals :signals="sceneSignals" @select="(id) => { const taskId = id.startsWith('task:') ? id.slice(5) : null; if (taskId) { detailTaskId = taskId; taskActionError = '' } else activeEventVisible = true }" />
    <div ref="timePeekOutput" class="time-peek" role="status" aria-live="off" aria-hidden="true"></div>
    <div v-if="assistantSession.state.conflicts.length" class="conflict-stack" aria-label="事件冲突">
      <ConflictChoice v-for="conflict in assistantSession.state.conflicts" :key="conflict.conflict_id"
        :conflict="conflict" :occurrences="assistantSession.state.activeOccurrences"
        :pending="assistantSession.state.conflictPending"
        @choose="assistantSession.chooseConflict" />
    </div>
    <ActiveEventLayer v-else-if="activeEventVisible" :occurrence="activeOccurrence"
      :exception-pending="assistantSession.state.exceptionPendingId === activeOccurrence?.occurrence_id"
      @acknowledge="activeEventVisible = false; rigidSignalReady = true"
      @exception="assistantSession.excuseOccurrence" />
    <div v-if="assistantSession.state.notice" class="event-action-notice" role="status" aria-live="polite">
      <span>{{ assistantSession.state.notice }}</span>
      <button type="button" aria-label="关闭状态提示" @click="assistantSession.state.notice = ''">×</button>
    </div>
    <ReminderLayer :reminder="assistantSession.state.reminder" :assistant-open="assistantSession.state.open" :pending="assistantSession.state.pending === 'confirming'" @acknowledge="assistantSession.acknowledgeReminder" />
    <div v-if="connection === 'failed'" class="connection-error" role="status">
      <span>助手暂时离线</span>
      <button type="button" aria-label="重试连接助手服务" @click="checkConnection">重试</button>
    </div>
    <button
      class="assistant-entry"
      type="button"
      :aria-expanded="assistantSession.state.open"
      aria-label="打开 Kairos 助手"
      @click="assistantSession.open()"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none">
        <path d="M5 18.5 6.2 15A7.5 7.5 0 1 1 9 18.1L5 18.5Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" />
        <path d="M8.8 11.8h.1m3.05 0h.1m3.05 0h.1" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
      </svg>
      <span>问 Kairos</span>
    </button>
    <AssistantPanel />
    <FlexibleTaskDetail v-if="detailTaskId && flexibleTasks.find(task => task.task_id === detailTaskId)"
      :task="flexibleTasks.find(task => task.task_id === detailTaskId)!"
      :cue-expires-at="flexibleSignals.cues.get(detailTaskId)?.expiresAt ?? null"
      :busy="taskActionBusy" :error="taskActionError"
      @accept="(id, version) => transitionFlexibleTask(id, 'active', version)"
      @pause="(id, version) => transitionFlexibleTask(id, 'planned', version)"
      @complete="(id, version) => transitionFlexibleTask(id, 'completed', version)"
      @close="detailTaskId = null" />
  </main>
</template>

<style>
* { box-sizing: border-box; }
html, body, #app { width: 100%; height: 100%; margin: 0; }
body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; }
.app-shell { position: relative; isolation: isolate; width: 100%; height: 100vh; height: 100svh; overflow: hidden; background: #0b1c2a; }
.scene-backdrop { z-index: 0; }
.scene-vignette { position: absolute; z-index: 1; inset: 0; pointer-events: none; background: linear-gradient(180deg, #07132114 0%, transparent 26%, transparent 72%, #0713212c 100%), radial-gradient(ellipse at center, transparent 48%, #06101a2a 100%); }
.conflict-stack { position: fixed; z-index: 9; top: max(5.25rem, calc(env(safe-area-inset-top) + 4.25rem)); left: 50%; display: grid; gap: .75rem; max-height: min(70vh, 44rem); overflow: auto; transform: translateX(-50%); }
.event-action-notice { position: fixed; z-index: 14; left: 50%; bottom: max(5.25rem, calc(env(safe-area-inset-bottom) + 4.25rem)); display: flex; align-items: center; gap: .75rem; max-width: min(30rem, calc(100vw - 2rem)); padding: .65rem .8rem .65rem 1rem; border: 1px solid #edf2e87d; border-radius: .9rem; background: #152c32ed; color: #f7f5e9; box-shadow: 0 10px 32px #07131c48; backdrop-filter: blur(14px); font-size: .88rem; line-height: 1.45; }
.event-action-notice button { flex: none; width: 1.8rem; height: 1.8rem; border: 0; border-radius: 50%; background: transparent; color: inherit; font: inherit; font-size: 1.2rem; cursor: pointer; }
.time-peek { position: fixed; z-index: 8; left: var(--time-peek-x, 50%); top: var(--time-peek-y, 50%); padding: .36rem .68rem .4rem; border: 0; border-radius: .7rem; background: rgba(18, 32, 36, .74); color: #fbf8ee; box-shadow: 0 2px 8px rgba(4, 15, 19, .2); pointer-events: none; text-align: center; font-size: clamp(1.25rem, 3.5vw, 1.5rem); font-weight: 600; font-variant-numeric: tabular-nums; letter-spacing: .01em; line-height: 1.2; opacity: 0; visibility: hidden; transform: translate(-50%, -100%) scale(.98); transition: opacity .18s ease, transform .22s cubic-bezier(.2,.7,.2,1), visibility 0s linear .22s; }
.time-peek[data-placement="below"] { transform: translate(-50%, 0) scale(.98); }
.time-peek.is-visible { opacity: 1; visibility: visible; transform: translate(-50%, -100%) scale(1); transition: opacity .18s ease, transform .22s cubic-bezier(.2,.7,.2,1); }
.time-peek.is-visible[data-placement="below"] { transform: translate(-50%, 0) scale(1); }
.assistant-entry { position: absolute; z-index: 12; right: max(1.5rem, env(safe-area-inset-right)); bottom: max(1.5rem, env(safe-area-inset-bottom)); display: inline-flex; align-items: center; gap: .65rem; min-height: 3rem; padding: .72rem 1.05rem .72rem .8rem; border: 1px solid #edf6f05c; border-radius: 999px; background: #142a2f63; color: #f7f7e9; box-shadow: 0 9px 32px #07111d2c, inset 0 1px #ffffff25; backdrop-filter: blur(16px) saturate(1.15); -webkit-backdrop-filter: blur(16px) saturate(1.15); font: inherit; font-size: .875rem; letter-spacing: .015em; cursor: pointer; touch-action: manipulation; transition: background-color .18s ease, transform .12s ease-out, border-color .2s ease; }
.assistant-entry svg { width: 1.25rem; height: 1.25rem; }
.assistant-entry:hover { background: #18343a85; border-color: #f7f5df95; }
.assistant-entry:active { transform: scale(.98); }
.assistant-entry:focus-visible, .connection-error button:focus-visible { outline: 3px solid #fff3bd; outline-offset: 3px; }
.connection-error { position: absolute; z-index: 12; left: max(1.5rem, env(safe-area-inset-left)); bottom: max(1.5rem, env(safe-area-inset-bottom)); display: flex; gap: .75rem; align-items: center; max-width: calc(100vw - 11rem); padding: .7rem .9rem; border: 1px solid #eff4e846; border-radius: 1rem; background: #122a35a8; color: #f7f5e9; box-shadow: 0 10px 35px #07111d35; backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px); font-size: .875rem; }
.connection-error button { min-height: 2.75rem; padding: .4rem .8rem; border: 1px solid #eaf4e65c; border-radius: .7rem; background: #eaf4e61a; color: inherit; font: inherit; cursor: pointer; }
@media (max-width: 40rem) { .assistant-entry { right: max(1rem, env(safe-area-inset-right)); bottom: max(1rem, env(safe-area-inset-bottom)); } .connection-error { left: max(1rem, env(safe-area-inset-left)); bottom: max(1rem, env(safe-area-inset-bottom)); max-width: calc(100vw - 9rem); padding: .6rem; font-size: .8rem; } }
@media (prefers-reduced-motion: reduce) { .time-peek, .time-peek.is-visible { transition: opacity .01ms; transform: translate(-50%, -100%); } .time-peek[data-placement="below"], .time-peek.is-visible[data-placement="below"] { transform: translate(-50%, 0); } .assistant-entry { transition: background-color .08s ease; } .assistant-entry:active { transform: none; } }
</style>
