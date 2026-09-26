<script setup lang="ts">
import { onMounted, onUnmounted, ref, shallowRef } from 'vue'
import NatureScene from './scene/NatureScene.vue'
import { RealClock } from './platform/clocks.ts'
import { SceneEnvironmentSession } from './scene/session.ts'
import AssistantPanel from './assistant/AssistantPanel.vue'
import { assistantSession } from './assistant/sessionStore.ts'

const connection = ref<'checking' | 'connected' | 'failed'>('checking')
const realClock = new RealClock()
const environment = new SceneEnvironmentSession(realClock)
const frame = shallowRef(environment.frame)
let refreshTimer = 0

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

function refreshEnvironment() {
  frame.value = environment.refresh()
}

onMounted(() => {
  void checkConnection()
  refreshTimer = window.setInterval(refreshEnvironment, 30_000)
})

onUnmounted(() => window.clearInterval(refreshTimer))
</script>

<template>
  <main class="app-shell" aria-label="Kairos 自然场景">
    <NatureScene class="scene-backdrop" :frame="frame" />
    <div class="scene-vignette" aria-hidden="true"></div>
    <div v-if="connection === 'failed'" class="connection-error" role="status">
      <span>助手暂时离线</span>
      <button type="button" aria-label="重试连接助手服务" @click="checkConnection">重试</button>
    </div>
    <button
      class="assistant-entry"
      type="button"
      :aria-expanded="assistantSession.state.open"
      aria-label="打开 Kairos 助手"
      @click="assistantSession.open()"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none">
        <path d="M5 18.5 6.2 15A7.5 7.5 0 1 1 9 18.1L5 18.5Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" />
        <path d="M8.8 11.8h.1m3.05 0h.1m3.05 0h.1" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
      </svg>
      <span>问 Kairos</span>
    </button>
    <AssistantPanel />
  </main>
</template>

<style>
* { box-sizing: border-box; }
html, body, #app { width: 100%; height: 100%; margin: 0; }
body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; }
.app-shell { position: relative; isolation: isolate; width: 100%; height: 100vh; height: 100svh; min-height: 30rem; overflow: hidden; background: #0b1c2a; }
.scene-backdrop { z-index: 0; }
.scene-vignette { position: absolute; z-index: 1; inset: 0; pointer-events: none; background: linear-gradient(180deg, #07132114 0%, transparent 26%, transparent 72%, #0713212c 100%), radial-gradient(ellipse at center, transparent 48%, #06101a2a 100%); }
.assistant-entry { position: absolute; z-index: 12; right: max(1.5rem, env(safe-area-inset-right)); bottom: max(1.5rem, env(safe-area-inset-bottom)); display: inline-flex; align-items: center; gap: .65rem; min-height: 3rem; padding: .72rem 1.05rem .72rem .8rem; border: 1px solid #edf6f05c; border-radius: 999px; background: #142a2f63; color: #f7f7e9; box-shadow: 0 9px 32px #07111d2c, inset 0 1px #ffffff25; backdrop-filter: blur(16px) saturate(1.15); -webkit-backdrop-filter: blur(16px) saturate(1.15); font: inherit; font-size: .875rem; letter-spacing: .015em; cursor: pointer; touch-action: manipulation; transition: background-color .18s ease, transform .12s ease-out, border-color .2s ease; }
.assistant-entry svg { width: 1.25rem; height: 1.25rem; }
.assistant-entry:hover { background: #18343a85; border-color: #f7f5df95; }
.assistant-entry:active { transform: scale(.98); }
.assistant-entry:focus-visible, .connection-error button:focus-visible { outline: 3px solid #fff3bd; outline-offset: 3px; }
.connection-error { position: absolute; z-index: 12; left: max(1.5rem, env(safe-area-inset-left)); bottom: max(1.5rem, env(safe-area-inset-bottom)); display: flex; gap: .75rem; align-items: center; max-width: calc(100vw - 11rem); padding: .7rem .9rem; border: 1px solid #eff4e846; border-radius: 1rem; background: #122a35a8; color: #f7f5e9; box-shadow: 0 10px 35px #07111d35; backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px); font-size: .875rem; }
.connection-error button { min-height: 2.75rem; padding: .4rem .8rem; border: 1px solid #eaf4e65c; border-radius: .7rem; background: #eaf4e61a; color: inherit; font: inherit; cursor: pointer; }
@media (max-width: 40rem) { .assistant-entry { right: max(1rem, env(safe-area-inset-right)); bottom: max(1rem, env(safe-area-inset-bottom)); } .connection-error { left: max(1rem, env(safe-area-inset-left)); bottom: max(1rem, env(safe-area-inset-bottom)); max-width: calc(100vw - 9rem); padding: .6rem; font-size: .8rem; } }
@media (prefers-reduced-motion: reduce) { .assistant-entry { transition: background-color .08s ease; } .assistant-entry:active { transform: none; } }
</style>
