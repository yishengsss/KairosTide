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
