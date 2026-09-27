import test from 'node:test'
import assert from 'node:assert/strict'
import { reminderUrgency, sceneModeForActiveCount } from '../../src/presentation/sceneMode.ts'

test('reminder urgency rises from calm at five minutes to the capped warning at start', () => {
  assert.equal(reminderUrgency(5), 0)
  assert.equal(reminderUrgency(3), 0.4)
  assert.equal(reminderUrgency(0), 1)
  assert.equal(reminderUrgency(-2), 1)
  assert.equal(reminderUrgency(8), 0)
})

test('scene enters work only while a rigid event is active', () => {
  assert.equal(sceneModeForActiveCount(0), 'free')
  assert.equal(sceneModeForActiveCount(1), 'work')
  assert.equal(sceneModeForActiveCount(2), 'work')
})
