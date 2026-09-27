import { computed, createApp, defineComponent, h, onBeforeUnmount, onMounted, ref } from 'vue'
import NatureScene from '../scene/flow/ContinuousFlowScene.vue'
import { computeEnvironment } from '../scene/environment.ts'
import ActiveEventLayer from './ActiveEventLayer.vue'
import SceneEventSignals from './SceneEventSignals.vue'
import { findMarkerPosition, screenYForMarker, type SceneMarker, type SceneSignal } from './markerLayout.ts'
import type { components } from '../../../../contracts/backend-api.d.ts'

type Occurrence = components['schemas']['Occurrence']
type TaskStatus = 'planned' | 'active' | 'completed'
type PreviewTask = { id: string; title: string; status: TaskStatus; visible: boolean; expiresAt: number | null }

// The development preview uses only in-memory fixtures and imports no API client.
const occurrence: Occurrence = {
  occurrence_id: 'preview-software-engineering', event_id: 'preview-event', title: '软件工程课程',
  location: '教学楼 · 204', start_at: '2026-09-27T14:00:00+08:00', end_at: '2026-09-27T15:40:00+08:00',
  disposition: 'scheduled', temporal_phase: 'active', version: 1,
}
const frame = computeEnvironment({ instant: new Date(), location: { latitude: 34.3416, longitude: 108.9398 }, weather: null })
const mount = document.querySelector<HTMLElement>('#preview-scene')!
const diagnostics = document.querySelector<HTMLElement>('.preview-diagnostics')!
const taskNames = ['完成操作系统实验', '整理本周阅读笔记', '修订项目功能', '练习一组高数题', '复习英语单词', '归档研究资料']
const tasks = ref<PreviewTask[]>([])
const markers = ref<SceneMarker[]>([])
const signals = ref<SceneSignal[]>([])
const selectedTaskId = ref<string | null>(null)
const selectedTask = computed(() => tasks.value.find(task => task.id === selectedTaskId.value) ?? null)
const rigidExists = ref(true)
const rigidCardOpen = ref(false)
let waterlineAt: ((x: number) => number) | null = null
let needsPlacement = true
let fixtureSeed = 0x25af27
let nextTaskNumber = 1
let clockOffsetMs = 0
let timer = 0

function random() {
  fixtureSeed = (Math.imul(fixtureSeed, 1664525) + 1013904223) >>> 0
  return fixtureSeed / 0x100000000
}
function now() { return Date.now() + clockOffsetMs }
function visibleIds() {
  return [...(rigidExists.value ? ['preview-rigid'] : []), ...tasks.value.filter(task => task.visible && task.status !== 'completed').map(task => task.id)]
}
function refreshSignals() {
  if (!waterlineAt) return
  const sample = waterlineAt
  signals.value = markers.value.filter(marker => !(marker.kind === 'rigid' && rigidCardOpen.value)).map(marker => {
    const task = tasks.value.find(item => item.id === marker.id)
    return { id: marker.id, kind: marker.kind,
      accessibleName: task ? `柔性任务：${task.title}，查看详情` : `固定事件：${occurrence.title}，查看事件`,
      x: marker.x, y: screenYForMarker(marker, sample), diameter: marker.diameter }
  })
  const deferred = visibleIds().filter(id => !markers.value.some(marker => marker.id === id)).length
  diagnostics.textContent = `已放置：红 ${markers.value.filter(marker => marker.kind === 'rigid').length} · 黄 ${markers.value.filter(marker => marker.kind === 'flexible').length}；空间不足待放置：${deferred}`
}
function placePending() {
  if (!waterlineAt || !needsPlacement) return
  const wanted = visibleIds()
  const wantedSet = new Set(wanted)
  const placed = markers.value.filter(marker => wantedSet.has(marker.id))
  const { width, height } = mount.getBoundingClientRect()
  for (const id of wanted) {
    if (placed.some(marker => marker.id === id)) continue
    const position = findMarkerPosition({ id, kind: id === 'preview-rigid' ? 'rigid' : 'flexible',
      width, height, diameter: 54, minGap: 14, waterlineAt, existing: placed, random })
    if (position) placed.push(position)
  }
  markers.value = placed
  // Deferred cues retry when a signal exits, a cue arrives, or the viewport changes.
  needsPlacement = false
  refreshSignals()
}
function reconcile() {
  const wanted = new Set(visibleIds())
  markers.value = markers.value.filter(marker => wanted.has(marker.id))
  needsPlacement = true
  placePending()
}
function addTemporary(title?: string) {
  const index = nextTaskNumber++
  tasks.value = [...tasks.value, { id: `preview-flex-${index}`, title: title ?? taskNames[(index - 1) % taskNames.length],
    status: 'planned', visible: true, expiresAt: now() + (5 + random() * 5) * 60_000 }]
  reconcile()
}
function resetFixtures() {
  fixtureSeed = 0x25af27
  nextTaskNumber = 1
  clockOffsetMs = 0
  rigidExists.value = true
  rigidCardOpen.value = false
  selectedTaskId.value = null
  markers.value = []
  tasks.value = []
  addTemporary('完成操作系统实验')
  addTemporary('整理本周阅读笔记')
  addTemporary('修订项目功能')
  tasks.value = [...tasks.value, { id: `preview-flex-${nextTaskNumber++}`, title: '复习英语单词',
    status: 'active', visible: true, expiresAt: null }]
  reconcile()
}
function expireTemporary() {
  let changed = false
  tasks.value = tasks.value.map(task => {
    if (task.status !== 'planned' || !task.visible || task.expiresAt === null || task.expiresAt > now()) return task
    changed = true
    return { ...task, visible: false }
  })
  // Deliberately keep an already-open detail panel when its ring expires.
  if (changed) reconcile()
}
function advanceToNextExpiry() {
  const next = tasks.value.reduce<number | null>((earliest, task) => task.status === 'planned' && task.visible && task.expiresAt !== null
    ? Math.min(earliest ?? task.expiresAt, task.expiresAt) : earliest, null)
  if (next === null) return
  clockOffsetMs += Math.max(0, next + 1 - now())
  expireTemporary()
}
function offerPausedAgain() {
  const paused = tasks.value.find(task => task.status === 'planned' && !task.visible)
  if (!paused) return
  tasks.value = tasks.value.map(task => task.id === paused.id
    ? { ...task, visible: true, expiresAt: now() + (5 + random() * 5) * 60_000 } : task)
  reconcile()
}
function changeSelectedTask(target: TaskStatus) {
  const current = selectedTask.value
  if (!current || current.status === 'completed') return
  if (target === 'active' && current.status !== 'planned') return
  if (target !== 'active' && current.status !== 'active') return
  tasks.value = tasks.value.map(task => task.id === current.id
    ? { ...task, status: target, visible: target === 'active', expiresAt: null } : task)
  selectedTaskId.value = null
  reconcile()
}
function selectSignal(id: string) {
  if (id === 'preview-rigid') { rigidCardOpen.value = true; refreshSignals(); return }
  if (tasks.value.some(task => task.id === id)) selectedTaskId.value = id
}
function updateWaterline(sample: (x: number) => number) {
  waterlineAt = sample
  placePending()
  refreshSignals()
}
function onResize() {
  markers.value = []
  needsPlacement = true
  placePending()
}

const preview = defineComponent({
  setup() {
    onMounted(() => { timer = window.setInterval(expireTemporary, 1_000); window.addEventListener('resize', onResize) })
    onBeforeUnmount(() => { window.clearInterval(timer); window.removeEventListener('resize', onResize) })
    return () => h('div', { class: 'preview-composition' }, [
      h(NatureScene, { frame, onWaterlineAt: updateWaterline }),
      h(SceneEventSignals, { signals: signals.value, onSelect: selectSignal }),
      h(ActiveEventLayer, { occurrence: rigidCardOpen.value && rigidExists.value ? occurrence : null,
        onAcknowledge: () => { rigidCardOpen.value = false; refreshSignals() },
        onException: () => { rigidExists.value = false; rigidCardOpen.value = false; reconcile() } }),
      selectedTask.value ? h('section', { class: 'preview-task-detail', 'aria-label': '柔性任务详情' }, [
        h('button', { class: 'preview-detail-close', type: 'button', 'aria-label': '关闭任务详情',
          onClick: () => { selectedTaskId.value = null } }, '×'),
        h('p', { class: 'preview-detail-kicker' }, '柔性任务'),
        h('h2', selectedTask.value.title),
        h('p', { class: 'preview-detail-copy' }, selectedTask.value.status === 'active'
          ? '已接受。可以暂停或完成。' : selectedTask.value.visible ? '是否现在接受，由你决定。' : '圆圈已淡去，任务仍保留。'),
        h('div', { class: 'preview-detail-actions' }, selectedTask.value.status === 'active'
          ? [h('button', { type: 'button', onClick: () => changeSelectedTask('planned') }, '暂停'),
            h('button', { type: 'button', onClick: () => changeSelectedTask('completed') }, '完成')]
          : [h('button', { type: 'button', onClick: () => changeSelectedTask('active') }, '接受')]),
      ]) : null,
    ])
  },
})

createApp(preview).mount(mount)
document.querySelector<HTMLButtonElement>('[data-action="reset"]')?.addEventListener('click', resetFixtures)
document.querySelector<HTMLButtonElement>('[data-action="add"]')?.addEventListener('click', () => addTemporary())
document.querySelector<HTMLButtonElement>('[data-action="expire"]')?.addEventListener('click', advanceToNextExpiry)
document.querySelector<HTMLButtonElement>('[data-action="reoffer"]')?.addEventListener('click', offerPausedAgain)
document.querySelector<HTMLButtonElement>('[data-action="rigid-end"]')?.addEventListener('click', () => {
  rigidExists.value = false; rigidCardOpen.value = false; reconcile()
})
document.querySelector<HTMLButtonElement>('[data-action="rigid-restart"]')?.addEventListener('click', () => {
  rigidExists.value = true; reconcile()
})
resetFixtures()
