import test from 'node:test'
import assert from 'node:assert/strict'
import { toAssistantChatMessages } from '../../src/assistant/chatPayload.ts'

test('chat API history contains only contract fields, not UI action cards', () => {
  const history = [
    { role: 'user', content: '列出我的规划' },
    { role: 'assistant', content: '目前没有已保存的柔性任务。', actionResults: [
      { action: 'query_flexible_tasks', status: 'succeeded', data: [] },
    ] },
  ]

  assert.deepEqual(toAssistantChatMessages(history), [
    { role: 'user', content: '列出我的规划' },
    { role: 'assistant', content: '目前没有已保存的柔性任务。' },
  ])
})
