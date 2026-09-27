import test from 'node:test'
import assert from 'node:assert/strict'

import { RealClock, SceneClock } from '../../src/platform/clocks.ts'

test('accelerating the scene clock cannot change a real-clock read', () => {
  const before = Date.now()
  const real = new RealClock()
  let elapsed = 0
  const scene = new SceneClock(new Date('2000-01-01T00:00:00Z'), () => elapsed, 3600)
  elapsed = 10_000
  assert.equal(scene.now().toISOString(), '2000-01-01T10:00:00.000Z')
  const observed = real.now().getTime()
  assert.ok(observed >= before && observed <= Date.now())
})
