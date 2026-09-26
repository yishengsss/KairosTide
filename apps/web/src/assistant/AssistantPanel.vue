<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import type { createAssistantSession } from './sessionStore.ts'
import { assistantSession } from './sessionStore.ts'
import Surface from '../ui/Surface.vue'
import ActionButton from '../ui/ActionButton.vue'
import Conversation from './Conversation.vue'
import Composer from './Composer.vue'
import DraftReview from './DraftReview.vue'

const props = withDefaults(defineProps<{ session?: ReturnType<typeof createAssistantSession> }>(), {
  session: () => assistantSession,
})
const emit = defineEmits<{ closed: []; 'return-to-scene': [] }>()
const composer = ref<{ focusInput: () => void } | null>(null)
let returnFocus: HTMLElement | null = null

watch(() => props.session.state.open, async (open) => {
  if (open) {
    returnFocus = typeof document === 'undefined' ? null : document.activeElement as HTMLElement | null
    await nextTick()
    composer.value?.focusInput()
  } else if (returnFocus) {
    await nextTick()
    returnFocus.focus()
    returnFocus = null
  }
}, { flush: 'post' })

onMounted(() => {
  if (props.session.state.open) composer.value?.focusInput()
})

function closePanel() {
  props.session.close()
  emit('closed')
}

function returnToScene() {
  closePanel()
  emit('return-to-scene')
}
</script>

<template>
  <aside :class="['assistant-panel', { 'is-open': session.state.open }]" :inert="!session.state.open" :aria-hidden="!session.state.open" @keydown.esc.stop.prevent="closePanel">
    <Surface class="assistant-surface">
      <template v-if="session.state.open">
        <header class="assistant-header">
          <h1 id="kairos-assistant-title">Kairos 助手</h1>
          <ActionButton quiet aria-label="关闭助手" @click="closePanel">关闭</ActionButton>
        </header>
        <div v-if="session.state.activeNotice" class="assistant-notice" role="status">
          <span>{{ session.state.activeNotice }}</span>
          <ActionButton quiet @click="returnToScene">回到场景</ActionButton>
        </div>
        <div class="assistant-scroll" role="region" aria-labelledby="kairos-assistant-title">
          <Conversation :messages="session.state.messages" />
          <DraftReview v-if="session.state.draft" :draft="session.state.draft" :pending="session.state.pending === 'confirming'" @confirm="session.confirmDraft" />
        </div>
        <p v-if="session.state.error" class="assistant-error" role="alert">{{ session.state.error }}</p>
        <Composer ref="composer" :value="session.state.input" :pending="session.state.pending === 'sending'" @update:value="session.setInput" @submit="session.sendMessage" />
      </template>
    </Surface>
  </aside>
</template>

<style scoped>
.assistant-panel {
  position: fixed; z-index: 20; top: 1rem; right: 1rem; bottom: 1rem;
  width: min(26rem, calc(100vw - 2rem));
  opacity: 0; visibility: hidden; pointer-events: none; transform: translateX(1.5rem);
  transition: transform .38s cubic-bezier(.2,.8,.2,1), opacity .3s ease, visibility 0s linear .38s;
}
.assistant-panel.is-open { opacity: 1; visibility: visible; pointer-events: auto; transform: translateX(0); transition-delay: 0s; }
.assistant-surface { height: 100%; display: flex; flex-direction: column; border-radius: 1.5rem; overflow: hidden; }
.assistant-header { display: flex; justify-content: space-between; align-items: center; gap: .75rem; padding: 1rem; flex: none; }
.assistant-header h1 { margin: 0; font-size: 1.18rem; line-height: 1.3; letter-spacing: -.01em; }
.assistant-notice { display: flex; align-items: center; justify-content: space-between; gap: .5rem; margin: 0 1rem .75rem; padding: .5rem .65rem; border-radius: .75rem; background: #e8efe7; color: #233d2d; font-size: .875rem; }
.assistant-notice span { min-width: 0; overflow-wrap: anywhere; }
.assistant-scroll { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; display: grid; align-content: start; gap: 1rem; padding: 0 1rem 1rem; }
.assistant-error { flex: none; margin: 0 1rem .25rem; padding: .65rem .75rem; border-radius: .6rem; background: #fff0e9; color: #823e29; }
@media (max-width: 59.999rem) {
  .assistant-panel { top: auto; right: 0; bottom: 0; width: 100%; height: min(88dvh, 46rem); transform: translateY(1.5rem); }
  .assistant-panel.is-open { transform: translateY(0); }
  .assistant-surface { border-radius: 1.5rem 1.5rem 0 0; }
}
@media (max-height: 34rem) and (max-width: 59.999rem) { .assistant-panel { height: 100dvh; } }
@media (prefers-reduced-motion: reduce) {
  .assistant-panel { transform: none; transition: opacity .18s ease, visibility 0s linear .18s; }
  .assistant-panel.is-open { transform: none; }
}
</style>
