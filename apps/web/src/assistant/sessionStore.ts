import { markRaw, reactive } from 'vue'
import type { components } from '../../../../contracts/backend-api.d.ts'

export type DraftResponse = components['schemas']['DraftResponse']
export type DraftCommitRequest = components['schemas']['DraftCommitRequest']
export type DraftCommitResponse = components['schemas']['DraftCommitResponse']
export type ActiveOccurrence = components['schemas']['Occurrence']
type Conversation = components['schemas']['Conversation']
type ConversationPage = components['schemas']['MessagePage']
type ConversationMessage = components['schemas']['ConversationMessage']
type MessageRequest = components['schemas']['MessageRequest']
type MessageResponse = components['schemas']['MessageResponse']

export interface AssistantReply {
  answer: string
  draft?: DraftResponse | null
  action_results?: components['schemas']['AssistantActionResult'][]
  retain_image?: boolean
}

export interface DraftConflictReview {
  acceptanceToken: string
  pairs: Array<[string, string]>
}

export type AssistantActionResult = components['schemas']['AssistantActionResult']

export interface RigidEventProposal {
  proposal_id: string
  target_id: string
  scope: 'occurrence' | 'series'
  revision: number
  action: 'update' | 'delete'
  summary: string
  confirmation_digest: string
  status: 'pending' | 'committed'
  target_title: string
  changes: Record<string, unknown>
}

export interface ProposalCommitResponse {
  proposal_id: string
  target_id: string
  scope: 'occurrence' | 'series'
  action: 'update' | 'delete'
  affected_ids: string[]
  version: number
  status: 'committed'
}

export function asRigidEventProposal(result: AssistantActionResult): RigidEventProposal | null {
  if (result.action !== 'propose_rigid_event_change' || result.status !== 'succeeded') return null
  const data = result.data
  if (typeof data !== 'object' || data === null || Array.isArray(data)) return null
  const item = data as Record<string, unknown>
  if (typeof item.proposal_id !== 'string' || !item.proposal_id ||
    typeof item.target_id !== 'string' || !item.target_id ||
    (item.scope !== 'occurrence' && item.scope !== 'series') ||
    !Number.isInteger(item.revision) || (item.revision as number) < 1 ||
    (item.action !== 'update' && item.action !== 'delete') ||
    typeof item.summary !== 'string' || typeof item.confirmation_digest !== 'string' || !item.confirmation_digest ||
    (item.status !== 'pending' && item.status !== 'committed') ||
    typeof item.target_title !== 'string' || !item.target_title ||
    typeof item.changes !== 'object' || item.changes === null || Array.isArray(item.changes)) return null
  return item as unknown as RigidEventProposal
}

export interface AssistantCommands {
  createConversation?: (idempotencyKey: string) => Promise<Conversation>
  appendConversationTurn?: (conversationId: string, request: MessageRequest, idempotencyKey: string) => Promise<MessageResponse>
  loadConversation?: (conversationId: string, cursor?: string) => Promise<ConversationPage>
  getDraft?: (draftId: string) => Promise<DraftResponse>
  sendMessage?: (text: string, clientMessageId: string, messages: AssistantMessage[], image?: File) => Promise<AssistantReply>
  confirmDraft?: (draftId: string, request: DraftCommitRequest, idempotencyKey: string) => Promise<DraftCommitResponse>
  commitProposal?: (proposalId: string, request: { revision: number; confirmation_digest: string; source_action_id: string },
    idempotencyKey: string) => Promise<ProposalCommitResponse>
  acknowledgeReminder?: (reminder: Reminder, idempotencyKey: string) => Promise<void>
  getState?: () => Promise<components['schemas']['StateResponse']>
  decideConflict?: (request: components['schemas']['ConflictDecisionRequest'], idempotencyKey: string) =>
    Promise<components['schemas']['ConflictDecisionResponse']>
  excuseOccurrence?: (occurrence: ActiveOccurrence, sourceActionId: string) =>
    Promise<components['schemas']['Occurrence']>
}

interface KeyValueStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

interface PendingReminderAck {
  reminder: Reminder
  idempotencyKey: string
}

const reminderStorageKey = 'kairos.reminder-ack.v1'
const conversationStorageKey = 'kairos.assistant-conversation.v1'

function browserStorage(): KeyValueStorage | undefined {
  try { return globalThis.localStorage } catch { return undefined }
}

function readConversationId(storage: KeyValueStorage | undefined): string | null {
  try {
    const id = storage?.getItem(conversationStorageKey)
    return typeof id === 'string' && id ? id : null
  } catch { return null }
}

async function imageAttachment(image: File): Promise<NonNullable<MessageRequest['image']>> {
  const mimeType = image.type
  if (mimeType !== 'image/jpeg' && mimeType !== 'image/png' && mimeType !== 'image/webp') {
    throw new Error('unsupported image type')
  }
  const bytes = new Uint8Array(await image.arrayBuffer())
  let binary = ''
  const chunkSize = 0x8000
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize))
  }
  return { mime_type: mimeType, data_base64: btoa(binary) }
}

export type Reminder = components['schemas']['Reminder']

export interface AssistantMessage {
  role: 'user' | 'assistant'
  content: string
  sequence?: number
  status?: 'pending' | 'completed'
  hasImage?: boolean
  actionResults?: AssistantActionResult[]
}

export function createAssistantSession(initialCommands: AssistantCommands = {}, storage = browserStorage()) {
  let commands = initialCommands
  const initialConversationId = readConversationId(storage)
  let sendAttempt: { text: string; image: File | null; key: string; expectedSequence: number; uncertain?: boolean; confirmationReceipt?: boolean } | null = null
  let createAttempt: string | null = null
  let restoreAttempt: Promise<boolean> | null = null
  let commitAttempt: { identity: string; key: string } | null = null
  const proposalAttempts = new Map<string, { identity: string; key: string }>()
  const state = reactive({
    open: false,
    conversationId: initialConversationId,
    conversationRevision: 0,
    conversationLoaded: !initialConversationId,
    conversationRestoring: false,
    pendingConversationTurn: null as { clientMessageId: string; content: string; expectedSequence: number } | null,
    input: '',
    image: null as File | null,
    imageError: '',
    messages: [] as AssistantMessage[],
    draft: null as DraftResponse | null,
    draftMessageIndex: null as number | null,
    draftConflict: null as DraftConflictReview | null,
    pending: null as 'sending' | 'confirming' | null,
    proposalPendingId: null as string | null,
    proposalErrors: {} as Record<string, string>,
    proposalCommits: {} as Record<string, ProposalCommitResponse>,
    error: '',
    activeNotice: '',
    activeOccurrences: [] as ActiveOccurrence[],
    conflicts: [] as components['schemas']['Conflict'][],
    stateRevision: 0,
    conflictPending: false,
    exceptionPendingId: null as string | null,
    nextTransitionAt: null as string | null,
    reminder: null as Reminder | null,
    notice: '',
  })
  const dismissedReminders = new Set<string>()
  const pendingReminderAcks = new Map<string, PendingReminderAck>()
  try {
    const raw = storage?.getItem(reminderStorageKey)
    if (raw) {
      const saved: unknown = JSON.parse(raw)
      if (typeof saved === 'object' && saved !== null) {
        const data = saved as { dismissed?: unknown; pending?: unknown }
        if (Array.isArray(data.dismissed)) {
          for (const id of data.dismissed) if (typeof id === 'string') dismissedReminders.add(id)
        }
        if (Array.isArray(data.pending)) {
          for (const entry of data.pending) {
            if (typeof entry !== 'object' || entry === null) continue
            const candidate = entry as PendingReminderAck
            if (typeof candidate.idempotencyKey === 'string' && candidate.reminder?.reminder_id &&
              Number.isInteger(candidate.reminder.schedule_revision) && Number.isInteger(candidate.reminder.version)) {
              pendingReminderAcks.set(candidate.reminder.reminder_id, candidate)
              dismissedReminders.add(candidate.reminder.reminder_id)
            }
          }
        }
      }
    }
  } catch { /* A corrupt local cache must never block scene or event state. */ }
  function persistReminderState() {
    try {
      storage?.setItem(reminderStorageKey, JSON.stringify({ dismissed: [...dismissedReminders], pending: [...pendingReminderAcks.values()] }))
    } catch { /* Keep the current page responsive when browser storage is unavailable. */ }
  }
  let conflictAttempt: { identity: string; key: string } | null = null
  let exceptionAttempt: { occurrenceId: string; key: string } | null = null

  function setCommands(next: AssistantCommands) { commands = next }
  function open() { state.open = true; if (state.conversationId) void restoreConversation() }
  function close() { state.open = false }
  function setInput(text: string) {
    if (text.trim() !== sendAttempt?.text) sendAttempt = null
    state.input = text
  }
  function setImage(image: File | null) {
    if (image !== sendAttempt?.image) sendAttempt = null
    state.image = image ? markRaw(image) : null
    state.imageError = ''
  }
  function setDraft(draft: DraftResponse | null) {
    if (`${draft?.draft_id}:${draft?.revision}:${draft?.confirmation_digest}` !== commitAttempt?.identity) {
      commitAttempt = null
      state.draftConflict = null
    }
    state.draft = draft
    state.draftMessageIndex = draft
      ? state.messages.map(message => message.role).lastIndexOf('assistant')
      : null
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

  function storeConversationId(id: string) {
    state.conversationId = id
    try { storage?.setItem(conversationStorageKey, id) }
    catch { /* The conversation remains usable for this page even if storage is unavailable. */ }
  }

  function restoreMessage(message: ConversationMessage): AssistantMessage {
    return {
      role: message.role,
      content: message.content,
      sequence: message.sequence,
      status: message.status,
      actionResults: (message.action_results ?? []) as AssistantActionResult[],
    }
  }

  async function readAllConversationPages(conversationId: string): Promise<{
    items: ConversationMessage[]; revision: number; pendingClientMessageId: string | null
  }> {
    if (!commands.loadConversation) throw new Error('conversation read unavailable')
    const items: ConversationMessage[] = []
    let cursor: string | null | undefined
    let revision = 0
    let pendingClientMessageId: string | null = null
    do {
      const page = await commands.loadConversation(conversationId, cursor ?? undefined)
      items.push(...page.items)
      revision = page.revision
      pendingClientMessageId = page.pending_client_message_id ?? pendingClientMessageId
      cursor = page.next_cursor
    } while (cursor)
    return { items, revision, pendingClientMessageId }
  }

  async function restoreLatestDraft(items: ConversationMessage[]): Promise<void> {
    state.draft = null
    state.draftMessageIndex = null
    const latestDraftId = [...items].reverse().flatMap(item => item.draft_refs ?? []).at(0)
    if (!latestDraftId || !commands.getDraft) return
    try {
      const currentDraft = await commands.getDraft(latestDraftId)
      const sourceIndex = [...items].findLastIndex(item => item.role === 'assistant' && item.draft_refs?.includes(latestDraftId))
      state.draft = currentDraft
      state.draftMessageIndex = sourceIndex >= 0 ? sourceIndex : null
    } catch {
      // A missing, expired or inaccessible draft is not restored from stale message data.
    }
  }

  async function restoreConversation(): Promise<boolean> {
    if (!state.conversationId) return true
    if (restoreAttempt) return restoreAttempt
    if (!commands.loadConversation) return false
    state.conversationRestoring = true
    state.error = ''
    restoreAttempt = (async () => {
      try {
        const conversationId = state.conversationId
        if (!conversationId) return true
        const { items, revision, pendingClientMessageId } = await readAllConversationPages(conversationId)
        state.messages = items.map(restoreMessage)
        state.conversationRevision = revision
        const pendingUser = items.find(item => item.role === 'user' && item.status === 'pending')
        state.pendingConversationTurn = pendingUser && pendingClientMessageId
          ? { clientMessageId: pendingClientMessageId, content: pendingUser.content, expectedSequence: pendingUser.sequence - 1 }
          : null
        state.draftConflict = null
        await restoreLatestDraft(items)
        state.conversationLoaded = true
        return true
      } catch {
        state.error = '无法恢复这段对话，请检查连接后重试。'
        return false
      } finally {
        state.conversationRestoring = false
        restoreAttempt = null
      }
    })()
    return restoreAttempt
  }

  async function createConversationIfNeeded(): Promise<boolean> {
    if (state.conversationId) return true
    if (!commands.createConversation) return false
    if (!createAttempt) createAttempt = globalThis.crypto.randomUUID()
    const conversation = await commands.createConversation(createAttempt)
    if (!conversation.conversation_id) throw new Error('Invalid conversation response')
    storeConversationId(conversation.conversation_id)
    state.conversationRevision = conversation.revision
    state.conversationLoaded = true
    createAttempt = null
    return true
  }

  async function acknowledgeReminder(): Promise<boolean> {
    const reminder = state.reminder
    if (!reminder) return false
    state.reminder = null
    dismissedReminders.add(reminder.reminder_id)
    const pending = pendingReminderAcks.get(reminder.reminder_id) ?? {
      reminder, idempotencyKey: globalThis.crypto.randomUUID(),
    }
    pendingReminderAcks.set(reminder.reminder_id, pending)
    persistReminderState()
    try {
      if (!commands.acknowledgeReminder) throw new Error('service unavailable')
      await commands.acknowledgeReminder(pending.reminder, pending.idempotencyKey)
      pendingReminderAcks.delete(reminder.reminder_id)
      persistReminderState()
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
      const currentReminders = new Map(snapshot.due_reminders.map(item => [item.reminder_id, item]))
      for (const [id, pending] of pendingReminderAcks) {
        const current = currentReminders.get(id)
        if (!current || current.schedule_revision !== pending.reminder.schedule_revision || current.version !== pending.reminder.version) {
          pendingReminderAcks.delete(id)
          continue
        }
        if (!commands.acknowledgeReminder) continue
        try {
          await commands.acknowledgeReminder(pending.reminder, pending.idempotencyKey)
          pendingReminderAcks.delete(id)
        } catch {
          state.notice = '提醒已关闭，未能向服务端确认，稍后同步。'
        }
      }
      persistReminderState()
      const candidates = snapshot.due_reminders.filter(item => !dismissedReminders.has(item.reminder_id))
      setReminder(candidates[0] ?? null)
      state.activeOccurrences = snapshot.active_occurrences
      state.conflicts = snapshot.conflicts ?? []
      state.stateRevision = snapshot.state_revision ?? 0
      const serverNow = Date.parse(snapshot.server_now)
      const now = Number.isFinite(serverNow) ? serverNow : Date.now()
      const boundaries = [
        Date.parse(snapshot.next_transition_at ?? ''),
        ...snapshot.active_occurrences.map(item => Date.parse(item.end_at)),
        ...candidates.map(item => Date.parse(item.start_at)),
      ].filter(at => Number.isFinite(at) && at > now)
      const retainedBoundary = state.nextTransitionAt ? Date.parse(state.nextTransitionAt) : NaN
      if (Number.isFinite(retainedBoundary) && retainedBoundary > now) boundaries.push(retainedBoundary)
      state.nextTransitionAt = boundaries.length ? new Date(Math.min(...boundaries)).toISOString() : null
      const active = snapshot.active_occurrences[0]
      state.activeNotice = active
        ? `正在进行：${active.title}${active.location ? ` · ${active.location}` : ''}`
        : ''
    } catch {
      // Keep any visible reminder and active notice stable until the next sync.
    }
  }

  async function chooseConflict(choice: { selectedId: string; memberIds: string[]; snapshotRevision: number }): Promise<boolean> {
    const memberIds = [...new Set(choice.memberIds)].sort()
    const current = state.conflicts.find(item => item.snapshot_revision === choice.snapshotRevision &&
      [...item.member_ids].sort().join('|') === memberIds.join('|'))
    if (!current || !memberIds.includes(choice.selectedId) || state.conflictPending) return false
    if (!commands.decideConflict) {
      state.notice = '事件状态暂时无法同步，未提交选择。'
      return false
    }
    const identity = `${choice.snapshotRevision}:${memberIds.join(',')}:${choice.selectedId}`
    if (!conflictAttempt || conflictAttempt.identity !== identity) {
      conflictAttempt = { identity, key: globalThis.crypto.randomUUID() }
    }
    state.conflictPending = true
    state.notice = ''
    try {
      const response = await commands.decideConflict({
        member_ids: memberIds, selected_id: choice.selectedId,
        snapshot_revision: choice.snapshotRevision, source_action_id: conflictAttempt.key,
      }, conflictAttempt.key)
      const affectedIds = response.affected_occurrences.map(item => item.occurrence_id).sort()
      if (response.selected_id !== choice.selectedId || affectedIds.join('|') !== memberIds.join('|')) {
        throw new Error('The conflict decision response did not match the request.')
      }
      conflictAttempt = null
      await refreshState()
      return true
    } catch {
      state.notice = '冲突状态可能已变化，请刷新后重新选择。'
      return false
    } finally {
      state.conflictPending = false
    }
  }

  async function excuseOccurrence(occurrenceId: string): Promise<boolean> {
    const occurrence = state.activeOccurrences.find(item => item.occurrence_id === occurrenceId)
    if (!occurrence || state.exceptionPendingId) return false
    if (!commands.excuseOccurrence) {
      state.notice = '事件服务暂时不可用，未记录本次例外。'
      return false
    }
    if (exceptionAttempt?.occurrenceId !== occurrenceId) {
      exceptionAttempt = { occurrenceId, key: globalThis.crypto.randomUUID() }
    }
    state.exceptionPendingId = occurrenceId
    state.notice = ''
    try {
      const result = await commands.excuseOccurrence(occurrence, exceptionAttempt.key)
      if (result.occurrence_id !== occurrenceId || result.disposition !== 'excused') {
        throw new Error('Exception response did not match the current occurrence.')
      }
      exceptionAttempt = null
      state.notice = `已记录“${occurrence.title}”本次请假。`
      await refreshState()
      return true
    } catch {
      state.notice = '本次例外尚未确认，请检查事件状态后重试。'
      return false
    } finally {
      state.exceptionPendingId = null
    }
  }

  async function sendMessage(): Promise<boolean> {
    const image = state.image
    const text = state.input.trim() || (image ? '请识别图片中的信息并告诉我能看出什么。' : '')
    if ((!text && !image) || state.pending) return false
    if (commands.appendConversationTurn && state.conversationId &&
      (state.conversationRestoring || !state.conversationLoaded) && !await restoreConversation()) {
      state.error = '无法恢复当前会话，原文仍在。请检查连接后重试。'
      return false
    }
    if (state.pendingConversationTurn && text !== state.pendingConversationTurn.content) {
      state.error = '上一条消息仍待服务端处理。请先重新发送原文，恢复该轮后再继续。'
      return false
    }
    const lastMessage = state.messages[state.messages.length - 1]
    const isDraftConfirmationText = !image && /^(?:确认|确认保存|确认保存全部项目|保存日程|保存)[。！!\s]*$/.test(text)
    const confirmsDisplayedDraft = isDraftConfirmationText &&
      state.draft?.status === 'ready' && state.draftMessageIndex === state.messages.length - 1 &&
      lastMessage?.role === 'assistant' && /确认|核对/.test(lastMessage.content)
    const confirmsCommittedDraft = isDraftConfirmationText && state.draft?.status === 'committed' &&
      state.draftMessageIndex === state.messages.length - 1 && lastMessage?.role === 'assistant' &&
      !lastMessage.actionResults?.some(result => result.action === 'confirm_rigid_event_draft')
    if (commands.appendConversationTurn && state.conversationId &&
      (sendAttempt?.confirmationReceipt && sendAttempt.text === text || confirmsCommittedDraft)) {
      if (!state.conversationLoaded && !await restoreConversation()) {
        state.error = '日程已保存，但无法恢复确认记录状态。原文仍在。'
        return false
      }
      if (!sendAttempt || sendAttempt.text !== text || !sendAttempt.confirmationReceipt) {
        sendAttempt = { text, image: null, key: globalThis.crypto.randomUUID(),
          expectedSequence: state.conversationRevision, confirmationReceipt: true }
      }
      return recordConfirmationReceipt(text)
    }
    if (confirmsDisplayedDraft) {
      state.error = ''
      if (commands.appendConversationTurn && state.conversationId &&
        (!state.conversationLoaded && !await restoreConversation())) {
        state.error = '无法核对当前会话，日程尚未保存。请检查连接后重试。'
        return false
      }
      const saved = await confirmDraft()
      if (!saved) return false
      if (commands.appendConversationTurn && state.conversationId) {
        sendAttempt = { text, image: null, key: globalThis.crypto.randomUUID(), expectedSequence: state.conversationRevision,
          confirmationReceipt: true }
        return recordConfirmationReceipt(text)
      }
      // Preserve compatibility for isolated sessions without a conversation API.
      state.messages.push({ role: 'user', content: text })
      state.messages.push({ role: 'assistant', content: '已保存这份日程。' })
      if (state.input.trim() === text) state.input = ''
      sendAttempt = null
      return true
    }
    if (!commands.sendMessage && !commands.appendConversationTurn) {
      state.error = '服务尚未连接，原文未发送。'
      return false
    }
    state.pending = 'sending'
    state.error = ''
    let retainImage = false
    try {
      if (commands.appendConversationTurn) {
        if (!await createConversationIfNeeded()) throw new Error('conversation service unavailable')
        if (state.conversationRestoring || !state.conversationLoaded) {
          if (!await restoreConversation()) throw new Error('conversation restore failed')
        }
        if (!sendAttempt || sendAttempt.text !== text || sendAttempt.image !== image) {
          sendAttempt = state.pendingConversationTurn
            ? { text, image, key: state.pendingConversationTurn.clientMessageId,
              expectedSequence: state.pendingConversationTurn.expectedSequence, uncertain: true }
            : { text, image, key: globalThis.crypto.randomUUID(), expectedSequence: state.conversationRevision }
        }
        if (sendAttempt.uncertain && commands.loadConversation) {
          const alreadyCompleted = await syncBeforeRetry(sendAttempt)
          if (alreadyCompleted) {
            if (state.input.trim() === text) state.input = ''
            if (state.image === image) state.image = null
            sendAttempt = null
            return true
          }
        }
        const request: MessageRequest = {
          client_message_id: sendAttempt.key, content: text, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
          expected_sequence: sendAttempt.expectedSequence,
          ...(image ? { image: await imageAttachment(image) } : {}),
        }
        const response = await commands.appendConversationTurn(state.conversationId!, request, sendAttempt.key)
        state.conversationRevision = response.revision
        state.pendingConversationTurn = null
        await mergeTurnResponse(response, image !== null)
      } else {
        if (!sendAttempt || sendAttempt.text !== text || sendAttempt.image !== image) {
          sendAttempt = { text, image, key: globalThis.crypto.randomUUID(), expectedSequence: 0 }
        }
        const messages = [...state.messages, { role: 'user' as const, content: text }]
        const reply = await commands.sendMessage!(text, sendAttempt.key, messages, image ?? undefined)
        retainImage = reply.retain_image ?? false
        state.messages.push({ role: 'user', content: text, hasImage: image !== null })
        if (reply.answer || reply.action_results?.length) state.messages.push({ role: 'assistant', content: reply.answer,
          actionResults: reply.action_results ?? [] })
        if (reply.draft !== undefined) setDraft(reply.draft)
      }
      if (state.input.trim() === text) state.input = ''
      if (state.image === image && !retainImage) state.image = null
      sendAttempt = null
      return true
    } catch {
      if (sendAttempt) sendAttempt.uncertain = true
      state.error = sendAttempt?.confirmationReceipt
        ? '日程已保存，但确认记录尚未同步。原文仍在；重试前会先核对会话记录。'
        : '发送结果未确认，原文仍在。重试前会先核对会话记录。'
      return false
    } finally {
      state.pending = null
    }
  }

  async function recordConfirmationReceipt(text: string): Promise<boolean> {
    const attempt = sendAttempt
    if (!attempt || !attempt.confirmationReceipt || !commands.appendConversationTurn || !state.conversationId) return false
    state.pending = 'sending'
    state.error = ''
    try {
      if (attempt.uncertain) {
        const alreadyRecorded = await syncBeforeRetry(attempt)
        if (alreadyRecorded) {
          if (state.input.trim() === text) state.input = ''
          sendAttempt = null
          return true
        }
      }
      const request: MessageRequest = {
        client_message_id: attempt.key,
        content: text,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
        expected_sequence: attempt.expectedSequence,
      }
      const response = await commands.appendConversationTurn(state.conversationId, request, attempt.key)
      state.conversationRevision = response.revision
      state.pendingConversationTurn = null
      await mergeTurnResponse(response, false)
      if (state.input.trim() === text) state.input = ''
      sendAttempt = null
      return true
    } catch {
      attempt.uncertain = true
      state.error = '日程已保存，但确认记录尚未同步。原文仍在；重试前会先核对会话记录。'
      return false
    } finally {
      state.pending = null
    }
  }

  async function syncBeforeRetry(attempt: NonNullable<typeof sendAttempt>): Promise<boolean> {
    const conversationId = state.conversationId
    if (!conversationId || !commands.loadConversation) return false
    const { items, revision, pendingClientMessageId } = await readAllConversationPages(conversationId)
    state.messages = items.map(restoreMessage)
    state.conversationRevision = revision
    const pendingUser = items.find(item => item.role === 'user' && item.status === 'pending')
    state.pendingConversationTurn = pendingUser && pendingClientMessageId
      ? { clientMessageId: pendingClientMessageId, content: pendingUser.content, expectedSequence: pendingUser.sequence - 1 }
      : null
    await restoreLatestDraft(items)
    if (state.pendingConversationTurn && state.pendingConversationTurn.clientMessageId !== attempt.key) {
      throw new Error('A different conversation turn is pending.')
    }
    const user = items.find(item => item.sequence === attempt.expectedSequence + 1 &&
      item.role === 'user' && item.content === attempt.text)
    if (user?.status === 'pending') return false
    if (user && items.some(item => item.sequence === user.sequence + 1 && item.role === 'assistant')) {
      return true
    }
    if (revision !== attempt.expectedSequence) {
      attempt.expectedSequence = revision
      state.error = '会话已更新，请确认原文后重试。'
    }
    return false
  }

  async function retryPendingTurn(): Promise<boolean> {
    const pending = state.pendingConversationTurn
    if (!pending || state.pending) return false
    state.input = pending.content
    return sendMessage()
  }

  async function mergeTurnResponse(response: MessageResponse, hasImage: boolean) {
    const user = response.user_message
    if (user) {
      const existingIndex = state.messages.findIndex(item => item.sequence === user.sequence && item.role === user.role)
      if (existingIndex >= 0) state.messages[existingIndex] = { ...restoreMessage(user), hasImage: state.messages[existingIndex].hasImage || hasImage }
      else state.messages.push({ ...restoreMessage(user), hasImage })
    }
    if (response.answer && !state.messages.some(item => item.role === 'assistant' &&
      item.content === response.answer?.content && item.sequence === response.answer?.sequence)) {
      state.messages.push(restoreMessage(response.answer))
    }
    const draftId = response.draft_refs.at(-1)
    if (draftId && commands.getDraft) {
      try {
        const draft = await commands.getDraft(draftId)
        state.draft = draft
        state.draftMessageIndex = response.answer ? state.messages.findIndex(item =>
          item.role === 'assistant' && item.content === response.answer?.content) : null
      } catch { setDraft(null) }
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
      conflict_acceptance: state.draftConflict?.acceptanceToken ?? null,
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
      state.draftConflict = null
      return true
    } catch (error) {
      const conflict = error as Error & { conflictAcceptance?: unknown; conflictPairs?: unknown }
      if (typeof conflict.conflictAcceptance === 'string' && Array.isArray(conflict.conflictPairs)) {
        const pairs = conflict.conflictPairs.filter((pair): pair is [string, string] =>
          Array.isArray(pair) && pair.length === 2 && pair.every(item => typeof item === 'string'))
        state.draftConflict = { acceptanceToken: conflict.conflictAcceptance, pairs }
        state.error = '发现日程时间冲突。请检查下方冲突信息；再次点击确认，才会接受冲突并保存。'
        return false
      }
      state.error = '保存结果未确认，草稿仍在。请核对后重试。'
      return false
    } finally {
      state.pending = null
    }
  }

  async function confirmProposal(proposalId: string): Promise<boolean> {
    const proposal = state.messages.flatMap(message => message.actionResults ?? [])
      .map(asRigidEventProposal).find(item => item?.proposal_id === proposalId)
    if (!proposal || proposal.status !== 'pending' || state.proposalPendingId || state.proposalCommits[proposalId]) return false
    if (!commands.commitProposal) {
      state.proposalErrors[proposalId] = '服务尚未连接，提案尚未确认。'
      return false
    }
    const identity = `${proposal.proposal_id}:${proposal.revision}:${proposal.confirmation_digest}`
    let attempt = proposalAttempts.get(proposalId)
    if (!attempt || attempt.identity !== identity) {
      attempt = { identity, key: globalThis.crypto.randomUUID() }
      proposalAttempts.set(proposalId, attempt)
    }
    state.proposalPendingId = proposalId
    delete state.proposalErrors[proposalId]
    try {
      const response = await commands.commitProposal(proposalId, {
        revision: proposal.revision, confirmation_digest: proposal.confirmation_digest,
        source_action_id: attempt.key,
      }, attempt.key)
      if (response.status !== 'committed' || response.proposal_id !== proposalId ||
        response.target_id !== proposal.target_id || response.scope !== proposal.scope ||
        response.action !== proposal.action) throw new Error('Commit response did not match proposal')
      state.proposalCommits[proposalId] = response
      proposalAttempts.delete(proposalId)
      await refreshState()
      return true
    } catch {
      state.proposalErrors[proposalId] = '变更尚未确认，请核对事件状态后重试。'
      return false
    } finally {
      state.proposalPendingId = null
    }
  }

  return { state, setCommands, open, close, setInput, setImage, setDraft, setActiveNotice, clearError, setReminder, refreshState,
    acknowledgeReminder, chooseConflict, excuseOccurrence, sendMessage, retryPendingTurn, confirmDraft, confirmProposal, restoreConversation }
}

export const assistantSession = createAssistantSession()
