import test from 'node:test'
import assert from 'node:assert/strict'
import { findMarkerPosition, screenYForMarker } from '../../src/presentation/markerLayout.ts'
import { createFlowPainter, waterSurfaceYAt } from '../../src/scene/flow/painter.ts'
import { computeEnvironment } from '../../src/scene/environment.ts'

const base = { id: 'task-1', kind: 'flexible', width: 400, height: 300, diameter: 40, minGap: 10,
  waterlineAt: x => 150 + x / 20, existing: [] }

test('marker circle stays beneath the sampled local waterline and inside the scene', () => {
  const marker = findMarkerPosition({ ...base, random: () => 0.5 })
  assert.ok(marker)
  const y = screenYForMarker(marker, base.waterlineAt)
  assert.ok(marker.x >= 20 && marker.x <= 380)
  assert.ok(y + 20 <= 300)
  for (const x of [marker.x - 20, marker.x, marker.x + 20]) {
    assert.ok(y - 20 >= base.waterlineAt(x))
  }
})

test('injected randomness makes placement reproducible', () => {
  const input = { ...base, random: () => 0.25 }
  const first = findMarkerPosition(input)
  assert.ok(first)
  assert.equal(first.x, 114)
  assert.deepEqual(first, findMarkerPosition(input))
})

test('rigid and flexible circles avoid each other with the requested gap', () => {
  const first = findMarkerPosition({ ...base, random: () => 0.5 })
  assert.ok(first)
  const values = [0.5, 0.5, 0.9, 0.5]
  let index = 0
  const second = findMarkerPosition({ ...base, id: 'event-1', kind: 'rigid',
    existing: [first], random: () => values[index++ % values.length] })
  assert.ok(second)
  assert.ok(second.x > 300, 'a colliding first candidate is retried')
  const distance = Math.hypot(second.x - first.x,
    screenYForMarker(second, base.waterlineAt) - screenYForMarker(first, base.waterlineAt))
  assert.ok(distance >= (second.diameter + first.diameter) / 2 + base.minGap)
})

test('placing another marker never changes an existing position', () => {
  const existing = [{ id: 'event-1', kind: 'rigid', diameter: 40, x: 100, offsetBelowWaterline: 70 }]
  const snapshot = structuredClone(existing)
  assert.ok(findMarkerPosition({ ...base, existing, random: () => 0.8 }))
  assert.deepEqual(existing, snapshot)
})

test('returns null when no circle fits below the waterline', () => {
  assert.equal(findMarkerPosition({ ...base, height: 180, waterlineAt: () => 170,
    random: () => 0.5 }), null)
})

test('non-finite or oversized attempt counts remain bounded', () => {
  let calls = 0
  assert.equal(findMarkerPosition({ ...base, height: 180, waterlineAt: () => 170,
    attempts: Number.POSITIVE_INFINITY, random: () => { calls += 1; return 0.5 } }), null)
  assert.ok(calls <= 256)
  calls = 0
  assert.equal(findMarkerPosition({ ...base, height: 180, waterlineAt: () => 170,
    attempts: 1_000_000, random: () => { calls += 1; return 0.5 } }), null)
  assert.ok(calls <= 256)
})

test('flow painter exposes a per-x CSS-pixel sampler for its current wave', () => {
  const context = new Proxy({}, {
    get: (_, key) => (...args) => {
      if (key === 'createLinearGradient' || key === 'createRadialGradient') return { addColorStop() {} }
    },
    set: () => true,
  })
  const frame = computeEnvironment({ instant: new Date('2026-09-26T04:30:00Z'),
    location: { latitude: 34, longitude: 109 }, weather: null })
  const sample = createFlowPainter(context)(frame, 390, 844, 7)
  const tide = Math.max(0.05, Math.sin(frame.sun.elevationDeg * Math.PI / 180) * 0.9 + 0.1)
  assert.equal(typeof sample, 'function')
  assert.equal(sample(20), waterSurfaceYAt(20, 844, tide, 7))
  assert.equal(sample(300), waterSurfaceYAt(300, 844, tide, 7))
  assert.notEqual(sample(20), sample(300))
})

test('a stable marker stays below the whole shoreline and above the bottom as wave phase advances', () => {
  const height = 900
  for (const [diameter, randomValues, tide] of [
    [64, [0.1, 0], 1],
    [48, [0.35, 1], 0.8],
  ]) {
    let index = 0
    const marker = findMarkerPosition({ id: 'phase-safe', kind: 'flexible', width: 800, height,
      diameter, minGap: 8, waterlineAt: x => waterSurfaceYAt(x, height, tide, 0), existing: [],
      random: () => randomValues[index++ % randomValues.length], attempts: 1 })
    assert.ok(marker)
    for (const laterTide of [0.05, 0.35, tide, 1]) {
      for (let seconds = 0; seconds <= 40; seconds += 0.25) {
        const line = x => waterSurfaceYAt(x, height, laterTide, seconds)
        const y = screenYForMarker(marker, line)
        assert.ok(y + diameter / 2 <= height - 8 + 1e-8)
        for (let x = marker.x - diameter / 2; x <= marker.x + diameter / 2; x += 2) {
          assert.ok(y - diameter / 2 >= line(x) - 1e-8)
        }
      }
    }
  }
})

test('a candidate that would collide in a later wave phase is deferred', () => {
  const height = 900
  const existing = [{ id: 'rigid', kind: 'rigid', diameter: 48, x: 150, offsetBelowWaterline: 45 }]
  const x = 110
  const xRandom = (x - 32) / (800 - 64)
  let index = 0
  const values = [xRandom, 0.4]
  const marker = findMarkerPosition({ id: 'flexible', kind: 'flexible', width: 800, height,
    diameter: 48, minGap: 8, waterlineAt: point => waterSurfaceYAt(point, height, 0.8, 0),
    existing, random: () => values[index++ % values.length], attempts: 1 })
  assert.equal(marker, null)
})
