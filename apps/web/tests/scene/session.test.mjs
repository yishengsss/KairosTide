import test from 'node:test'
import assert from 'node:assert/strict'

import { SceneEnvironmentSession } from '../../src/scene/session.ts'

test('production scene frames refresh from the injected real-time source', () => {
  let instant = new Date('2026-06-01T06:00:00.000Z')
  const session = new SceneEnvironmentSession({ now: () => new Date(instant) }, null, null)
  assert.equal(session.frame.instant.toISOString(), '2026-06-01T06:00:00.000Z')
  instant = new Date('2026-06-01T06:01:00.000Z')
  assert.equal(session.refresh().instant.toISOString(), '2026-06-01T06:01:00.000Z')
  assert.equal(session.frame.atmosphere.availability, 'unavailable')
})

test('user-selected location and weather update the scene without changing the clock', () => {
  const instant = new Date('2026-09-26T07:00:00.000Z')
  const session = new SceneEnvironmentSession({ now: () => instant })
  const before = session.frame
  const after = session.setInputs({ latitude: 34.3416, longitude: 108.9398 }, {
    availability: 'available', location_id: 'Xi An', latitude: 34.3416, longitude: 108.9398,
    fetched_at: instant.toISOString(), source: 'Open-Meteo', observations: [{
      kind: 'current', condition: 'rain', cloud_cover: 90, precipitation: 1,
      visibility: 10000, observed_at: instant.toISOString(), valid_until: '2026-09-26T08:00:00.000Z',
    }],
  })
  assert.equal(after.instant.toISOString(), instant.toISOString())
  assert.equal(after.sun.accuracy, 'location_based_approximation')
  assert.equal(after.atmosphere.condition, 'rain')
  assert.notEqual(after.sun.elevationDeg, before.sun.elevationDeg)
  const cleared = session.setInputs(null, null)
  assert.equal(cleared.atmosphere.condition, null)
  assert.equal(cleared.sun.accuracy, 'local_clock_approximation')
})
