import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { renderToString } from 'vue/server-renderer'

let server
let preview
test.before(async () => {
  server = await createServer({ configFile: new URL('../../vite.config.ts', import.meta.url).pathname, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  preview = await server.ssrLoadModule('/tests/assistant/reminder-preview.ts')
})
test.after(async () => { await server?.close() })

test('reminder shows event identity without numeric countdown in the scene', async () => {
  const html = await renderToString(preview.reminderPreview())
  assert.match(html, /软件工程课/)
  assert.match(html, /教学楼A/)
  assert.match(html, /即将开始/)
  assert.match(html, /知道了/)
  assert.doesNotMatch(html, /\b\d+\s*(分钟|分)\b/)
})
