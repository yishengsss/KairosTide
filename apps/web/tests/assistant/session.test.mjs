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

const proposal = (overrides = {}) => ({
  proposal_id: 'proposal-1', target_id: 'occurrence-1', scope: 'occurrence', revision: 2,
  action: 'update', summary: '修改这次课程', confirmation_digest: 'digest-2',
  status: 'pending', target_title: '高数课',
  changes: { title: '高等数学', location: '教学楼 B', start_at: '2026-09-29T15:00:00+08:00', end_at: '2026-09-29T16:00:00+08:00' },
  ...overrides,
})

test('assistant proposal stays pending until explicit confirmation and duplicate submission is ignored', async () => {
  let resolveCommit
  const calls = []
  const session = createAssistantSession({
    sendMessage: async () => ({ answer: '请核对修改。', action_results: [
      { action: 'propose_rigid_event_change', status: 'succeeded', data: proposal(), message: null },
    ] }),
    commitProposal: async (id, request, key) => {
      calls.push({ id, request, key })
      return new Promise(resolve => { resolveCommit = resolve })
    },
  })
  session.setInput('把这次高数课改到三点')
  await session.sendMessage()
  assert.equal(calls.length, 0)
  assert.equal(session.state.messages.at(-1).actionResults[0].data.status, 'pending')

  const confirming = session.confirmProposal('proposal-1')
  assert.equal(await session.confirmProposal('proposal-1'), false)
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].request, {
    revision: 2, confirmation_digest: 'digest-2', source_action_id: calls[0].key,
  })
  assert.ok(calls[0].key)
  resolveCommit({ proposal_id: 'proposal-1', target_id: 'occurrence-1', scope: 'occurrence',
    action: 'update', affected_ids: ['occurrence-1'], version: 4, status: 'committed' })
  assert.equal(await confirming, true)
  assert.equal(session.state.proposalCommits['proposal-1'].status, 'committed')
  assert.equal(await session.confirmProposal('proposal-1'), false)
  assert.equal(calls.length, 1)
})

test('structured proposal remains visible when the assistant answer is empty', async () => {
  const session = createAssistantSession({ sendMessage: async () => ({ answer: '', action_results: [
    { action: 'propose_rigid_event_change', status: 'succeeded', data: proposal(), message: null },
  ] }) })
  session.setInput('修改课程')
  await session.sendMessage()
  assert.equal(session.state.messages.at(-1).actionResults[0].data.proposal_id, 'proposal-1')
})

test('commit conflict or expiry retains the exact proposal and stable retry key', async () => {
  const keys = []
  const session = createAssistantSession({
    sendMessage: async () => ({ answer: '请确认。', action_results: [
      { action: 'propose_rigid_event_change', status: 'succeeded', data: proposal(), message: null },
    ] }),
    commitProposal: async (_id, _request, key) => { keys.push(key); throw new Error('HTTP 409') },
  })
  session.setInput('改时间')
  await session.sendMessage()
  assert.equal(await session.confirmProposal('proposal-1'), false)
  assert.equal(session.state.messages.at(-1).actionResults[0].data.status, 'pending')
  assert.match(session.state.proposalErrors['proposal-1'], /尚未确认/)
  assert.equal(await session.confirmProposal('proposal-1'), false)
  assert.equal(keys.length, 2)
  assert.equal(keys[0], keys[1])
  assert.equal(session.state.proposalCommits['proposal-1'], undefined)
})

test('rejected and already committed proposal results cannot trigger a commit', async () => {
  let calls = 0
  const session = createAssistantSession({
    commitProposal: async () => { calls++; throw new Error('unexpected') },
  })
  session.state.messages.push({ role: 'assistant', content: '未生成', actionResults: [
    { action: 'propose_rigid_event_change', status: 'rejected', data: proposal(), message: '目标已过期' },
    { action: 'propose_rigid_event_change', status: 'succeeded', data: proposal({ proposal_id: 'p2', status: 'committed' }), message: null },
  ] })
  assert.equal(await session.confirmProposal('proposal-1'), false)
  assert.equal(await session.confirmProposal('p2'), false)
  assert.equal(calls, 0)
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

test('event reaching start while assistant is open shows a light notice and clears when no longer active', async () => {
  let snapshot = { due_reminders: [], active_occurrences: [] }
  const session = createAssistantSession({ getState: async () => snapshot })
  session.open()
  snapshot = { due_reminders: [], active_occurrences: [
    { title: '软件工程课', location: '教学楼A' },
  ] }
  await session.refreshState()
  assert.equal(session.state.activeNotice, '正在进行：软件工程课 · 教学楼A')

  snapshot = { due_reminders: [], active_occurrences: [] }
  await session.refreshState()
  assert.equal(session.state.activeNotice, '')
})

test('the scene returns from WORK to FREE when the active occurrence ends', async () => {
  const active = { occurrence_id: 'o-1', event_id: 'e-1', version: 1, title: '课程', location: null,
    temporal_phase: 'active', disposition: 'scheduled', start_at: '2026-09-29T14:00:00+08:00', end_at: '2026-09-29T15:00:00+08:00' }
  let snapshot = { due_reminders: [], active_occurrences: [active] }
  const session = createAssistantSession({ getState: async () => snapshot })
  await session.refreshState()
  assert.deepEqual(session.state.activeOccurrences, [active])

  snapshot = { due_reminders: [], active_occurrences: [] }
  await session.refreshState()
  assert.deepEqual(session.state.activeOccurrences, [])
})

test('the exception action records this occurrence directly without opening or messaging the assistant', async () => {
  const active = { occurrence_id: 'o-9', event_id: 'e-9', version: 3, title: '高数课', location: '教室A',
    temporal_phase: 'active', disposition: 'scheduled', start_at: '2026-09-26T14:00:00+08:00', end_at: '2026-09-26T15:00:00+08:00' }
  let snapshot = { server_now: '2026-09-26T06:30:00Z', due_reminders: [], active_occurrences: [active],
    conflicts: [], state_revision: 4, next_transition_at: active.end_at }
  const calls = []
  const session = createAssistantSession({
    getState: async () => snapshot,
    sendMessage: async () => { throw new Error('AI must not be called') },
    excuseOccurrence: async (occurrence, actionId) => {
      calls.push([occurrence.occurrence_id, occurrence.version, actionId])
      snapshot = { ...snapshot, active_occurrences: [] }
      return { ...occurrence, disposition: 'excused' }
    },
  })
  await session.refreshState()
  const result = await session.excuseOccurrence('o-9')
  assert.equal(result, true)
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 'o-9')
  assert.equal(calls[0][1], 3)
  assert.ok(calls[0][2])
  assert.equal(session.state.open, false)
  assert.deepEqual(session.state.activeOccurrences, [])
  assert.equal(session.state.notice, '已记录“高数课”本次请假。')
})

test('an acknowledged reminder still schedules automatic WORK and FREE boundaries', async () => {
  const startsAt = '2026-09-26T07:00:00Z'
  const endsAt = '2026-09-26T08:00:00Z'
  const reminder = { reminder_id: 'r-1', occurrence_id: 'o-1', version: 1, schedule_revision: 1,
    acknowledged_at: null, event_title: '课程', location: '教室', start_at: startsAt, minutes_until_start: 5 }
  const active = { occurrence_id: 'o-1', event_id: 'e-1', version: 1, title: '课程', location: '教室',
    temporal_phase: 'active', disposition: 'scheduled', start_at: startsAt, end_at: endsAt }
  let snapshot = { server_now: '2026-09-26T06:55:00Z', due_reminders: [reminder], active_occurrences: [] }
  const session = createAssistantSession({
    getState: async () => snapshot,
    acknowledgeReminder: async () => {},
  })

  await session.refreshState()
  assert.equal(Date.parse(session.state.nextTransitionAt), Date.parse(startsAt))
  await session.acknowledgeReminder()
  snapshot = { server_now: '2026-09-26T06:59:59Z', due_reminders: [], active_occurrences: [] }
  await session.refreshState()
  assert.equal(Date.parse(session.state.nextTransitionAt), Date.parse(startsAt), 'acknowledging the card must not cancel the event start')

  snapshot = { server_now: startsAt, due_reminders: [], active_occurrences: [active] }
  await session.refreshState()
  assert.deepEqual(session.state.activeOccurrences, [active])
  assert.equal(Date.parse(session.state.nextTransitionAt), Date.parse(endsAt))

  snapshot = { server_now: endsAt, due_reminders: [], active_occurrences: [] }
  await session.refreshState()
  assert.deepEqual(session.state.activeOccurrences, [])
  assert.equal(session.state.nextTransitionAt, null)
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

test('typing confirm after the latest ready draft commits that exact draft instead of re-parsing chat', async () => {
  let sends = 0
  let commits = 0
  const session = createAssistantSession({
    sendMessage: async () => { sends++; return { answer: '不应重新解析' } },
    confirmDraft: async () => {
      commits++
      return { draft_id: 'draft-1', revision: 3, resources: [
        { resource_id: 'event-1', resource_type: 'event', version: 1 },
        { resource_id: 'event-2', resource_type: 'event', version: 1 },
        { resource_id: 'event-3', resource_type: 'event', version: 1 },
      ] }
    },
  })
  session.state.messages.push({ role: 'assistant', content: '已生成日程草稿，请检查内容并确认。' })
  session.setDraft(draft())
  session.setInput('确认')

  assert.equal(await session.sendMessage(), true)
  assert.equal(sends, 0)
  assert.equal(commits, 1)
  assert.equal(session.state.draft.status, 'committed')
  assert.equal(session.state.input, '')
})

test('typing confirm after a newer unrelated reply does not commit an older ready draft', async () => {
  let sends = 0
  let commits = 0
  const session = createAssistantSession({
    sendMessage: async () => { sends++; return { answer: '普通对话回复' } },
    confirmDraft: async () => {
      commits++
      return { draft_id: 'draft-1', revision: 3, resources: [
        { resource_id: 'event-1', resource_type: 'event', version: 1 },
        { resource_id: 'event-2', resource_type: 'event', version: 1 },
        { resource_id: 'event-3', resource_type: 'event', version: 1 },
      ] }
    },
  })
  session.state.messages.push({ role: 'assistant', content: '已生成日程草稿，请检查内容并确认。' })
  session.setDraft(draft())
  session.state.messages.push({ role: 'user', content: '顺便问一下天气' })
  session.state.messages.push({ role: 'assistant', content: '请先告诉我城市。' })
  session.setInput('确认')

  assert.equal(await session.sendMessage(), true)
  assert.equal(sends, 1)
  assert.equal(commits, 0)
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

test('image attachment stays memory-only through clarification and clears after a draft reply', async () => {
  const image = { name: 'timetable.png', type: 'image/png', size: 4 }
  const sent = []
  const session = createAssistantSession({ sendMessage: async (text, _id, _messages, attachment) => {
    sent.push({ text, attachment })
    return sent.length === 1
      ? { answer: '请补充课表系列的开始日期和结束日期。', retain_image: true }
      : { answer: '已生成草稿。', retain_image: false }
  } })
  session.setImage(image)
  await session.sendMessage()
  assert.equal(sent[0].text, '请识别图片中的信息并告诉我能看出什么。')
  assert.equal(session.state.image, image)
  session.setInput('从 2026-09-01 到 2026-12-31')
  await session.sendMessage()
  assert.equal(sent[0].attachment, image)
  assert.equal(sent[1].attachment, image)
  assert.equal(session.state.image, null)
  assert.equal(session.state.messages[0].hasImage, true)
})

test('saving an overlapping draft requires a second explicit confirmation', async () => {
  const requests = []
  const session = createAssistantSession({ confirmDraft: async (_draftId, request) => {
    requests.push(request)
    if (!request.conflict_acceptance) {
      throw Object.assign(new Error('conflict'), {
        conflictAcceptance: 'server-token', conflictPairs: [['candidate-a', 'event-b']],
      })
    }
    return { draft_id: 'draft-1', revision: 1, resources: [
      { resource_type: 'event', resource_id: 'e1', version: 1 },
      { resource_type: 'event', resource_id: 'e2', version: 1 },
      { resource_type: 'event', resource_id: 'e3', version: 1 },
    ] }
  } })
  session.setDraft(draft())
  assert.equal(await session.confirmDraft(), false)
  assert.equal(session.state.draftConflict.pairs.length, 1)
  assert.equal(await session.confirmDraft(), true)
  assert.equal(requests[0].conflict_acceptance, null)
  assert.equal(requests[1].conflict_acceptance, 'server-token')
})

test('structured task operation results stay attached to the assistant reply', async () => {
  const actionResults = [{ action: 'create_flexible_task', status: 'succeeded',
    data: { task_id: 'task-1', title: '操作系统实验', deadline: '2026-09-27' }, message: null }]
  const session = createAssistantSession({
    sendMessage: async () => ({ answer: '已保存一项。', action_results: actionResults }),
  })
  session.setInput('添加操作系统实验')

  assert.equal(await session.sendMessage(), true)
  assert.deepEqual(session.state.messages.at(-1).actionResults, actionResults)
})

test('state keeps conflict sets and only clears them after a confirmed user choice', async () => {
  const conflict = { conflict_id: 'c-1', member_ids: ['o-a', 'o-b'], snapshot_revision: 12, selected_id: null }
  let snapshot = { state_revision: 12, server_now: '2026-09-26T14:00:00Z',
    due_reminders: [], active_occurrences: [
      { occurrence_id: 'o-a', title: '课程 A', location: null },
      { occurrence_id: 'o-b', title: '课程 B', location: null },
    ], conflicts: [conflict] }
  const decisions = []
  const session = createAssistantSession({
    getState: async () => snapshot,
    decideConflict: async (request, key) => {
      decisions.push({ request, key })
      snapshot = { ...snapshot, active_occurrences: [snapshot.active_occurrences[0]], conflicts: [], state_revision: 13 }
      return { selected_id: request.selected_id, state_revision: 13,
        affected_occurrences: [{ occurrence_id: 'o-a' }, { occurrence_id: 'o-b', disposition: 'missed' }] }
    },
  })

  await session.refreshState()
  assert.deepEqual(session.state.conflicts, [conflict])
  assert.equal(await session.chooseConflict({ selectedId: 'o-a', memberIds: ['o-a', 'o-b'], snapshotRevision: 12 }), true)
  assert.equal(decisions.length, 1)
  assert.deepEqual(decisions[0].request.member_ids, ['o-a', 'o-b'])
  assert.equal(decisions[0].request.selected_id, 'o-a')
  assert.equal(decisions[0].request.snapshot_revision, 12)
  assert.ok(decisions[0].key)
  assert.deepEqual(session.state.conflicts, [])
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

test('reminder dismissal survives reload and retries only the still-current reminder with the same idempotency key', async () => {
  const values = new Map()
  const storage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
  const reminder = { reminder_id: 'rem-persist', occurrence_id: 'occ-persist', version: 2, schedule_revision: 7,
    acknowledged_at: null, event_title: '课程', location: '教室', start_at: '2026-09-26T10:00:00Z', minutes_until_start: 5 }
  const snapshot = { server_now: '2026-09-26T09:55:00Z', due_reminders: [reminder], active_occurrences: [], conflicts: [], state_revision: 1 }
  const keys = []
  const first = createAssistantSession({ acknowledgeReminder: async (_item, key) => { keys.push(key); throw new Error('offline') } }, storage)
  first.setReminder(reminder)
  await first.acknowledgeReminder()

  const second = createAssistantSession({
    getState: async () => snapshot,
    acknowledgeReminder: async (_item, key) => { keys.push(key) },
  }, storage)
  await second.refreshState()

  assert.equal(second.state.reminder, null)
  assert.equal(keys.length, 2)
  assert.equal(keys[0], keys[1])
})

test('a stale reminder pending ack is not replayed after the reminder leaves the server snapshot', async () => {
  const values = new Map()
  const storage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
  const reminder = { reminder_id: 'rem-stale', occurrence_id: 'occ-stale', version: 1, schedule_revision: 1,
    acknowledged_at: null, event_title: '课程', location: null, start_at: '2026-09-26T10:00:00Z', minutes_until_start: 5 }
  const first = createAssistantSession({ acknowledgeReminder: async () => { throw new Error('offline') } }, storage)
  first.setReminder(reminder)
  await first.acknowledgeReminder()
  let attempts = 0
  const second = createAssistantSession({ getState: async () => ({ server_now: '2026-09-26T10:01:00Z',
    due_reminders: [], active_occurrences: [], conflicts: [], state_revision: 2 }),
  acknowledgeReminder: async () => { attempts++ } }, storage)

  await second.refreshState()

  assert.equal(attempts, 0)
})
