<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import ActionButton from '../ui/ActionButton.vue'

const props = defineProps<{ value: string; pending: boolean; image: File | null; imageError: string }>()
const emit = defineEmits<{ 'update:value': [value: string]; 'update:image': [image: File | null]; submit: [] }>()
const input = ref<HTMLTextAreaElement | null>(null)
const imageInput = ref<HTMLInputElement | null>(null)
const previewUrl = ref('')
const fileError = ref('')
watch(() => props.image, (image) => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = image ? URL.createObjectURL(image) : ''
})
onBeforeUnmount(() => { if (previewUrl.value) URL.revokeObjectURL(previewUrl.value) })

function onInput(event: Event) {
  emit('update:value', (event.target as HTMLTextAreaElement).value)
}

function onEnter(event: KeyboardEvent) {
  if (event.isComposing || event.shiftKey) return
  event.preventDefault()
  if ((props.value.trim() || props.image) && !props.pending) emit('submit')
}

function onFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const allowed = ['image/jpeg', 'image/png', 'image/webp']
  if (!allowed.includes(file.type) || file.size > 10 * 1024 * 1024) {
    fileError.value = '请选择 JPEG、PNG 或 WebP 图片，且文件不超过 10 MiB。'
    return
  }
  fileError.value = ''
  emit('update:image', file)
}

defineExpose({ focusInput: () => input.value?.focus() })
</script>

<template>
  <form class="composer" @submit.prevent="emit('submit')">
    <label for="kairos-assistant-input">给 Kairos 留言</label>
    <div v-if="image" class="attachment" aria-label="待发送图片">
      <img :src="previewUrl" alt="待分析图片预览" />
      <span>{{ image.name }}</span>
      <button type="button" class="remove-image" aria-label="移除图片" @click="emit('update:image', null)">移除</button>
    </div>
    <div class="composer-row">
      <textarea id="kairos-assistant-input" ref="input" :value="value" rows="2" placeholder="说说你想安排或询问的事" @input="onInput" @keydown.enter="onEnter" />
      <input ref="imageInput" class="file-input" type="file" accept="image/jpeg,image/png,image/webp" aria-label="选择图片" @change="onFile" />
      <ActionButton type="button" quiet :disabled="pending" @click="imageInput?.click()">图片</ActionButton>
      <ActionButton type="submit" :disabled="(!value.trim() && !image) || pending">{{ pending ? '发送中…' : '发送' }}</ActionButton>
    </div>
    <p class="composer-hint">按 Enter 发送，Shift + Enter 换行</p>
    <p v-if="fileError || imageError" class="composer-error" role="alert">{{ fileError || imageError }}</p>
  </form>
</template>

<style scoped>
.composer { padding: .85rem 1rem max(.85rem, env(safe-area-inset-bottom)); background: rgba(244, 248, 236, .76); border-top: 1px solid rgba(38, 67, 49, .1); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); }
.composer label { display: block; margin-bottom: .45rem; font-size: .875rem; font-weight: 600; }
.composer-row { display: flex; align-items: end; gap: .5rem; }
.composer textarea { flex: 1; min-width: 0; min-height: 2.75rem; max-height: 30vh; padding: .65rem .75rem; resize: vertical; border: 1px solid #9bafa0; border-radius: .75rem; background: #fff; color: #172920; font: inherit; line-height: 1.5; }
.composer textarea:focus-visible { outline: 2px solid #25583b; outline-offset: 2px; }
.composer-hint { margin: .35rem 0 0; color: #526358; font-size: .75rem; }
.attachment { display: flex; align-items: center; gap: .6rem; margin: 0 0 .6rem; padding: .45rem; border-radius: .7rem; background: rgba(255,255,255,.72); }
.attachment img { width: 3rem; height: 3rem; object-fit: cover; border-radius: .4rem; }
.attachment span { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .82rem; }
.remove-image { border: 0; background: transparent; color: #315341; font: inherit; text-decoration: underline; cursor: pointer; }
.file-input { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; }
.composer-error { margin: .35rem 0 0; color: #823e29; font-size: .8rem; }
</style>
