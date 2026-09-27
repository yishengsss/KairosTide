import test from 'node:test'
import assert from 'node:assert/strict'
import { activeFlexibleTasks, FlexibleTaskSignals, eligibleFlexibleTasks } from '../../src/presentation/flexibleTaskSignals.ts'
import { transitionFlexibleTaskRequest } from '../../src/presentation/flexibleTaskClient.ts'

function harness(random = () => 0) {
  let now = 1000
  const timers = new Map()
  let id = 0
  const signals = new FlexibleTaskSignals(() => now, random, () => {}, (fn, delay) => {
    const key = ++id; timers.set(key, { fn, at: now + Number(delay) }); return key
  }, key => timers.delete(key))
  return { signals, timers, jump(ms) { now += ms }, advance(ms) { now += ms; for (const [key, timer] of [...timers]) if (timer.at <= now) { timers.delete(key); timer.fn() } } }
}

test('each cue has independent randomized 5–10 minute lifetime, independent of detail', () => {
  const h = harness(() => 0)
  h.signals.show('a'); h.advance(1000); h.signals.show('b')
  assert.deepEqual([...h.signals.cues.keys()], ['a', 'b'])
  h.advance(298999); assert.equal(h.signals.cues.has('a'), true)
  h.advance(1); assert.equal(h.signals.cues.has('a'), false)
  assert.equal(h.signals.cues.has('b'), true)
  h.advance(299000); assert.equal(h.signals.cues.has('b'), false)
})

test('random lifetime reaches the inclusive ten minute bound', () => {
  const h = harness(() => 1)
  h.signals.show('a'); h.advance(600000)
  assert.equal(h.signals.cues.has('a'), false)
})

test('expired wall-clock cues are pruned after a suspended or hidden page resumes', () => {
  const h = harness(() => 0)
  h.signals.show('a'); h.jump(300000)
  // The fake browser did not dispatch its throttled timer while hidden.
  h.timers.clear(); h.signals.expireDue()
  assert.equal(h.signals.cues.has('a'), false)
})

test('only planned, not already cued tasks are eligible; active and completed stay excluded', () => {
  const task = (task_id, lifecycle_status) => ({ task_id, lifecycle_status })
  assert.deepEqual(eligibleFlexibleTasks([
    task('planned', 'planned'), task('active', 'active'), task('done', 'completed'), task('shown', 'planned'),
  ], new Set(['shown'])).map(item => item.task_id), ['planned'])
})

test('server snapshots restore every active task ring and exclude completed tasks', () => {
  const task = (task_id, lifecycle_status) => ({ task_id, lifecycle_status })
  assert.deepEqual(activeFlexibleTasks([
    task('planned', 'planned'), task('active-1', 'active'), task('active-2', 'active'), task('done', 'completed'),
  ]).map(item => item.task_id), ['active-1', 'active-2'])
})

test('cue removal and dispose cancel timers without implying detail dismissal', () => {
  const h = harness(); h.signals.show('a'); h.signals.remove('a')
  assert.equal(h.timers.size, 0); assert.equal(h.signals.cues.size, 0)
  h.signals.show('b'); h.signals.dispose(); assert.equal(h.timers.size, 0)
})

test('lifecycle actions call the direct API with an idempotency key and expected version', async () => {
  let request
  const task = { task_id: 'task/42', lifecycle_status: 'active', version: 8 }
  const result = await transitionFlexibleTaskRequest('task/42', 'active', 7, async (url, init) => {
    request = { url, init }
    return { ok: true, json: async () => task }
  })
  assert.equal(result, task)
  assert.equal(request.url, '/api/v1/flexible-tasks/task%2F42/lifecycle')
  assert.equal(request.init.method, 'POST')
  assert.ok(request.init.headers['Idempotency-Key'])
  assert.deepEqual(JSON.parse(request.init.body), { status: 'active', expected_version: 7 })
})

test('API failures leave lifecycle mutation to the caller and report stale versions', async () => {
  await assert.rejects(transitionFlexibleTaskRequest('t1', 'completed', 2, async () => ({ ok: false, status: 409 })),
    /任务状态已更新/)
})
