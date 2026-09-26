import test from 'node:test'
import assert from 'node:assert/strict'

import { createAssistantSession } from '../../src/assistant/sessionStore.ts'

const candidate = (id, missing = []) => ({
  candidate_id: id, title: `事项 ${id}`, location: '教室',
  start_at: '2026-09-29T14:00:00+08:00', end_at: '2026-09-29T15:00:00+08:00',
  timezone: 'Asia/Shanghai', recurrence: null, missing_fields: missing,
})

const draft = (status = 'ready') => ({
  draft_id: 'draft-1', revision: 2, status, confirmation_digest: 'digest-1',
  expires_at: '2026-09-29T16:00:00+08:00', reference_now: '2026-09-26T10:00:00+08:00',
  related_action_ids: [], questions: status === 'needs_clarification' ? ['具体是几点？'] : [],
  candidates: [candidate('c1'), candidate('c2'), candidate('c3')],
})

test('closing and reopening retains unsent text and all draft candidates', () => {
  const session = createAssistantSession()
  session.open()
  session.setInput('下午三点再说')
  session.setDraft(draft())
  session.close()
  session.open()
  assert.equal(session.state.input, '下午三点再说')
  assert.deepEqual(session.state.draft.candidates.map(item => item.candidate_id), ['c1', 'c2', 'c3'])
})

test('draft and message alone never issue a commit command', async () => {
  let commits = 0
  const session = createAssistantSession({
    sendMessage: async () => ({ answer: '请核对草稿', draft: draft() }),
    confirmDraft: async () => { commits++; throw new Error('unexpected') },
  })
  session.setInput('明天下午两点上课')
  await session.sendMessage()
  assert.equal(commits, 0)
  assert.equal(session.state.draft.candidates.length, 3)
})

test('missing fields stay in clarification state and cannot commit', async () => {
  let commits = 0
  const session = createAssistantSession({
    confirmDraft: async () => { commits++; throw new Error('unexpected') },
  })
  session.setDraft({ ...draft('needs_clarification'), candidates: [candidate('c1', ['start_at'])] })
  const result = await session.confirmDraft()
  assert.equal(result, false)
  assert.equal(commits, 0)
  assert.equal(session.state.draft.status, 'needs_clarification')
  assert.deepEqual(session.state.draft.questions, ['具体是几点？'])
})

test('explicit confirmation sends every candidate ID and only then marks saved', async () => {
  let sent
  const session = createAssistantSession({
    confirmDraft: async (draftId, request) => {
      sent = { draftId, request }
      return { draft_id: 'draft-1', revision: 3, resources: [
        { resource_id: 'e1', resource_type: 'event', version: 1 },
        { resource_id: 'e2', resource_type: 'event', version: 1 },
        { resource_id: 'e3', resource_type: 'event', version: 1 },
      ] }
    },
  })
  session.setDraft(draft())
  assert.equal(session.state.draft.status, 'ready')
  assert.equal(await session.confirmDraft(), true)
  assert.deepEqual(sent, { draftId: 'draft-1', request: {
    revision: 2, confirmation_digest: 'digest-1',
    confirmed_candidate_ids: ['c1', 'c2', 'c3'], conflict_acceptance: null,
  } })
  assert.equal(session.state.draft.status, 'committed')
})

test('send failure retains original text and existing draft for retry', async () => {
  let attempts = 0
  const keys = []
  const session = createAssistantSession({
    sendMessage: async (_text, key) => { attempts++; keys.push(key); throw new Error('network down') },
  })
  session.setDraft(draft())
  session.setInput('原文必须保留')
  assert.equal(await session.sendMessage(), false)
  assert.equal(session.state.input, '原文必须保留')
  assert.equal(session.state.draft.candidates.length, 3)
  assert.match(session.state.error, /结果未确认/)
  assert.equal(await session.sendMessage(), false)
  assert.equal(attempts, 2)
  assert.ok(keys[0])
  assert.equal(keys[0], keys[1])
})

test('commit failure keeps draft ready and offers retry without false success', async () => {
  let attempts = 0
  const keys = []
  const session = createAssistantSession({
    confirmDraft: async (_id, _request, key) => { attempts++; keys.push(key); throw new Error('timeout') },
  })
  session.setDraft(draft())
  assert.equal(await session.confirmDraft(), false)
  assert.equal(session.state.draft.status, 'ready')
  assert.match(session.state.error, /结果未确认/)
  assert.equal(await session.confirmDraft(), false)
  assert.equal(attempts, 2)
  assert.ok(keys[0])
  assert.equal(keys[0], keys[1])
})

test('five-minute reminder can be dismissed immediately and is never re-shown in the same session', async () => {
  let acknowledged
  const session = createAssistantSession({
    acknowledgeReminder: async (reminder) => { acknowledged = reminder.reminder_id },
  })
  const reminder = { reminder_id: 'rem-1', occurrence_id: 'occ-1', version: 1, schedule_revision: 1,
    acknowledged_at: null, event_title: '软件工程课', location: '教学楼A', minutes_until_start: 5 }
  session.setReminder(reminder)
  assert.equal(session.state.reminder.reminder_id, 'rem-1')
  assert.equal(await session.acknowledgeReminder(), true)
  assert.equal(acknowledged, 'rem-1')
  assert.equal(session.state.reminder, null)
  session.setReminder(reminder)
  assert.equal(session.state.reminder, null)
})

test('reminder acknowledgment failure still dismisses locally and never restores a blocking prompt', async () => {
  const session = createAssistantSession({ acknowledgeReminder: async () => { throw new Error('offline') } })
  session.setReminder({ reminder_id: 'rem-2', occurrence_id: 'occ-2', version: 1, schedule_revision: 1,
    acknowledged_at: null, event_title: '课程', location: null, minutes_until_start: 4 })
  assert.equal(await session.acknowledgeReminder(), true)
  assert.equal(session.state.reminder, null)
  assert.match(session.state.notice, /稍后同步/)
})
