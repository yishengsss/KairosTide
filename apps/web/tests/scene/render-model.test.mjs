import test from 'node:test'
import assert from 'node:assert/strict'

import { sceneStyle, shouldAnimateScene, waterGlints } from '../../src/scene/renderer.ts'
import { computeEnvironment } from '../../src/scene/environment.ts'

const instant = new Date('2026-09-26T07:00:00Z')
const location = { latitude: 34.3416, longitude: 108.9398 }

function frame(condition) {
  const weather = condition === null ? null : {
    availability: 'available', fetched_at: instant.toISOString(), location_id: 'test', source: 'fixture',
    observations: [{ kind: 'current', condition, cloud_cover: condition === 'clear' ? 0 : 0.9,
      precipitation: null, visibility: null, observed_at: instant.toISOString(), valid_until: null }],
  }
  return computeEnvironment({ instant, location, weather })
}

test('weather appearance changes while rendered sun coordinates remain fixed', () => {
  const clear = sceneStyle(frame('clear'))
  const rain = sceneStyle(frame('rain'))
  assert.equal(clear['--sun-x'], rain['--sun-x'])
  assert.equal(clear['--sun-y'], rain['--sun-y'])
  assert.notEqual(clear['--cloud-opacity'], rain['--cloud-opacity'])
  assert.notEqual(clear['--sky-zenith'], rain['--sky-zenith'])
})

test('reduced motion disables decorative frame updates even in rain', () => {
  assert.equal(shouldAnimateScene(frame('rain'), true, true), false)
  assert.equal(shouldAnimateScene(frame('rain'), false, false), false)
  assert.equal(shouldAnimateScene(frame('rain'), false, true), true)
})

test('scene rendering carries distinct mid-mountain and sunlit ridge planes', () => {
  const style = sceneStyle(frame('clear'))
  assert.match(style['--mountain-mid'], /^rgb\(/)
  assert.match(style['--mountain-light'], /^rgb\(/)
  assert.notEqual(style['--mountain-mid'], style['--mountain-far'])
  assert.notEqual(style['--mountain-light'], style['--mountain-near'])
})

test('sunlight breaks into irregular water glints instead of a ladder-like stripe', () => {
  const glints = waterGlints(frame('clear'), 1600, 900, 12)
  assert.ok(glints.length >= 40)
  const lengths = glints.map(({ x1, x2 }) => x2 - x1)
  assert.ok(new Set(lengths.map((length) => Math.round(length))).size > 6)
  const sortedY = [...new Set(glints.map(({ y }) => Math.round(y * 10) / 10))].sort((a, b) => a - b)
  const gaps = sortedY.slice(1).map((y, index) => y - sortedY[index])
  assert.ok(new Set(gaps.map((gap) => Math.round(gap * 100) / 100)).size > 3)
})

test('bird silhouettes are limited to twilight rather than displayed at midday', () => {
  const dawn = computeEnvironment({ instant: new Date('2026-03-20T06:00:00Z'), location: { latitude: 0, longitude: 0 }, weather: null })
  const noon = computeEnvironment({ instant: new Date('2026-03-20T12:00:00Z'), location: { latitude: 0, longitude: 0 }, weather: null })
  const dawnOpacity = Number(sceneStyle(dawn)['--bird-opacity'])
  const noonOpacity = Number(sceneStyle(noon)['--bird-opacity'])
  assert.ok(dawnOpacity > 0.5)
  assert.ok(noonOpacity < 0.1)
})
