import { reactive } from 'vue'
import type { components } from '../../../../contracts/backend-api.d.ts'

export type DraftResponse = components['schemas']['DraftResponse']
export type DraftCommitRequest = components['schemas']['DraftCommitRequest']
export type DraftCommitResponse = components['schemas']['DraftCommitResponse']

export interface AssistantReply {
  answer: string
  draft?: DraftResponse | null
}

export interface AssistantCommands {
  sendMessage?: (text: string, clientMessageId: string) => Promise<AssistantReply>
  confirmDraft?: (draftId: string, request: DraftCommitRequest, idempotencyKey: string) => Promise<DraftCommitResponse>
  acknowledgeReminder?: (reminder: Reminder, idempotencyKey: string) => Promise<void>
  getState?: () => Promise<components['schemas']['StateResponse']>
}

export type Reminder = components['schemas']['Reminder']

export interface AssistantMessage {
  role: 'user' | 'assistant'
  content: string
}

export function createAssistantSession(initialCommands: AssistantCommands = {}) {
  let commands = initialCommands
  let sendAttempt: { text: string; key: string } | null = null
  let commitAttempt: { identity: string; key: string } | null = null
  const state = reactive({
    open: false,
    input: '',
    messages: [] as AssistantMessage[],
    draft: null as DraftResponse | null,
    pending: null as 'sending' | 'confirming' | null,
    error: '',
    activeNotice: '',
    reminder: null as Reminder | null,
    notice: '',
  })
  const dismissedReminders = new Set<string>()

  function setCommands(next: AssistantCommands) { commands = next }
  function open() { state.open = true }
  function close() { state.open = false }
  function setInput(text: string) {
    if (text.trim() !== sendAttempt?.text) sendAttempt = null
    state.input = text
  }
  function setDraft(draft: DraftResponse | null) {
    if (`${draft?.draft_id}:${draft?.revision}:${draft?.confirmation_digest}` !== commitAttempt?.identity) commitAttempt = null
    state.draft = draft
  }
  function setActiveNotice(text: string) { state.activeNotice = text }
  function clearError() { state.error = '' }
  function setReminder(reminder: Reminder | null) {
    if (!reminder || reminder.acknowledged_at || dismissedReminders.has(reminder.reminder_id)) {
      if (state.reminder?.reminder_id === reminder?.reminder_id || !reminder) state.reminder = null
      return
    }
    state.reminder = reminder
  }

  async function acknowledgeReminder(): Promise<boolean> {
    const reminder = state.reminder
    if (!reminder) return false
    state.reminder = null
    dismissedReminders.add(reminder.reminder_id)
    try {
      if (!commands.acknowledgeReminder) throw new Error('service unavailable')
      await commands.acknowledgeReminder(reminder, globalThis.crypto.randomUUID())
      return true
    } catch {
      state.notice = '提醒已关闭，未能向服务端确认，稍后同步。'
      return true
    }
  }

  async function refreshState(): Promise<void> {
    if (!commands.getState) return
    try {
      const snapshot = await commands.getState()
      const candidates = snapshot.due_reminders.filter(item => !dismissedReminders.has(item.reminder_id))
      setReminder(candidates[0] ?? null)
      if (snapshot.active_occurrences.length > 0 && !state.open) {
        const active = snapshot.active_occurrences[0]
        state.activeNotice = `正在进行：${active.title}${active.location ? ` · ${active.location}` : ''}`
      }
    } catch {
      // Keep any visible reminder and active notice stable until the next sync.
    }
  }

  async function sendMessage(): Promise<boolean> {
    const text = state.input.trim()
    if (!text || state.pending) return false
    if (!commands.sendMessage) {
      state.error = '服务尚未连接，原文未发送。'
      return false
    }
    state.pending = 'sending'
    state.error = ''
    if (!sendAttempt || sendAttempt.text !== text) sendAttempt = { text, key: globalThis.crypto.randomUUID() }
    try {
      const reply = await commands.sendMessage(text, sendAttempt.key)
      state.messages.push({ role: 'user', content: text })
      if (reply.answer) state.messages.push({ role: 'assistant', content: reply.answer })
      if (reply.draft !== undefined) state.draft = reply.draft
      if (state.input.trim() === text) state.input = ''
      sendAttempt = null
      return true
    } catch {
      state.error = '发送结果未确认，原文仍在。请核对后重试。'
      return false
    } finally {
      state.pending = null
    }
  }

  async function confirmDraft(): Promise<boolean> {
    const draft = state.draft
    if (!draft || draft.status !== 'ready' || !draft.confirmation_digest ||
      draft.candidates.length === 0 || draft.candidates.some(item => item.missing_fields.length > 0) ||
      state.pending) return false
    if (!commands.confirmDraft) {
      state.error = '服务尚未连接，草稿未保存。'
      return false
    }
    const request: DraftCommitRequest = {
      revision: draft.revision,
      confirmed_candidate_ids: draft.candidates.map(item => item.candidate_id),
      confirmation_digest: draft.confirmation_digest,
      conflict_acceptance: null,
    }
    const identity = `${draft.draft_id}:${draft.revision}:${draft.confirmation_digest}`
    if (!commitAttempt || commitAttempt.identity !== identity) commitAttempt = { identity, key: globalThis.crypto.randomUUID() }
    state.pending = 'confirming'
    state.error = ''
    try {
      const response = await commands.confirmDraft(draft.draft_id, request, commitAttempt.key)
      if (response.draft_id !== draft.draft_id || response.resources.length !== draft.candidates.length) {
        throw new Error('commit response does not match draft')
      }
      if (state.draft?.draft_id === draft.draft_id && state.draft.revision === draft.revision) {
        state.draft = { ...draft, status: 'committed', revision: response.revision }
      }
      commitAttempt = null
      return true
    } catch {
      state.error = '保存结果未确认，草稿仍在。请核对后重试。'
      return false
    } finally {
      state.pending = null
    }
  }

  return { state, setCommands, open, close, setInput, setDraft, setActiveNotice, clearError, setReminder, refreshState,
    acknowledgeReminder, sendMessage, confirmDraft }
}

export const assistantSession = createAssistantSession()
