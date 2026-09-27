<script setup lang="ts">
import type { components } from '../../../../contracts/backend-api.d.ts'

type FlexibleTask = components['schemas']['FlexibleTask']
const props = defineProps<{ task: FlexibleTask; cueExpiresAt: number | null; busy: boolean; error: string }>()
const emit = defineEmits<{ accept: [taskId: string, version: number]; pause: [taskId: string, version: number]; complete: [taskId: string, version: number]; close: [] }>()
</script>

<template>
  <section class="task-detail" role="dialog" aria-modal="true" :aria-label="props.task.title">
    <button class="close" type="button" aria-label="关闭任务详情" @click="emit('close')">×</button>
    <p class="eyebrow">{{ props.task.lifecycle_status === 'active' ? '正在进行' : '留给你的一件事' }}</p>
    <h2>{{ props.task.title }}</h2>
    <p v-if="props.task.deadline">截止 {{ new Date(props.task.deadline).toLocaleString() }}</p>
    <p v-if="props.error" class="error" role="alert">{{ props.error }}</p>
    <div class="actions">
      <template v-if="props.task.lifecycle_status === 'planned'">
        <button class="primary" type="button" :disabled="props.busy" @click="emit('accept', props.task.task_id, props.task.version)">接受，放在河边</button>
      </template>
      <template v-else-if="props.task.lifecycle_status === 'active'">
        <button type="button" :disabled="props.busy" @click="emit('pause', props.task.task_id, props.task.version)">暂停</button>
        <button class="primary" type="button" :disabled="props.busy" @click="emit('complete', props.task.task_id, props.task.version)">完成</button>
      </template>
    </div>
  </section>
</template>

<style scoped>
.task-detail { position: fixed; z-index: 20; left: 50%; top: 50%; width: min(25rem, calc(100vw - 2rem)); padding: 1.5rem; border: 1px solid #edf4e680; border-radius: 1.4rem; background: #10282beF; color: #f7f5e9; box-shadow: 0 24px 80px #04101688, inset 0 1px #ffffff20; backdrop-filter: blur(22px); transform: translate(-50%, -50%); }
.close { position: absolute; top: .65rem; right: .7rem; width: 2.5rem; height: 2.5rem; border: 0; border-radius: 50%; background: #ffffff12; color: inherit; font: inherit; font-size: 1.4rem; cursor: pointer; }
.eyebrow { margin: 0 2.5rem .6rem 0; color: #e9d88c; font-size: .78rem; letter-spacing: .08em; }
h2 { margin: 0; font-size: 1.35rem; line-height: 1.35; font-weight: 600; }
.actions { display: flex; gap: .6rem; margin-top: 1.4rem; }
.actions button { min-height: 2.75rem; padding: .65rem .9rem; border: 1px solid #edf4e65c; border-radius: .85rem; background: #ffffff10; color: inherit; font: inherit; cursor: pointer; }
.actions .primary { border-color: #f2da8c88; background: #d1b55f2b; }
.actions button:disabled { opacity: .55; cursor: wait; }
.error { color: #ffc2b8; font-size: .88rem; }
@media (prefers-reduced-motion: reduce) { .task-detail { scroll-behavior: auto; } }
</style>
