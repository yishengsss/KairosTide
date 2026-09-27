import test from 'node:test'
import assert from 'node:assert/strict'

import { createAssistantSession } from '../../src/assistant/sessionStore.ts'

const readyDraft = {
  draft_id: 'draft-live', revision: 4, status: 'ready', confirmation_digest: 'digest-live',
  expires_at: '2026-09-27T15:00:00+08:00', reference_now: '2026-09-27T14:00:00+08:00',
  related_action_ids: [], questions: [],
  candidates: [{ candidate_id: 'candidate-1', title: '项目会', location: '会议室',
    start_at: '2026-09-27T15:00:00+08:00', end_at: '2026-09-27T16:00:00+08:00',
    timezone: 'Asia/Shanghai', recurrence: null, missing_fields: [] }],
}

function fakeStorage() {
  const values = new Map()
  return {
    values,
    getItem(key) { return values.get(key) ?? null },
    setItem(key, value) { values.set(key, value) },
  }
}

const userMessage = (id, content, sequence = 1, status = 'completed') => ({
  message_id: id, role: 'user', content, sequence, status,
  created_at: '2026-09-27T06:00:00Z', draft_refs: [], action_results: [],
})

const assistantMessage = (id, content, sequence = 2, draftRefs = [], actionResults = []) => ({
  message_id: id, role: 'assistant', content, sequence, status: 'completed',
  created_at: '2026-09-27T06:00:01Z', draft_refs: draftRefs, action_results: actionResults,
})

test('opens the stored conversation and restores transcript and current server draft', async () => {
  const storage = fakeStorage()
  storage.setItem('kairos.assistant-conversation.v1', 'conversation-1')
  const calls = []
  const session = createAssistantSession({
    loadConversation: async (id, cursor) => {
      calls.push(['load', id, cursor])
      return { items: [userMessage('m1', '明天下午开项目会'), assistantMessage('m2', '请检查并确认。', 2, ['draft-live'])],
        draft_refs: ['draft-live'], next_cursor: null, revision: 2 }
    },
    getDraft: async id => { calls.push(['draft', id]); return readyDraft },
  }, storage)

  assert.equal(await session.restoreConversation(), true)
  assert.deepEqual(calls, [['load', 'conversation-1', undefined], ['draft', 'draft-live']])
  assert.deepEqual(session.state.messages.map(message => [message.role, message.content]), [
    ['user', '明天下午开项目会'], ['assistant', '请检查并确认。'],
  ])
  assert.equal(session.state.draft.draft_id, 'draft-live')
  assert.equal(session.state.draftMessageIndex, 1)
})

test('a send issued as the panel opens waits for history and uses the restored sequence', async () => {
  const storage = fakeStorage()
  storage.setItem('kairos.assistant-conversation.v1', 'conversation-open-send')
  const requests = []
  const session = createAssistantSession({
    loadConversation: async () => ({ items: [userMessage('u1', '上一轮', 1), assistantMessage('a1', '收到。', 2)],
      draft_refs: [], next_cursor: null, revision: 2 }),
    appendConversationTurn: async (_id, request) => {
      requests.push(request)
      return { status: 'completed', revision: 4,
        user_message: userMessage('u2', request.content, 3),
        answer: assistantMessage('a2', '已记录。', 4), draft_refs: [], tool_results: [] }
    },
  }, storage)

  session.open()
  session.setInput('再加一项')
  assert.equal(await session.sendMessage(), true)
  assert.equal(requests[0].expected_sequence, 2)
  assert.deepEqual(session.state.messages.map(message => message.content), ['上一轮', '收到。', '再加一项', '已记录。'])
})

test('persists only conversation ID and never stores transcript, draft snapshot, or image bytes', async () => {
  const storage = fakeStorage()
  const file = new File(['private image bytes'], 'schedule.png', { type: 'image/png' })
  const session = createAssistantSession({
    createConversation: async () => ({ conversation_id: 'conversation-private', revision: 0 }),
    appendConversationTurn: async (_conversationId, request) => ({
      status: 'completed', revision: 2, user_message: userMessage(request.client_message_id, request.content),
      answer: assistantMessage('assistant-1', '已读出课表。', 2), draft_refs: [], tool_results: [],
    }),
  }, storage)
  session.setInput('识别这张图')
  session.setImage(file)

  assert.equal(await session.sendMessage(), true)
  assert.deepEqual([...storage.values.entries()], [['kairos.assistant-conversation.v1', 'conversation-private']])
  assert.equal([...storage.values.values()].some(value => value.includes('识别这张图') || value.includes('private image bytes')), false)
  assert.equal(session.state.messages[0].hasImage, true)
  assert.equal(session.state.image, null)
})

test('uncertain send preserves input and ID, loads the server before same-ID retry', async () => {
  const storage = fakeStorage()
  const calls = []
  let fail = true
  const session = createAssistantSession({
    createConversation: async () => ({ conversation_id: 'conversation-2', revision: 0 }),
    loadConversation: async id => {
      calls.push(['load', id])
      return { items: [], draft_refs: [], next_cursor: null, revision: 0 }
    },
    appendConversationTurn: async (id, request, key) => {
      calls.push(['append', id, request.client_message_id, request.content, key])
      if (fail) { fail = false; throw new Error('connection lost after send') }
      return { status: 'completed', revision: 2,
        user_message: userMessage(request.client_message_id, request.content),
        answer: assistantMessage('assistant-2', '会议时间已确认。'), draft_refs: [], tool_results: [] }
    },
  }, storage)
  session.setInput('十分钟后有一个会议持续20分钟')

  assert.equal(await session.sendMessage(), false)
  assert.equal(session.state.input, '十分钟后有一个会议持续20分钟')
  const firstId = calls[0]?.[2]
  assert.equal(await session.sendMessage(), true)
  assert.deepEqual(calls.filter(call => call[0] === 'load').map(call => call[1]), ['conversation-2'])
  assert.equal(calls[0][2], calls.at(-1)[2])
  assert.equal(calls.at(-1)[3], '十分钟后有一个会议持续20分钟')
  assert.equal(calls[0][4], calls.at(-1)[4])
  assert.ok(firstId)
  assert.equal(session.state.messages.at(-1).content, '会议时间已确认。')
  assert.equal(session.state.input, '')
})

test('uncertain send that already completed on the server restores its reply without replaying tools', async () => {
  const storage = fakeStorage()
  const calls = []
  const session = createAssistantSession({
    createConversation: async () => ({ conversation_id: 'conversation-committed', revision: 0 }),
    loadConversation: async () => ({ items: [userMessage('server-user', '创建一个会议', 1),
      assistantMessage('server-assistant', '会议草稿已生成。', 2, ['draft-live'])],
    draft_refs: ['draft-live'], next_cursor: null, revision: 2 }),
    appendConversationTurn: async (_id, request, key) => {
      calls.push([request, key])
      throw new Error('response lost')
    },
    getDraft: async () => readyDraft,
  }, storage)
  session.setInput('创建一个会议')

  assert.equal(await session.sendMessage(), false)
  assert.equal(await session.sendMessage(), true)
  assert.equal(calls.length, 1)
  assert.deepEqual(session.state.messages.map(message => message.content), ['创建一个会议', '会议草稿已生成。'])
  assert.equal(session.state.draft.draft_id, 'draft-live')
  assert.equal(session.state.input, '')
})

test('restores a pending turn by server-provided client ID and blocks unrelated input', async () => {
  const storage = fakeStorage()
  storage.setItem('kairos.assistant-conversation.v1', 'conversation-pending')
  const calls = []
  let pending = true
  const session = createAssistantSession({
    loadConversation: async id => {
      calls.push(['load', id])
      const message = userMessage('server-message-1', '十分钟后有会议', 1, pending ? 'pending' : 'completed')
      return { items: [message], draft_refs: [], next_cursor: null, revision: pending ? 1 : 2,
        pending_client_message_id: pending ? 'original-client-id' : null }
    },
    appendConversationTurn: async (id, request, key) => {
      calls.push(['append', id, request.client_message_id, request.expected_sequence, key])
      pending = false
      return { status: 'completed', revision: 2,
        user_message: userMessage('server-message-1', request.content, 1),
        answer: assistantMessage('assistant-pending', '会议安排已确认。', 2), draft_refs: [], tool_results: [] }
    },
  }, storage)

  assert.equal(await session.restoreConversation(), true)
  assert.deepEqual(session.state.pendingConversationTurn, {
    clientMessageId: 'original-client-id', content: '十分钟后有会议', expectedSequence: 0,
  })
  session.setInput('创建另一个日程')
  assert.equal(await session.sendMessage(), false)
  assert.equal(calls.some(call => call[0] === 'append'), false)
  assert.equal(await session.retryPendingTurn(), true)
  assert.equal(calls.at(-1)[2], 'original-client-id')
  assert.equal(calls.at(-1)[3], 0)
  assert.equal(calls.at(-1)[4], 'original-client-id')
  assert.equal(session.state.pendingConversationTurn, null)
})

test('typed draft confirmation commits directly then records server-confirmed receipt without AI', async () => {
  const storage = fakeStorage()
  storage.setItem('kairos.assistant-conversation.v1', 'conversation-confirm')
  let draftStatus = 'ready'
  let commitCalls = 0
  let modelCalls = 0
  const appended = []
  const session = createAssistantSession({
    loadConversation: async () => ({ items: [userMessage('u1', '明天下午开项目会'),
      assistantMessage('a1', '已生成日程草稿，请检查内容并确认。', 2, ['draft-live'])],
    draft_refs: ['draft-live'], next_cursor: null, revision: 2 }),
    getDraft: async () => ({ ...readyDraft, status: draftStatus }),
    confirmDraft: async () => {
      commitCalls++
      draftStatus = 'committed'
      return { draft_id: 'draft-live', revision: 5, resources: [{ resource_id: 'event-1', resource_type: 'event', version: 1 }] }
    },
    sendMessage: async () => { modelCalls++; throw new Error('confirmation must not invoke AI') },
    appendConversationTurn: async (id, request, key) => {
      appended.push({ id, request, key })
      return { status: 'completed', revision: 4,
        user_message: userMessage('u-confirm', request.content, 3),
        answer: assistantMessage('a-confirm', '已保存这份日程。', 4, ['draft-live'], [
          { action: 'confirm_rigid_event_draft', status: 'succeeded', data: { draft_id: 'draft-live' }, message: null },
        ]), draft_refs: ['draft-live'], tool_results: [] }
    },
  }, storage)
  assert.equal(await session.restoreConversation(), true)
  session.setInput('确认')

  assert.equal(await session.sendMessage(), true)
  assert.equal(commitCalls, 1)
  assert.equal(modelCalls, 0)
  assert.equal(appended.length, 1)
  assert.equal(appended[0].id, 'conversation-confirm')
  assert.equal(appended[0].request.content, '确认')
  assert.equal(appended[0].request.client_message_id, appended[0].key)
  assert.equal(appended[0].request.expected_sequence, 2)
  assert.deepEqual(session.state.messages.map(message => message.content), [
    '明天下午开项目会', '已生成日程草稿，请检查内容并确认。', '确认', '已保存这份日程。',
  ])
  assert.equal(session.state.draft.status, 'committed')
  assert.equal(session.state.input, '')
})

test('uncertain confirmation receipt retries same client ID after loading pending turn', async () => {
  const storage = fakeStorage()
  storage.setItem('kairos.assistant-conversation.v1', 'conversation-confirm-retry')
  let draftStatus = 'ready'
  let commitCalls = 0
  let modelCalls = 0
  let appendCount = 0
  const keys = []
  const session = createAssistantSession({
    loadConversation: async () => ({ items: [userMessage('u1', '创建一个项目会'),
      assistantMessage('a1', '已生成日程草稿，请检查内容并确认。', 2, ['draft-live']),
      ...(appendCount ? [userMessage('u-confirm', '确认', 3, 'pending')] : [])],
    draft_refs: ['draft-live'], next_cursor: null, revision: appendCount ? 3 : 2,
    pending_client_message_id: appendCount ? keys[0] : null }),
    getDraft: async () => ({ ...readyDraft, status: draftStatus }),
    confirmDraft: async () => {
      commitCalls++
      draftStatus = 'committed'
      return { draft_id: 'draft-live', revision: 5, resources: [{ resource_id: 'event-1', resource_type: 'event', version: 1 }] }
    },
    sendMessage: async () => { modelCalls++; throw new Error('confirmation must not invoke AI') },
    appendConversationTurn: async (_id, request, key) => {
      appendCount++
      keys.push(key)
      assert.equal(request.expected_sequence, 2)
      if (appendCount === 1) throw new Error('response lost after reservation')
      return { status: 'completed', revision: 4,
        user_message: userMessage('u-confirm', request.content, 3),
        answer: assistantMessage('a-confirm', '已保存这份日程。', 4, ['draft-live'], [
          { action: 'confirm_rigid_event_draft', status: 'succeeded', data: { draft_id: 'draft-live' }, message: null },
        ]), draft_refs: ['draft-live'], tool_results: [] }
    },
  }, storage)
  await session.restoreConversation()
  session.setInput('确认')

  assert.equal(await session.sendMessage(), false)
  assert.equal(session.state.input, '确认')
  assert.match(session.state.error, /日程已保存.*确认记录尚未同步/)
  assert.equal(commitCalls, 1)
  assert.equal(modelCalls, 0)
  assert.equal(await session.sendMessage(), true)
  assert.equal(appendCount, 2)
  assert.equal(keys[0], keys[1])
  assert.equal(session.state.messages.filter(message => message.content === '确认').length, 1)
  assert.equal(session.state.input, '')
})

test('a committed draft restored after reload records an unrecorded typed confirmation without recommit or AI', async () => {
  const storage = fakeStorage()
  storage.setItem('kairos.assistant-conversation.v1', 'conversation-confirm-reload')
  let commits = 0
  let models = 0
  let recorded = 0
  const session = createAssistantSession({
    loadConversation: async () => ({ items: [userMessage('u1', '创建会议'),
      assistantMessage('a1', '已生成日程草稿，请检查内容并确认。', 2, ['draft-live'])],
    draft_refs: ['draft-live'], next_cursor: null, revision: 2 }),
    getDraft: async () => ({ ...readyDraft, status: 'committed' }),
    confirmDraft: async () => { commits++; throw new Error('already committed; must not commit again') },
    sendMessage: async () => { models++; throw new Error('confirmation must not invoke AI') },
    appendConversationTurn: async (_id, request) => {
      recorded++
      return { status: 'completed', revision: 4,
        user_message: userMessage('u-confirm', request.content, 3),
        answer: assistantMessage('a-confirm', '已保存这份日程。', 4, ['draft-live'], [
          { action: 'confirm_rigid_event_draft', status: 'succeeded', data: { draft_id: 'draft-live' }, message: null },
        ]), draft_refs: ['draft-live'], tool_results: [] }
    },
  }, storage)
  await session.restoreConversation()
  session.setInput('确认')

  assert.equal(await session.sendMessage(), true)
  assert.equal(commits, 0)
  assert.equal(models, 0)
  assert.equal(recorded, 1)
  assert.equal(session.state.messages.filter(message => message.content === '确认').length, 1)
})

test('a committed draft with a recorded receipt does not capture later ordinary acknowledgments', async () => {
  const storage = fakeStorage()
  storage.setItem('kairos.assistant-conversation.v1', 'conversation-after-confirm')
  const appends = []
  const receipt = { action: 'confirm_rigid_event_draft', status: 'succeeded', data: { draft_id: 'draft-live' }, message: null }
  const session = createAssistantSession({
    loadConversation: async () => ({ items: [userMessage('u1', '创建会议'),
      assistantMessage('a1', '请核对并确认草稿。', 2, ['draft-live']),
      userMessage('u2', '确认', 3), assistantMessage('a2', '已保存这份日程。', 4, ['draft-live'], [receipt])],
    draft_refs: ['draft-live'], next_cursor: null, revision: 4 }),
    getDraft: async () => ({ ...readyDraft, status: 'committed' }),
    appendConversationTurn: async (_id, request) => {
      appends.push(request.content)
      return { status: 'completed', revision: 6,
        user_message: userMessage('u3', request.content, 5),
        answer: assistantMessage('a3', '我会按你的语境继续处理。', 6), draft_refs: [], tool_results: [] }
    },
  }, storage)
  await session.restoreConversation()
  session.setInput('好的')

  assert.equal(await session.sendMessage(), true)
  assert.deepEqual(appends, ['好的'])
  assert.equal(session.state.messages.at(-1).content, '我会按你的语境继续处理。')
})
