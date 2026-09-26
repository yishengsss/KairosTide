<script setup lang="ts">
import type { AssistantMessage } from './sessionStore.ts'

defineProps<{ messages: AssistantMessage[] }>()
</script>

<template>
  <section class="conversation" aria-label="对话记录">
    <p v-if="!messages.length" class="conversation-empty">可以告诉我你的安排，或主动问我需要了解的事。</p>
    <ol v-else class="conversation-list">
      <li v-for="(message, index) in messages" :key="index" :class="['conversation-message', message.role]">
        <span class="conversation-role">{{ message.role === 'user' ? '你' : 'Kairos' }}</span>
        <p>{{ message.content }}</p>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.conversation { min-width: 0; }
.conversation-empty { margin: 1rem 0; color: #4b6253; line-height: 1.6; }
.conversation-list { list-style: none; margin: 0; padding: 0; display: grid; gap: .9rem; }
.conversation-message { max-width: 96%; min-width: 0; padding: .75rem .9rem; border-radius: 1rem; background: #eaf0e8; overflow-wrap: anywhere; }
.conversation-message.user { justify-self: end; background: #dce9dc; }
.conversation-role { display: block; margin-bottom: .25rem; color: #315341; font-size: .8rem; font-weight: 650; }
.conversation-message p { margin: 0; line-height: 1.55; white-space: pre-wrap; }
</style>
