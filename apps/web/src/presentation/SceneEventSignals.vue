<script setup lang="ts">
import type { SceneSignal } from './markerLayout.ts'

const props = defineProps<{ signals: SceneSignal[] }>()
const emit = defineEmits<{ select: [signalId: string] }>()
</script>

<template>
  <div class="scene-event-signals">
    <button v-for="signal in props.signals" :key="signal.id"
      class="signal-ring" :class="`signal-${signal.kind}`" type="button"
      :aria-label="signal.accessibleName"
      :style="{ left: `${signal.x}px`, top: `${signal.y}px`, width: `${signal.diameter}px`, height: `${signal.diameter}px` }"
      @click="emit('select', signal.id)">
      <svg viewBox="0 0 120 120" focusable="false" aria-hidden="true">
        <circle class="ring-halo" cx="60" cy="60" r="39" />
        <circle class="ring-line" cx="60" cy="60" r="34" />
        <circle class="ring-inner" cx="60" cy="60" r="29" />
      </svg>
    </button>
  </div>
</template>

<style scoped>
.scene-event-signals {
  position: absolute;
  z-index: 4;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}
.signal-ring {
  position: absolute;
  display: block;
  padding: 0;
  border: 0;
  appearance: none;
  background: transparent;
  transform: translate(-50%, -50%);
  pointer-events: auto;
  cursor: pointer;
  animation: signal-enter .35s ease-out both;
}
.signal-ring:focus-visible { outline: 2px solid #fff0bd; outline-offset: 4px; border-radius: 50%; }
.signal-ring svg { display: block; width: 100%; height: 100%; overflow: visible; }
.ring-halo { fill: none; stroke-width: 8; opacity: .1; }
.ring-line { fill: none; stroke-width: 1.7; }
.ring-inner { fill: none; stroke-width: .8; opacity: .28; }
.signal-rigid .ring-halo { stroke: #f05a4f; }
.signal-rigid .ring-line { stroke: #ff7461; }
.signal-rigid .ring-inner { stroke: #ffc6a5; }
.signal-flexible .ring-halo { stroke: #e5c766; }
.signal-flexible .ring-line { stroke: #f2d77e; }
.signal-flexible .ring-inner { stroke: #fff0b4; }
@keyframes signal-enter { from { opacity: 0; } to { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .signal-ring { animation: none; } }
</style>
