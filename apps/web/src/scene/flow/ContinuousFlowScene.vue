<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import type { EnvironmentFrame } from '../environment.ts'
import { mountFlow } from './mount.ts'
import { WaterTapController } from './waterInteraction.ts'

const props = withDefaults(defineProps<{ frame: EnvironmentFrame; mode?: 'free' | 'work' }>(), { mode: 'free' })
const emit = defineEmits<{ waterlineAt: [sample: (x: number) => number] }>()
const canvas = ref<HTMLCanvasElement | null>(null)
const root = ref<HTMLElement | null>(null)
const ripples = ref<{ id: number; x: number; y: number }[]>([])
const tapController = new WaterTapController()
let renderer: ReturnType<typeof mountFlow> | undefined
let nextRippleId = 1

function isInteractiveTarget(target: EventTarget | null): boolean {
  return target instanceof Element && !!target.closest('button, a, input, textarea, select, [contenteditable="true"], [data-time-peek-ignore], .assistant-panel, .reminder-state')
}

function pointerDown(event: PointerEvent) {
  if (!event.isPrimary || event.button !== 0) return
  const scene = root.value
  const surface = scene?.parentElement
  const bounds = scene?.getBoundingClientRect()
  const inWater = !!bounds && event.clientY >= bounds.top + bounds.height * 0.78
    && event.clientY <= bounds.bottom && event.clientX >= bounds.left && event.clientX <= bounds.right
  tapController.pointerDown(event.pointerId, event.clientX, event.clientY, event.timeStamp,
    !!surface && event.target instanceof Node && surface.contains(event.target) && inWater && !isInteractiveTarget(event.target))
}

function pointerMove(event: PointerEvent) {
  tapController.pointerMove(event.pointerId, event.clientX, event.clientY)
}

function pointerUp(event: PointerEvent) {
  const point = tapController.pointerUp(event.pointerId, event.clientX, event.clientY, event.timeStamp)
  const scene = root.value
  const bounds = scene?.getBoundingClientRect()
  const surface = scene?.parentElement
  if (!point || !bounds || !surface || !(event.target instanceof Node) || !surface.contains(event.target)
    || isInteractiveTarget(event.target) || point.x < bounds.left || point.x > bounds.right
    || point.y < bounds.top + bounds.height * 0.78 || point.y > bounds.bottom) return
  const ripple = { id: nextRippleId++, x: point.x - bounds.left, y: point.y - bounds.top }
  ripples.value = [...ripples.value.slice(-3), ripple]
}

function removeRipple(id: number) { ripples.value = ripples.value.filter(ripple => ripple.id !== id) }
function cancelPress() { tapController.cancel() }

onMounted(() => {
  if (canvas.value) renderer = mountFlow(canvas.value, () => props.frame, (sample) => emit('waterlineAt', sample))
  window.addEventListener('pointerdown', pointerDown)
  window.addEventListener('pointermove', pointerMove)
  window.addEventListener('pointerup', pointerUp)
  window.addEventListener('pointercancel', cancelPress)
  window.addEventListener('blur', cancelPress)
  document.addEventListener('visibilitychange', cancelPress)
})
watch(() => props.frame, () => renderer?.refresh())
onUnmounted(() => {
  renderer?.destroy()
  tapController.cancel()
  window.removeEventListener('pointerdown', pointerDown)
  window.removeEventListener('pointermove', pointerMove)
  window.removeEventListener('pointerup', pointerUp)
  window.removeEventListener('pointercancel', cancelPress)
  window.removeEventListener('blur', cancelPress)
  document.removeEventListener('visibilitychange', cancelPress)
})
</script>

<template>
  <div ref="root" class="continuous-flow" :class="{ 'is-work': props.mode === 'work' }" aria-hidden="true">
    <canvas ref="canvas" class="flow-canvas"></canvas>
    <span v-for="ripple in ripples" :key="ripple.id" class="water-tap-ripple"
      :style="{ left: `${ripple.x}px`, top: `${ripple.y}px` }" @animationend="removeRipple(ripple.id)"></span>
  </div>
</template>

<style scoped>
.continuous-flow { position: absolute; inset: 0; overflow: hidden; pointer-events: none; background: #080c1e; filter: saturate(1) contrast(1); transition: filter 1.2s ease; }
.flow-canvas { position: absolute; inset: 0; display: block; width: 100%; height: 100%; }
.continuous-flow.is-work { filter: saturate(1.06) contrast(1.035); }
.water-tap-ripple { position: absolute; width: 4.75rem; height: 1.75rem; border: 1px solid #e0e8db8c; border-radius: 50%; opacity: 0; pointer-events: none; animation: water-tap-ripple 620ms cubic-bezier(.2,.7,.2,1) both; }
@keyframes water-tap-ripple {
  0% { opacity: .58; transform: translate(-50%, -50%) scale(.24); }
  100% { opacity: 0; transform: translate(-50%, -50%) scale(1.45); }
}
@keyframes water-tap-fade {
  0% { opacity: .42; transform: translate(-50%, -50%); }
  100% { opacity: 0; transform: translate(-50%, -50%); }
}
@media (prefers-reduced-motion: reduce) { .continuous-flow { transition: none; } }
@media (prefers-reduced-motion: reduce) { .water-tap-ripple { animation-name: water-tap-fade; animation-duration: 180ms; } }
</style>
