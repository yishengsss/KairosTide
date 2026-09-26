import { createApp, defineComponent, h } from 'vue'
import AssistantPanel from '../../src/assistant/AssistantPanel.vue'
import { assistantSession } from '../../src/assistant/sessionStore.ts'

const preview = defineComponent({
  setup() {
    const open = () => {
      assistantSession.setDraft({
        draft_id: 'preview-draft', revision: 1, status: 'ready', confirmation_digest: 'preview',
        expires_at: '2026-10-01T00:00:00+08:00', reference_now: '2026-09-26T10:00:00+08:00',
        questions: [], related_action_ids: [], candidates: ['高数课', '项目会', '预约'].map((title, index) => ({
          candidate_id: `preview-${index}`, title, location: '西安校区',
          start_at: '2026-09-29T14:00:00+08:00', end_at: '2026-09-29T15:00:00+08:00',
          timezone: 'Asia/Shanghai', recurrence: null, missing_fields: [],
        })),
      })
      assistantSession.setActiveNotice('高数课正在进行')
      assistantSession.open()
    }
    return () => h('main', [
      h('button', { id: 'open-assistant', onClick: open, style: 'position:fixed;bottom:2rem;right:2rem;padding:1rem' }, '问 Kairos'),
      h(AssistantPanel),
    ])
  },
})

createApp(preview).mount('#preview')
