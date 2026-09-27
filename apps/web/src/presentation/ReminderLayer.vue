<script setup lang="ts">
import { computed } from 'vue'
import type { Reminder } from '../assistant/sessionStore.ts'
import ActionButton from '../ui/ActionButton.vue'
import { reminderUrgency } from './sceneMode.ts'

const props = defineProps<{ reminder: Reminder | null; assistantOpen: boolean; pending: boolean }>()
const emit = defineEmits<{ acknowledge: [] }>()
const urgency = computed(() => reminderUrgency(props.reminder?.minutes_until_start ?? 5))
</script>

<template>
  <Transition name="reminder-alert">
    <div v-if="reminder" class="reminder-state" :class="{ 'assistant-is-open': assistantOpen }" :style="{ '--urgency': urgency }">
      <div class="reminder-card" role="status" aria-live="polite">
        <div class="reminder-copy">
          <strong>{{ reminder.event_title }}</strong>
          <span v-if="reminder.location">{{ reminder.location }}</span>
          <span>即将开始</span>
        </div>
        <ActionButton quiet class="acknowledge" :disabled="pending" @click="emit('acknowledge')">知道了</ActionButton>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.reminder-alert-enter-active, .reminder-alert-leave-active { transition: opacity .28s ease; }
.reminder-alert-enter-from, .reminder-alert-leave-to { opacity: 0; }
.reminder-state { position: fixed; z-index: 10; inset: 0; pointer-events: none; --urgency: 0; }
.reminder-state::before { content: ''; position: absolute; inset: 0; border: 1px solid rgba(255, 100, 82, calc(.08 + var(--urgency) * .34)); box-shadow: inset 0 0 54px rgba(255, 72, 64, calc(.01 + var(--urgency) * .035)); transition: border-color 60s linear, box-shadow 60s linear; }
.reminder-state::after { content: ''; position: absolute; inset: 0; opacity: calc(var(--urgency) * .12); background: radial-gradient(ellipse at center, transparent 52%, rgba(255, 75, 65, .56) 100%); transition: opacity 60s linear; }
.reminder-card { position: absolute; top: max(1.25rem, env(safe-area-inset-top)); left: 50%; transform: translateX(-50%); display: flex; align-items: center; gap: 1rem; width: min(25rem, calc(100vw - 2rem)); padding: .85rem 1rem; border: 1px solid #eff5e5a1; border-radius: 1rem; color: #f7f4e7; background: #142d35e8; box-shadow: 0 12px 42px #07111d42; backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px); pointer-events: auto; }
.reminder-copy { display: grid; flex: 1; min-width: 0; gap: .15rem; }
.reminder-copy strong { font-size: .97rem; font-weight: 600; }
.reminder-copy span { font-size: .79rem; opacity: .83; }
.acknowledge { min-height: 2.75rem; white-space: nowrap; }
.assistant-is-open .reminder-card { top: max(1rem, env(safe-area-inset-top)); left: 1rem; transform: none; width: min(19rem, calc(100vw - 2rem)); }
.assistant-is-open::before, .assistant-is-open::after { display: none; }
@media (prefers-reduced-motion: reduce) {
  .reminder-alert-enter-active, .reminder-alert-leave-active { transition-duration: .08s; }
  .reminder-state::before, .reminder-state::after { transition-duration: .08s; }
}
</style>
