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

const assistantMessage = (id, content, sequence = 2, draftRefs = []) => ({
  message_id: id, role: 'assistant', content, sequence, status: 'completed',
  created_at: '2026-09-27T06:00:01Z', draft_refs: draftRefs, action_results: [],
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
