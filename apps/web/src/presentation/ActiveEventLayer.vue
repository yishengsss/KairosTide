<script setup lang="ts">
import type { components } from '../../../../contracts/backend-api.d.ts'

type Occurrence = components['schemas']['Occurrence']

const props = defineProps<{ occurrence: Occurrence | null; exceptionPending?: boolean }>()
const emit = defineEmits<{
  acknowledge: [occurrenceId: string]
  exception: [occurrenceId: string]
}>()
</script>

<template>
  <Transition name="active-event">
    <section v-if="props.occurrence" class="active-event" aria-live="polite" aria-label="正在进行的事件">
      <div class="event-vignette" aria-hidden="true"></div>
      <div class="event-content">
        <span class="anchor-mark" aria-hidden="true"></span>
        <div class="event-copy">
          <span class="event-kicker">正在进行</span>
          <h1>{{ props.occurrence.title }}</h1>
          <p v-if="props.occurrence.location">{{ props.occurrence.location }}</p>
        </div>
        <div class="event-actions" aria-label="事件操作">
          <button type="button" class="event-action event-action-primary" @click="emit('acknowledge', props.occurrence!.occurrence_id)">
            知道了
          </button>
          <button type="button" class="event-action" :disabled="props.exceptionPending" aria-label="记录本次请假"
            @click="emit('exception', props.occurrence!.occurrence_id)">
            {{ props.exceptionPending ? '正在记录…' : '例外' }}
          </button>
        </div>
      </div>
    </section>
  </Transition>
</template>

<style scoped>
.active-event {
  position: fixed;
  z-index: 9;
  inset: 0;
  display: grid;
  place-items: center;
  color: #f7f5e9;
  pointer-events: none;
}
.event-vignette { position: absolute; inset: 0; background: radial-gradient(ellipse at 50% 48%, rgb(179 211 227 / 5%) 0%, rgb(5 12 23 / 17%) 46%, rgb(3 8 16 / 31%) 100%); opacity: 1; transition: opacity .9s ease; }
.event-content { position: relative; z-index: 1; display: grid; justify-items: center; width: min(88vw, 42rem); padding: 1.5rem; text-align: center; transform: translateY(10px) scale(.985); transition: transform .9s cubic-bezier(.2, .75, .2, 1); pointer-events: auto; }
.anchor-mark { width: .55rem; height: .55rem; margin: 0 auto 1.35rem; border-radius: 50%; background: #eef6f2; box-shadow: 0 0 22px rgb(190 220 255 / 64%), 0 0 62px rgb(160 200 255 / 18%); }
.event-copy { min-width: 0; }
.event-kicker { color: #f1f5e8a6; font-size: .68rem; letter-spacing: .34em; }
h1 { margin: .8rem 0 0; font-size: clamp(2rem, 6vw, 4.6rem); font-weight: 260; letter-spacing: .055em; line-height: 1.18; overflow-wrap: anywhere; text-shadow: 0 2px 26px rgb(7 19 32 / 30%); }
p { margin: .9rem 0 0; color: #e2e8dcb8; font-size: clamp(.82rem, 2.5vw, 1rem); letter-spacing: .13em; overflow-wrap: anywhere; }
.event-actions { display: flex; justify-content: center; gap: .6rem; margin-top: 1.8rem; }
.event-action { min-height: 2.75rem; padding: .62rem 1.05rem; border: 1px solid rgb(236 244 239 / 20%); border-radius: 999px; background: rgb(12 25 35 / 20%); color: rgb(247 245 233 / 76%); font: inherit; font-size: .82rem; letter-spacing: .04em; cursor: pointer; backdrop-filter: blur(8px); transition: background-color .2s ease, border-color .2s ease, color .2s ease; }
.event-action-primary { border-color: rgb(236 244 239 / 33%); background: rgb(236 244 239 / 12%); color: #fbfaf1; }
.event-action:hover { background-color: rgb(237 242 232 / 16%); border-color: rgb(237 242 232 / 38%); color: #fff; }
.event-action:disabled { opacity: .65; cursor: wait; }
.event-action:focus-visible { outline: 3px solid #fff3bd; outline-offset: 3px; }
.active-event-enter-active, .active-event-leave-active { transition: opacity .72s ease; }
.active-event-enter-active .event-content, .active-event-leave-active .event-content { transition: transform .72s cubic-bezier(.2, .75, .2, 1); }
.active-event-enter-from, .active-event-leave-to { opacity: 0; }
.active-event-enter-from .event-content, .active-event-leave-to .event-content { transform: translateY(14px) scale(.985); }
@media (prefers-reduced-motion: reduce) {
  .event-vignette, .event-content, .event-action, .active-event-enter-active, .active-event-leave-active,
  .active-event-enter-active .event-content, .active-event-leave-active .event-content { transition-duration: .01ms; }
}
</style>
