import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { fileURLToPath } from 'node:url'

const vite = await createServer({
  root: fileURLToPath(new URL('../../', import.meta.url)),
  server: { middlewareMode: true, hmr: false }, appType: 'custom',
})

test.after(async () => { await vite.close() })

const candidate = id => ({
  candidate_id: id, title: `候选 ${id}`, location: `地点 ${id}`,
  start_at: '2026-09-29T14:00:00+08:00', end_at: '2026-09-29T15:00:00+08:00',
  timezone: 'Asia/Shanghai', recurrence: null, missing_fields: [],
})

test('draft review visibly retains all three candidates before confirmation', async () => {
  const { default: DraftReview } = await vite.ssrLoadModule('/src/assistant/DraftReview.vue')
  const html = await renderToString(createSSRApp(DraftReview, { draft: {
    draft_id: 'd1', revision: 1, status: 'ready', confirmation_digest: 'digest',
    expires_at: '2026-09-29T16:00:00+08:00', reference_now: '2026-09-26T10:00:00+08:00',
    questions: [], related_action_ids: [],
    candidates: [candidate('one'), candidate('two'), candidate('three')],
  }, pending: false }))
  for (const id of ['one', 'two', 'three']) {
    assert.match(html, new RegExp(`候选 ${id}`))
    assert.match(html, new RegExp(`地点 ${id}`))
  }
  assert.match(html, /未保存/)
  assert.match(html, /确认保存/)
})

test('clarification displays question and cannot expose enabled confirm', async () => {
  const { default: DraftReview } = await vite.ssrLoadModule('/src/assistant/DraftReview.vue')
  const html = await renderToString(createSSRApp(DraftReview, { draft: {
    draft_id: 'd1', revision: 1, status: 'needs_clarification', confirmation_digest: null,
    expires_at: '2026-09-29T16:00:00+08:00', reference_now: '2026-09-26T10:00:00+08:00',
    questions: ['具体是几点？'], related_action_ids: [],
    candidates: [{ ...candidate('one'), start_at: null, missing_fields: ['start_at'] }],
  }, pending: false }))
  assert.match(html, /具体是几点？/)
  assert.match(html, /尚需补充/)
  assert.doesNotMatch(html, /确认保存/)
})

test('open panel exposes conversation, unsent text, draft and a light event notice', async () => {
  const { default: AssistantPanel } = await vite.ssrLoadModule('/src/assistant/AssistantPanel.vue')
  const { createAssistantSession } = await vite.ssrLoadModule('/src/assistant/sessionStore.ts')
  const session = createAssistantSession()
  session.open()
  session.setInput('还没发送的原文')
  session.setActiveNotice('高数课正在进行')
  session.state.messages.push({ role: 'assistant', content: '已生成待确认草稿。' })
  session.setDraft({
    draft_id: 'd1', revision: 1, status: 'needs_clarification', confirmation_digest: null,
    expires_at: '2026-09-29T16:00:00+08:00', reference_now: '2026-09-26T10:00:00+08:00',
    questions: ['请补充地点'], related_action_ids: [],
    candidates: [{ candidate_id: 'c1', title: '高数课', location: null,
      start_at: '2026-09-29T14:00:00+08:00', end_at: '2026-09-29T15:00:00+08:00',
      timezone: 'Asia/Shanghai', recurrence: null, missing_fields: ['location'] }],
  })
  const html = await renderToString(createSSRApp(AssistantPanel, { session }))
  assert.match(html, /Kairos 助手/)
  assert.match(html, /还没发送的原文/)
  assert.match(html, /高数课正在进行/)
  assert.match(html, /请补充地点/)
  assert.match(html, /关闭助手/)
  assert.match(html, /回到场景/)
  assert.match(html, /新对话/)
})

test('draft table and confirm button appear inside the assistant reply that introduced the draft', async () => {
  const { default: AssistantPanel } = await vite.ssrLoadModule('/src/assistant/AssistantPanel.vue')
  const { createAssistantSession } = await vite.ssrLoadModule('/src/assistant/sessionStore.ts')
  const session = createAssistantSession()
  session.open()
  session.state.messages.push({ role: 'assistant', content: '请核对图片中识别出的课程。' })
  session.setDraft({
    draft_id: 'd-inline', revision: 1, status: 'ready', confirmation_digest: 'digest',
    expires_at: '2026-09-29T16:00:00+08:00', reference_now: '2026-09-26T10:00:00+08:00',
    questions: [], related_action_ids: [], candidates: [candidate('inline')],
  })
  const html = await renderToString(createSSRApp(AssistantPanel, { session }))
  const assistantMessageStart = html.indexOf('class="conversation-message assistant"')
  const assistantMessageEnd = html.indexOf('</li>', assistantMessageStart)
  const draftReview = html.indexOf('class="draft-review"')
  assert.ok(assistantMessageStart >= 0)
  assert.ok(draftReview > assistantMessageStart && draftReview < assistantMessageEnd,
    'draft review should be nested in the assistant message, not detached below the conversation')
  assert.match(html, /确认保存全部项目/)
})

test('a structured draft reference returned by the conversation API renders its confirmation card', async () => {
  const { default: AssistantPanel } = await vite.ssrLoadModule('/src/assistant/AssistantPanel.vue')
  const { createAssistantSession } = await vite.ssrLoadModule('/src/assistant/sessionStore.ts')
  const readyDraft = {
    draft_id: 'draft-from-turn', revision: 1, status: 'ready', confirmation_digest: 'digest',
    expires_at: '2026-09-29T16:00:00+08:00', reference_now: '2026-09-27T10:00:00+08:00',
    questions: [], related_action_ids: [], candidates: [candidate('meeting')],
  }
  const session = createAssistantSession({
    createConversation: async () => ({ conversation_id: 'conversation-1', revision: 0 }),
    appendConversationTurn: async (_id, request) => ({
      status: 'completed', revision: 2,
      user_message: { message_id: request.client_message_id, role: 'user', content: request.content,
        sequence: 1, status: 'completed', created_at: '2026-09-27T10:00:00Z', draft_refs: [], action_results: [] },
      answer: { message_id: 'assistant-1', role: 'assistant',
        content: '已生成刚性事件草稿，尚未保存。请检查内容并确认。', sequence: 2,
        status: 'completed', created_at: '2026-09-27T10:00:01Z', draft_refs: ['draft-from-turn'], action_results: [] },
      draft_refs: ['draft-from-turn'], tool_results: [],
    }),
    getDraft: async id => { assert.equal(id, 'draft-from-turn'); return readyDraft },
  })
  session.open()
  session.setInput('十分钟后有一个会议持续10分钟')

  assert.equal(await session.sendMessage(), true)
  assert.equal(session.state.draft.draft_id, 'draft-from-turn')
  assert.equal(session.state.draftMessageIndex, 1)
  const html = await renderToString(createSSRApp(AssistantPanel, { session }))
  assert.match(html, /未保存草稿/)
  assert.match(html, /确认保存全部项目/)
  assert.match(html, /候选 meeting/)
})

test('closed panel is inert and does not expose draft as page content', async () => {
  const { default: AssistantPanel } = await vite.ssrLoadModule('/src/assistant/AssistantPanel.vue')
  const { createAssistantSession } = await vite.ssrLoadModule('/src/assistant/sessionStore.ts')
  const session = createAssistantSession()
  session.setInput('隐藏文本')
  const html = await renderToString(createSSRApp(AssistantPanel, { session }))
  assert.match(html, /inert/)
  assert.match(html, /aria-hidden="true"/)
  assert.doesNotMatch(html, /隐藏文本/)
})


test('draft timestamps display calendar date and minutes in each candidate timezone', async () => {
  const { default: DraftReview } = await vite.ssrLoadModule('/src/assistant/DraftReview.vue')
  const html = await renderToString(createSSRApp(DraftReview, { draft: {
    draft_id: 'local-time', revision: 1, status: 'ready', confirmation_digest: 'digest',
    expires_at: '2026-09-28T00:00:00Z', reference_now: '2026-09-27T04:00:00Z',
    questions: [], related_action_ids: [],
    candidates: [{ ...candidate('shanghai'), start_at: '2026-09-27T04:37:35.590506Z', end_at: '2026-09-27T06:07:35.590506Z' },
      { ...candidate('tokyo'), timezone: 'Asia/Tokyo', start_at: '2026-09-27T16:00:00Z', end_at: null }],
  }, pending: false }))
  assert.match(html, /2026年9月27日 12:37/)
  assert.match(html, /2026年9月27日 14:07/)
  assert.match(html, /2026年9月28日 01:00/)
  assert.match(html, /待补充/)
  assert.doesNotMatch(html, /2026-09-27T04:37/)
})
