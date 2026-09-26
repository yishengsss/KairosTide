<script setup lang="ts">
import { ref } from 'vue'
import ActionButton from '../ui/ActionButton.vue'

const props = defineProps<{ value: string; pending: boolean }>()
const emit = defineEmits<{ 'update:value': [value: string]; submit: [] }>()
const input = ref<HTMLTextAreaElement | null>(null)

function onInput(event: Event) {
  emit('update:value', (event.target as HTMLTextAreaElement).value)
}

function onEnter(event: KeyboardEvent) {
  if (event.isComposing || event.shiftKey) return
  event.preventDefault()
  if (props.value.trim() && !props.pending) emit('submit')
}

defineExpose({ focusInput: () => input.value?.focus() })
</script>

<template>
  <form class="composer" @submit.prevent="emit('submit')">
    <label for="kairos-assistant-input">给 Kairos 留言</label>
    <div class="composer-row">
      <textarea id="kairos-assistant-input" ref="input" :value="value" rows="2" placeholder="说说你想安排或询问的事" @input="onInput" @keydown.enter="onEnter" />
      <ActionButton type="submit" :disabled="!value.trim() || pending">{{ pending ? '发送中…' : '发送' }}</ActionButton>
    </div>
    <p class="composer-hint">按 Enter 发送，Shift + Enter 换行</p>
  </form>
</template>

<style scoped>
.composer { padding: .85rem 1rem max(.85rem, env(safe-area-inset-bottom)); background: rgba(244, 248, 236, .76); border-top: 1px solid rgba(38, 67, 49, .1); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); }
.composer label { display: block; margin-bottom: .45rem; font-size: .875rem; font-weight: 600; }
.composer-row { display: flex; align-items: end; gap: .5rem; }
.composer textarea { flex: 1; min-width: 0; min-height: 2.75rem; max-height: 30vh; padding: .65rem .75rem; resize: vertical; border: 1px solid #9bafa0; border-radius: .75rem; background: #fff; color: #172920; font: inherit; line-height: 1.5; }
.composer textarea:focus-visible { outline: 2px solid #25583b; outline-offset: 2px; }
.composer-hint { margin: .35rem 0 0; color: #526358; font-size: .75rem; }
</style>
