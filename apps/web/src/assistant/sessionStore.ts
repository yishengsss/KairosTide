import { markRaw, reactive } from 'vue'
import type { components } from '../../../../contracts/backend-api.d.ts'

export type DraftResponse = components['schemas']['DraftResponse']
export type DraftCommitRequest = components['schemas']['DraftCommitRequest']
export type DraftCommitResponse = components['schemas']['DraftCommitResponse']
export type ActiveOccurrence = components['schemas']['Occurrence']

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

function browserStorage(): KeyValueStorage | undefined {
  try { return globalThis.localStorage } catch { return undefined }
}

export type Reminder = components['schemas']['Reminder']

export interface AssistantMessage {
  role: 'user' | 'assistant'
  content: string
  hasImage?: boolean
  actionResults?: AssistantActionResult[]
}

export function createAssistantSession(initialCommands: AssistantCommands = {}, storage = browserStorage()) {
  let commands = initialCommands
  let sendAttempt: { text: string; image: File | null; key: string } | null = null
  let commitAttempt: { identity: string; key: string } | null = null
  const proposalAttempts = new Map<string, { identity: string; key: string }>()
  const state = reactive({
    open: false,
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
  function open() { state.open = true }
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
    if (!commands.sendMessage) {
      state.error = '服务尚未连接，原文未发送。'
      return false
    }
    state.pending = 'sending'
    state.error = ''
    if (!sendAttempt || sendAttempt.text !== text || sendAttempt.image !== image) {
      sendAttempt = { text, image, key: globalThis.crypto.randomUUID() }
    }
    try {
      const messages = [...state.messages, { role: 'user' as const, content: text }]
      const reply = await commands.sendMessage(text, sendAttempt.key, messages, image ?? undefined)
      state.messages.push({ role: 'user', content: text, hasImage: image !== null })
      if (reply.answer || reply.action_results?.length) state.messages.push({ role: 'assistant', content: reply.answer,
        actionResults: reply.action_results ?? [] })
      if (reply.draft !== undefined) setDraft(reply.draft)
      if (state.input.trim() === text) state.input = ''
      if (state.image === image && !reply.retain_image) state.image = null
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
    acknowledgeReminder, chooseConflict, excuseOccurrence, sendMessage, confirmDraft, confirmProposal }
}

export const assistantSession = createAssistantSession()
