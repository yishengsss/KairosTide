import { createSSRApp } from 'vue'
import ReminderLayer from '../../src/presentation/ReminderLayer.vue'

export function reminderPreview() {
  return createSSRApp(ReminderLayer, { reminder: { reminder_id: 'fixture', occurrence_id: 'occ', version: 1,
    schedule_revision: 1, acknowledged_at: null, event_title: '软件工程课', location: '教学楼A', minutes_until_start: 1 },
    assistantOpen: false, pending: false })
}
