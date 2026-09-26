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
