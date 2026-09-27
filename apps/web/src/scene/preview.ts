import { createApp, defineComponent, h, shallowRef } from 'vue'
import NatureScene from './flow/ContinuousFlowScene.vue'
import { computeEnvironment, type WeatherCondition, type WeatherResponse } from './environment.ts'

const timeInput = document.querySelector<HTMLInputElement>('#fixture-time')!
const seasonInput = document.querySelector<HTMLSelectElement>('#fixture-season')!
const weatherInput = document.querySelector<HTMLSelectElement>('#fixture-weather')!
const query = new URLSearchParams(location.search)
const seasonProgress: Record<string, number> = {
  // Sample the season palette stops directly (March, June, September, December).
  spring: 2 / 12,
  summer: 5 / 12,
  autumn: 8 / 12,
  winter: 11 / 12,
}
timeInput.value = query.get('time') ?? '15:00'
seasonInput.value = query.get('season') ?? 'auto'
weatherInput.value = query.get('weather') ?? 'clear'

function frameForFixture() {
  const instant = new Date(`2026-09-26T${timeInput.value}:00+08:00`)
  const condition = weatherInput.value === 'unknown' ? null : weatherInput.value as WeatherCondition
  const weather: WeatherResponse | null = condition === null ? null : {
    availability: 'available', location_id: 'fixture-xian', source: 'synthetic-fixture',
    fetched_at: instant.toISOString(),
    observations: [{ kind: 'current', condition,
      cloud_cover: { clear: 0, partly_cloudy: 0.44, overcast: 0.94, rain: 0.94, fog: 0.72, snow: 0.84 }[condition],
      precipitation: condition === 'rain' || condition === 'snow' ? 0.7 : 0,
      visibility: condition === 'fog' ? 0.3 : 1,
      observed_at: instant.toISOString(), valid_until: new Date(instant.getTime() + 60_000).toISOString() }],
  }
  return computeEnvironment({ instant, location: { latitude: 34.3416, longitude: 108.9398 }, weather,
    season: seasonProgress[seasonInput.value] })
}

const frame = shallowRef(frameForFixture())
const preview = defineComponent({
  setup: () => () => h(NatureScene, { frame: frame.value }),
})
createApp(preview).mount('#scene-preview')

function update() {
  frame.value = frameForFixture()
  const url = new URL(location.href)
  url.searchParams.set('time', timeInput.value)
  url.searchParams.set('weather', weatherInput.value)
  if (seasonInput.value === 'auto') url.searchParams.delete('season')
  else url.searchParams.set('season', seasonInput.value)
  history.replaceState(null, '', url)
}
timeInput.addEventListener('input', update)
seasonInput.addEventListener('change', update)
weatherInput.addEventListener('change', update)
