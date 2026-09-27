import test from 'node:test'
import assert from 'node:assert/strict'

import { createAssistantSession } from '../../src/assistant/sessionStore.ts'

const expiredDraft = {
  draft_id: 'draft-expired', revision: 5, status: 'expired', confirmation_digest: 'digest-expired',
  expires_at: '2026-09-26T15:00:00+08:00', reference_now: '2026-09-26T14:00:00+08:00',
  related_action_ids: [], questions: [],
  candidates: [{ candidate_id: 'candidate-1', title: '项目会', location: '会议室',
    start_at: '2026-09-26T15:00:00+08:00', end_at: '2026-09-26T16:00:00+08:00',
    timezone: 'Asia/Shanghai', recurrence: null, missing_fields: [] }],
}

const messages = [
  { message_id: 'u1', role: 'user', content: '明天下午开项目会', sequence: 1, status: 'completed',
    created_at: '2026-09-26T06:00:00Z', draft_refs: [], action_results: [] },
  { message_id: 'a1', role: 'assistant', content: '草稿已过期，请重新安排。', sequence: 2, status: 'completed',
    created_at: '2026-09-26T06:00:01Z', draft_refs: ['draft-expired'], action_results: [] },
]

function fakeStorage() {
  const values = new Map([['kairos.assistant-conversation.v1', 'conversation-1']])
  return {
    getItem(key) { return values.get(key) ?? null },
    setItem(key, value) { values.set(key, value) },
  }
}

for (const status of ['expired', 'committed']) {
  test(`a ${status} server draft restored after reload cannot be committed from stale conversation history`, async () => {
    const calls = []
    const session = createAssistantSession({
      loadConversation: async () => ({ items: messages, draft_refs: ['draft-expired'], next_cursor: null, revision: 2 }),
      getDraft: async draftId => { calls.push(['getDraft', draftId]); return { ...expiredDraft, status } },
      confirmDraft: async (...args) => { calls.push(['confirmDraft', ...args]); return {
        draft_id: 'draft-expired', revision: 6, resources: [{ resource_type: 'event', resource_id: 'event-1', version: 1 }],
      } },
      appendConversationTurn: async (_id, request) => {
        calls.push(['append', request.content])
        return { status: 'completed', revision: 4,
          user_message: { ...messages[0], message_id: request.client_message_id, content: request.content, sequence: 3 },
          answer: { ...messages[1], message_id: 'a2', content: '请重新说明有效时间。', sequence: 4 },
          draft_refs: [], tool_results: [] }
      },
    }, fakeStorage())

    assert.equal(await session.restoreConversation(), true)
    assert.equal(session.state.draft.status, status)
    assert.equal(await session.confirmDraft(), false)
    assert.equal(calls.some(([kind]) => kind === 'confirmDraft'), false)

    session.setInput('确认')
    assert.equal(await session.sendMessage(), true)
    assert.deepEqual(calls.filter(([kind]) => kind === 'append').map(([, content]) => content), ['确认'])
    assert.equal(calls.some(([kind]) => kind === 'confirmDraft'), false)
  })
}
