import test from 'node:test'
import assert from 'node:assert/strict'
import { parse, compileScript } from '@vue/compiler-sfc'
import { transformSync } from 'esbuild'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createRequire } from 'node:module'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

const appRoot = fileURLToPath(new URL('../../', import.meta.url))
const require = createRequire(new URL('../../src/assistant/Conversation.vue', import.meta.url))

async function loadConversation() {
  const filename = resolve(appRoot, 'src/assistant/Conversation.vue')
  const source = await readFile(filename, 'utf8')
  const { descriptor } = parse(source, { filename })
  const compiled = compileScript(descriptor, { id: 'conversation', inlineTemplate: true }).content
  const javascript = transformSync(compiled, { loader: 'ts', format: 'cjs' }).code
  const module = { exports: {} }
  new Function('require', 'module', 'exports', javascript)(require, module, module.exports)
  return module.exports.default
}

test('task receipts and query cards render only server-confirmed action data', async () => {
  const Conversation = await loadConversation()
  const html = await renderToString(createSSRApp(Conversation, { messages: [
    { role: 'user', content: '我还有什么任务？' },
    { role: 'assistant', content: '这是你已保存的事项。', actionResults: [{
      action: 'query_flexible_tasks', status: 'succeeded', data: [
        { task_id: 't1', title: '操作系统实验', deadline: '2026-09-27', deadline_precision: 'date' },
      ], message: null,
    }] },
  ] }))
  assert.match(html, /操作系统实验/)
  assert.match(html, /2026-09-27/)
  assert.doesNotMatch(html, /已添加新任务/)
})

test('failed or rejected task operations do not render successful receipts', async () => {
  const Conversation = await loadConversation()
  const html = await renderToString(createSSRApp(Conversation, { messages: [
    { role: 'user', content: '你好' },
    { role: 'assistant', content: '我没有执行该操作。', actionResults: [{
      action: 'delete_flexible_task', status: 'rejected', data: null, message: '需要明确任务标题。',
    }] },
  ] }))
  assert.match(html, /未执行/)
  assert.doesNotMatch(html, /删除成功/)
})

test('assistant Markdown renders common formatting while user text and raw HTML stay safe', async () => {
  const Conversation = await loadConversation()
  const html = await renderToString(createSSRApp(Conversation, { messages: [
    { role: 'user', content: '**这段用户输入保持原样**' },
    { role: 'assistant', content: '# 查询结果\n\n**重点**：\n- 第一项\n- `截止日期`\n\n> 这是补充说明。\n\n[帮助](https://example.com)\n\n<script>alert(1)</script>\n\n![追踪图](https://tracker.invalid/pixel)' },
  ] }))

  assert.match(html, /<h1>查询结果<\/h1>/)
  assert.match(html, /<strong>重点<\/strong>/)
  assert.match(html, /<ul>/)
  assert.match(html, /<code>截止日期<\/code>/)
  assert.match(html, /<blockquote>/)
  assert.match(html, /href="https:\/\/example\.com"[^>]*target="_blank"[^>]*rel="noopener noreferrer"/)
  assert.match(html, /\*\*这段用户输入保持原样\*\*/)
  assert.doesNotMatch(html, /<script>/)
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/)
  assert.doesNotMatch(html, /<img|tracker\.invalid|href="javascript:/)
})

test('pending occurrence and series proposals show exact target, scope, and changed values without a saved receipt', async () => {
  const Conversation = await loadConversation()
  const results = [
    { action: 'propose_rigid_event_change', status: 'succeeded', message: null, data: {
      proposal_id: 'p-occ', target_id: 'occ-27', scope: 'occurrence', revision: 1,
      action: 'update', summary: '修改这次课程', confirmation_digest: 'digest-occ', status: 'pending',
      target_title: '高数课', changes: { location: '教学楼 B', start_at: '2026-09-29T15:00:00+08:00', end_at: '2026-09-29T16:00:00+08:00' },
    } },
    { action: 'propose_rigid_event_change', status: 'succeeded', message: null, data: {
      proposal_id: 'p-series', target_id: 'event-9', scope: 'series', revision: 1,
      action: 'delete', summary: '删除整个系列', confirmation_digest: 'digest-series', status: 'pending',
      target_title: '英语课', changes: {},
    } },
  ]
  const html = await renderToString(createSSRApp(Conversation, { messages: [
    { role: 'assistant', content: '请核对。', actionResults: results },
  ], proposalCommits: {}, proposalPendingId: null, proposalErrors: {} }))
  for (const value of ['高数课', 'occ-27', '这次', '教学楼 B', '2026-09-29T15:00:00+08:00',
    '2026-09-29T16:00:00+08:00', '英语课', 'event-9', '整个系列', '确认修改', '确认删除']) {
    assert.ok(html.includes(value), `missing ${value}`)
  }
  assert.match(html, /待确认/)
  assert.doesNotMatch(html, /已处理/)
  assert.doesNotMatch(html, /已删除/)
})

test('proposal success appears only with a matching commit response; errors retain the confirm control', async () => {
  const Conversation = await loadConversation()
  const result = { action: 'propose_rigid_event_change', status: 'succeeded', message: null, data: {
    proposal_id: 'p1', target_id: 'occ-1', scope: 'occurrence', revision: 1,
    action: 'update', summary: '修改课程', confirmation_digest: 'digest', status: 'pending',
    target_title: '高数课', changes: { title: '数学课' },
  } }
  const messages = [{ role: 'assistant', content: '请核对。', actionResults: [result] }]
  const pending = await renderToString(createSSRApp(Conversation, {
    messages, proposalCommits: {}, proposalPendingId: null, proposalErrors: { p1: '尚未确认，请重试。' },
  }))
  assert.match(pending, /尚未确认，请重试/)
  assert.match(pending, /确认修改/)
  const committed = await renderToString(createSSRApp(Conversation, {
    messages, proposalCommits: { p1: { proposal_id: 'p1', target_id: 'occ-1', scope: 'occurrence', action: 'update', affected_ids: ['occ-1'], version: 2, status: 'committed' } },
    proposalPendingId: null, proposalErrors: {},
  }))
  assert.match(committed, /已确认修改/)
  assert.doesNotMatch(committed, /确认修改<\/button>/)
})
