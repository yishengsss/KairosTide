import test from 'node:test'
import assert from 'node:assert/strict'

import { computeEnvironment } from '../../src/scene/environment.ts'

const location = { latitude: 34.3416, longitude: 108.9398 }
const instant = new Date('2026-09-26T07:00:00.000Z')

function weather(condition, cloudCover) {
  return {
    availability: 'available', location_id: 'fixture-xian', fetched_at: instant.toISOString(),
    source: 'fixture', observations: [{ kind: 'current', condition,
      cloud_cover: cloudCover, precipitation: condition === 'rain' ? 0.7 : 0,
      visibility: null, observed_at: instant.toISOString(), valid_until: '2026-09-26T08:00:00.000Z' }],
  }
}

test('rain obscures light without moving the astronomical sun', () => {
  const clear = computeEnvironment({ instant, location, weather: weather('clear', 0) })
  const rain = computeEnvironment({ instant, location, weather: weather('rain', 0.9) })
  assert.deepEqual(rain.sun, clear.sun)
  assert.ok(rain.atmosphere.transmission < clear.atmosphere.transmission)
  assert.ok(rain.atmosphere.rain > 0)
  assert.equal(clear.atmosphere.rain, 0)
})

test('sun reaches near zenith at equatorial equinox noon and nears horizon at dawn', () => {
  const equator = { latitude: 0, longitude: 0 }
  const noon = computeEnvironment({ instant: new Date('2026-03-20T12:00:00Z'), location: equator, weather: null })
  const dawn = computeEnvironment({ instant: new Date('2026-03-20T06:00:00Z'), location: equator, weather: null })
  assert.ok(noon.sun.elevationDeg > 85 && noon.sun.elevationDeg <= 90)
  assert.ok(Math.abs(dawn.sun.elevationDeg) < 5)
  assert.ok(dawn.sun.screenX < noon.sun.screenX)
})

test('unknown weather stays unknown and does not silently become clear', () => {
  const frame = computeEnvironment({ instant, location, weather: null })
  assert.equal(frame.atmosphere.availability, 'unavailable')
  assert.equal(frame.atmosphere.condition, null)
  assert.equal(frame.atmosphere.rain, 0)
})

test('rain meaningfully dims daylight while snow changes the ground without changing the sun', () => {
  const clear = computeEnvironment({ instant, location, weather: weather('clear', 0) })
  const rain = computeEnvironment({ instant, location, weather: weather('rain', 0.9) })
  const overcast = computeEnvironment({ instant, location, weather: weather('overcast', 0.9) })
  const snow = computeEnvironment({ instant, location, weather: weather('snow', 0.9) })
  const brightness = (color) => color.r + color.g + color.b
  assert.ok(brightness(clear.palette.skyZenith) - brightness(rain.palette.skyZenith) > 25)
  assert.ok(brightness(snow.palette.shore) - brightness(overcast.palette.shore) > 20)
  assert.deepEqual(snow.sun, overcast.sun)
})

test('sky and season progress continuously across local midnight without a phase reset', () => {
  const before = computeEnvironment({ instant: new Date(2026, 8, 26, 23, 59, 59), location: null, weather: null })
  const after = computeEnvironment({ instant: new Date(2026, 8, 27, 0, 0, 1), location: null, weather: null })
  for (const key of ['r', 'g', 'b']) {
    assert.ok(Math.abs(before.palette.skyZenith[key] - after.palette.skyZenith[key]) < 3)
  }
  assert.ok(Math.abs(before.season.progress - after.season.progress) < 0.001)
  assert.equal(after.sun.accuracy, 'local_clock_approximation')
})
