import test from 'node:test'
import assert from 'node:assert/strict'
import { WaterTapController } from '../../src/scene/flow/waterInteraction.ts'

test('a short stationary primary press produces one ripple at the release point', () => {
  const tap = new WaterTapController()
  tap.pointerDown(1, 20, 30, 100)
  assert.deepEqual(tap.pointerUp(1, 23, 32, 500), { x: 23, y: 32 })
  assert.equal(tap.pointerUp(1, 23, 32, 501), null)
})

test('long presses and drags do not produce a water ripple', () => {
  const tap = new WaterTapController()
  tap.pointerDown(1, 20, 30, 100)
  assert.equal(tap.pointerUp(1, 20, 30, 700), null)

  tap.pointerDown(2, 20, 30, 800)
  tap.pointerMove(2, 31, 30)
  assert.equal(tap.pointerUp(2, 31, 30, 900), null)
})

test('ineligible presses and pointer cancellation never produce a ripple', () => {
  const tap = new WaterTapController()
  tap.pointerDown(1, 20, 30, 100, false)
  assert.equal(tap.pointerUp(1, 20, 30, 200), null)

  tap.pointerDown(2, 20, 30, 300)
  tap.cancel()
  assert.equal(tap.pointerUp(2, 20, 30, 400), null)
})
