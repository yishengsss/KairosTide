<script setup lang="ts">
import { onMounted, ref } from 'vue'

const connection = ref<'checking' | 'connected' | 'failed'>('checking')

async function checkConnection() {
  connection.value = 'checking'
  try {
    const response = await fetch('/api/v1/health', { cache: 'no-store' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const body: unknown = await response.json()
    if (typeof body !== 'object' || body === null || !('status' in body) || body.status !== 'ok') throw new Error('Invalid health response')
    connection.value = 'connected'
  } catch {
    connection.value = 'failed'
  }
}

onMounted(checkConnection)
</script>

<template>
  <main class="scene" aria-label="自然场景">
    <div class="horizon" aria-hidden="true"></div>
    <div v-if="connection === 'failed'" class="connection-error" role="alert">
      <span>连接服务失败，请稍后重试。</span>
      <button type="button" @click="checkConnection">重试</button>
    </div>
  </main>
</template>

<style>
html, body, #app { margin: 0; min-height: 100%; }
body { font-family: system-ui, -apple-system, sans-serif; }
.scene { min-height: 100vh; position: relative; overflow: hidden; background: linear-gradient(#87a7b6 0%, #d2c6ad 56%, #678894 57%, #243e4e 100%); }
.horizon { position: absolute; width: 140%; height: 32%; left: -20%; bottom: 31%; background: #455e60; clip-path: polygon(0 100%, 0 70%, 18% 28%, 33% 73%, 52% 18%, 74% 77%, 90% 44%, 100% 69%, 100% 100%); opacity: .82; }
.connection-error { position: absolute; left: 50%; bottom: 2rem; transform: translateX(-50%); display: flex; gap: .8rem; align-items: center; max-width: calc(100vw - 2rem); padding: .8rem 1rem; border-radius: 1rem; background: #fffdf4; color: #27343b; box-shadow: 0 12px 30px #10202c33; }
button { border: 1px solid #52636a; border-radius: .6rem; background: transparent; color: inherit; padding: .35rem .7rem; cursor: pointer; }
button:focus-visible { outline: 3px solid #284f72; outline-offset: 2px; }
</style>
