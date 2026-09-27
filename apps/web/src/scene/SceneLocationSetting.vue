<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SceneWeatherController, WeatherPlaceChoice } from './weatherController.ts'

const props = defineProps<{ controller: SceneWeatherController }>()
const open = ref(false)
const city = ref('')
const inputError = ref('')
const state = props.controller.state
const fetchedLabel = computed(() => {
  if (!state.fetchedAt) return null
  const instant = new Date(state.fetchedAt)
  return Number.isFinite(instant.getTime()) ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(instant) : null
})

async function applyCity() {
  const value = city.value.trim()
  if (!value) { inputError.value = '请输入城市名称'; return }
  inputError.value = ''
  try { await props.controller.setCity(value) }
  catch { inputError.value = '地点暂时无法设置，请重试。' }
}

async function choosePlace(choice: WeatherPlaceChoice) {
  inputError.value = ''
  try { await props.controller.selectChoice(choice) }
  catch { inputError.value = '地点选择已过期，请重新搜索。' }
}

function clearPlace() {
  props.controller.clear()
  city.value = ''
  inputError.value = ''
}

function placeLabel(choice: WeatherPlaceChoice): string {
  return [choice.name, choice.admin1, choice.country].filter(Boolean).join('，')
}
</script>

<template>
  <section class="scene-place" aria-label="场景地点设置">
    <button class="scene-place-trigger" type="button" :aria-expanded="open" aria-controls="scene-place-panel"
      @click="open = !open">
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 21s6.5-5.5 6.5-11a6.5 6.5 0 1 0-13 0c0 5.5 6.5 11 6.5 11Z" stroke="currentColor" stroke-width="1.5"/><circle cx="12" cy="10" r="2.2" stroke="currentColor" stroke-width="1.5"/></svg>
      <span>{{ state.status === 'available' && state.label ? state.label : '场景地点' }}</span>
    </button>
    <div v-if="open" id="scene-place-panel" class="scene-place-panel" @keydown.esc="open = false">
      <div class="panel-heading"><h2>场景地点</h2><button type="button" aria-label="关闭场景地点设置" @click="open = false">×</button></div>
      <p class="panel-intro">选择城市后，天气会融入风景。太阳仍跟随真实时间。</p>
      <form @submit.prevent="applyCity">
        <label for="scene-city">城市</label>
        <div class="city-row"><input id="scene-city" v-model="city" type="text" maxlength="120" autocomplete="address-level2" placeholder="例如 西安" :aria-invalid="!!inputError"><button type="submit">使用此城市</button></div>
      </form>
      <p v-if="inputError" class="scene-place-error" role="alert">{{ inputError }}</p>
      <p v-else-if="state.status === 'loading'" class="scene-place-status" role="status">正在获取天气…</p>
      <div v-else-if="state.status === 'ambiguous'" class="scene-place-status">
        <p>找到多个地点，请选择：</p>
        <div class="place-choices"><button v-for="choice in state.choices" :key="`${choice.name}-${choice.latitude}-${choice.longitude}`" type="button" @click="choosePlace(choice)">{{ placeLabel(choice) }}</button></div>
      </div>
      <p v-else-if="state.status === 'unavailable' || state.status === 'stale'" class="scene-place-status" role="status">天气暂不可用，风景保持中性。<button type="button" @click="controller.maybeRefresh(Number.POSITIVE_INFINITY)">重试</button></p>
      <p v-else-if="state.status === 'available'" class="scene-place-status" role="status">正在显示 {{ state.label }} 的当前天气。</p>
      <p v-if="state.source && state.status === 'available'" class="scene-place-source">来源：{{ state.attribution || state.source }}<span v-if="fetchedLabel"> · 更新于 {{ fetchedLabel }}</span></p>
      <button v-if="state.city" class="clear-place" type="button" @click="clearPlace">清除场景地点</button>
    </div>
  </section>
</template>

<style scoped>
.scene-place { position: absolute; z-index: 12; top: max(1.25rem, env(safe-area-inset-top)); left: max(1.25rem, env(safe-area-inset-left)); max-width: calc(100vw - 2.5rem); color: #f7f7eb; font: inherit; }
button, input { font: inherit; }
.scene-place-trigger { display: inline-flex; align-items: center; gap: .45rem; min-height: 2.75rem; max-width: min(18rem, 70vw); padding: .55rem .8rem; border: 1px solid #eef3e64d; border-radius: 999px; background: #142c34b0; color: inherit; box-shadow: 0 8px 28px #08182130; backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); cursor: pointer; font-size: .84rem; }
.scene-place-trigger svg { width: 1rem; height: 1rem; flex: none; }
.scene-place-trigger span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.scene-place-panel { width: min(22rem, calc(100vw - 2.5rem)); margin-top: .55rem; padding: 1rem; border: 1px solid #eef3e65e; border-radius: 1.1rem; background: #142c34f0; color: #f7f7eb; box-shadow: 0 15px 42px #07141db0; backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px); font-size: .875rem; }
.panel-heading { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.panel-heading h2 { margin: 0; font-size: 1rem; line-height: 1.35; font-weight: 620; }
.panel-heading button { width: 2rem; height: 2rem; border: 0; border-radius: .5rem; background: transparent; color: inherit; cursor: pointer; font-size: 1.35rem; line-height: 1; }
.panel-intro { margin: .35rem 0 1rem; color: #d9e4de; line-height: 1.5; }
label { display: block; margin-bottom: .35rem; font-weight: 600; }
.city-row { display: flex; gap: .45rem; }
.city-row input { min-width: 0; flex: 1; height: 2.75rem; padding: .55rem .7rem; border: 1px solid #dee9e275; border-radius: .7rem; outline: none; background: #f8f9ef; color: #183038; }
.city-row button, .place-choices button { min-height: 2.75rem; padding: .5rem .7rem; border: 1px solid #e8f2e686; border-radius: .7rem; background: #e4f1e11e; color: inherit; cursor: pointer; }
.place-choices { display: grid; gap: .4rem; margin-top: .45rem; }
.place-choices button { text-align: left; }
.scene-place-status, .scene-place-error { margin: .8rem 0 0; line-height: 1.5; }
.scene-place-error { color: #ffe0d4; }
.scene-place-status button, .clear-place { border: 0; padding: .25rem .2rem; background: transparent; color: #e5f3de; cursor: pointer; text-decoration: underline; text-underline-offset: .15rem; }
.scene-place-source { margin: .65rem 0 0; color: #d5e1db; font-size: .77rem; line-height: 1.45; }
.clear-place { margin-top: .7rem; font-size: .8rem; }
button:focus-visible, input:focus-visible { outline: 3px solid #fff3bd; outline-offset: 3px; }
@media (max-width: 40rem) { .scene-place { top: max(.85rem, env(safe-area-inset-top)); left: max(.85rem, env(safe-area-inset-left)); } .scene-place-panel { width: min(21rem, calc(100vw - 1.7rem)); } }
@media (prefers-reduced-transparency: reduce) { .scene-place-trigger, .scene-place-panel { background: #142c34; backdrop-filter: none; -webkit-backdrop-filter: none; } }
</style>
