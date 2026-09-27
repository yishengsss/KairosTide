<script setup lang="ts">
import { asRigidEventProposal } from './sessionStore.ts'
import type { AssistantMessage, AssistantActionResult, ProposalCommitResponse } from './sessionStore.ts'
import { renderAssistantMarkdown } from './markdown.ts'

withDefaults(defineProps<{
  messages: AssistantMessage[]
  proposalCommits?: Record<string, ProposalCommitResponse>
  proposalPendingId?: string | null
  proposalErrors?: Record<string, string>
}>(), { proposalCommits: () => ({}), proposalPendingId: null, proposalErrors: () => ({}) })
const emit = defineEmits<{ confirmProposal: [proposalId: string] }>()

function resultHeading(result: AssistantActionResult): string {
  if (result.status !== 'succeeded') return '操作未执行'
  if (result.action === 'propose_rigid_event_change') return '刚性日程变更提案'
  if (result.action === 'query_flexible_tasks') return '已查询的事项'
  if (result.action === 'query_rigid_events') return '已查询的刚性日程'
  if (result.action === 'create_flexible_task') return '已保存'
  if (result.action === 'update_flexible_task') return '已更新'
  if (result.action === 'delete_flexible_task') return '已删除'
  return '已处理'
}

function fieldLabel(key: string): string {
  return ({ title: '名称', location: '地点', start_at: '开始时间', end_at: '结束时间',
    timezone: '时区', recurrence: '重复规则' } as Record<string, string>)[key] ?? key
}

function fieldValue(value: unknown): string {
  if (value === null) return '无'
  if (typeof value === 'string') return value
  return JSON.stringify(value) ?? String(value)
}

function records(result: AssistantActionResult): Array<Record<string, unknown>> {
  if (Array.isArray(result.data)) return result.data.filter((value): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null)
  return typeof result.data === 'object' && result.data !== null
    ? [result.data as Record<string, unknown>] : []
}

function imageMatches(result: AssistantActionResult): Array<Record<string, unknown>> {
  const matches = records(result)[0]?.existing_schedule_matches
  return Array.isArray(matches) ? matches.filter((item): item is Record<string, unknown> =>
    typeof item === 'object' && item !== null) : []
}

function displayDeadline(record: Record<string, unknown>): string {
  return typeof record.deadline === 'string' ? record.deadline : ''
}

function displayEventTime(record: Record<string, unknown>): string {
  const startValue = typeof record.start_at === 'string' ? record.start_at : record.existing_start_at
  const endValue = typeof record.end_at === 'string' ? record.end_at : record.existing_end_at
  if (typeof startValue !== 'string' || typeof endValue !== 'string') return ''
  const start = new Date(startValue)
  const end = new Date(endValue)
  if (Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf())) return ''
  const date = new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(start)
  const startTime = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(start)
  const endTime = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(end)
  return `${date} ${startTime}–${endTime}`
}
</script>

<template>
  <section class="conversation" aria-label="对话记录">
    <p v-if="!messages.length" class="conversation-empty">可以告诉我你的安排，或主动问我需要了解的事。</p>
    <ol v-else class="conversation-list">
      <li v-for="(message, index) in messages" :key="index" :class="['conversation-message', message.role]">
        <span class="conversation-role">{{ message.role === 'user' ? '你' : 'Kairos' }}</span>
        <template v-if="message.role === 'user'"><p>{{ message.content }}</p><p v-if="message.hasImage" class="image-note">已发送一张图片供本次分析</p></template>
        <div v-else class="markdown-content" v-html="renderAssistantMarkdown(message.content)"></div>
        <section v-for="(result, resultIndex) in message.actionResults ?? []" :key="`${index}-${resultIndex}`"
          class="action-result" :class="{ 'action-result-failed': result.status !== 'succeeded' }" aria-live="polite">
          <h3>{{ resultHeading(result) }}</h3>
          <p v-if="result.status !== 'succeeded'">{{ result.message || '请补充信息后重试。' }}</p>
          <div v-else-if="result.action === 'create_rigid_event_draft' && records(result)[0]?.existing_schedule_matches" class="image-matches">
            <p>已只读核对图片日期内的日程：</p>
            <ul><li v-for="(match, matchIndex) in imageMatches(result)" :key="matchIndex">
              <template v-if="match.status === 'unavailable'">{{ match.message }}</template>
              <template v-else><strong>{{ match.title }}</strong> 与「{{ match.existing_title }}」有{{ match.overlap_count }}次时间重叠（如 {{ displayEventTime(match) }}）。请自行核对；不会自动移除或合并。</template>
            </li></ul>
            <p v-if="imageMatches(result).length === 0">没有发现时间重叠。</p>
          </div>
          <div v-else-if="result.action === 'propose_rigid_event_change' && asRigidEventProposal(result)" class="proposal-review">
            <p><strong>{{ asRigidEventProposal(result)!.target_title }}</strong> · {{ asRigidEventProposal(result)!.target_id }}</p>
            <p>范围：{{ asRigidEventProposal(result)!.scope === 'series' ? '整个系列' : '这次' }}</p>
            <p>操作：{{ asRigidEventProposal(result)!.action === 'delete' ? '删除' : '修改' }}</p>
            <ul v-if="Object.keys(asRigidEventProposal(result)!.changes).length">
              <li v-for="(value, key) in asRigidEventProposal(result)!.changes" :key="key">
                {{ fieldLabel(String(key)) }}：{{ fieldValue(value) }}
              </li>
            </ul>
            <p v-if="proposalCommits[asRigidEventProposal(result)!.proposal_id]?.status === 'committed'" role="status">
              已确认{{ asRigidEventProposal(result)!.action === 'delete' ? '删除' : '修改' }}
            </p>
            <template v-else>
              <p v-if="asRigidEventProposal(result)!.status === 'pending'">待确认，事件尚未更改。</p>
              <p v-if="proposalErrors[asRigidEventProposal(result)!.proposal_id]" role="alert">{{ proposalErrors[asRigidEventProposal(result)!.proposal_id] }}</p>
              <button v-if="asRigidEventProposal(result)!.status === 'pending'" type="button"
                :disabled="proposalPendingId !== null"
                @click="emit('confirmProposal', asRigidEventProposal(result)!.proposal_id)">
                {{ proposalPendingId === asRigidEventProposal(result)!.proposal_id ? '确认中…' : `确认${asRigidEventProposal(result)!.action === 'delete' ? '删除' : '修改'}` }}
              </button>
            </template>
          </div>
          <p v-else-if="result.action === 'propose_rigid_event_change'">提案信息不完整，请重新提出修改要求。</p>
          <ul v-else-if="result.action === 'query_flexible_tasks' && records(result).length">
            <li v-for="record in records(result)" :key="String(record.task_id)">
              <strong>{{ record.title }}</strong>
              <span v-if="displayDeadline(record)"> · 截止 {{ displayDeadline(record) }}</span>
            </li>
          </ul>
          <p v-else-if="result.action === 'query_flexible_tasks'">目前没有已保存的柔性事项。</p>
          <ul v-else-if="result.action === 'query_rigid_events' && records(result).length">
            <li v-for="record in records(result)" :key="String(record.occurrence_id)">
              <strong>{{ record.title }}</strong>
              <span v-if="displayEventTime(record)"> · {{ displayEventTime(record) }}</span>
              <span v-if="record.location"> · {{ record.location }}</span>
            </li>
          </ul>
          <p v-else-if="result.action === 'query_rigid_events'">接下来七天没有已保存的刚性日程。</p>
          <p v-else-if="records(result)[0]?.title">
            <strong>{{ records(result)[0].title }}</strong>
            <span v-if="displayDeadline(records(result)[0])"> · 截止 {{ displayDeadline(records(result)[0]) }}</span>
          </p>
        </section>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.conversation { min-width: 0; }
.conversation-empty { margin: 1rem 0; color: #4b6253; line-height: 1.6; }
.conversation-list { list-style: none; margin: 0; padding: 0; display: grid; gap: .9rem; }
.conversation-message { max-width: 96%; min-width: 0; padding: .75rem .9rem; border-radius: 1rem; background: #eaf0e8; overflow-wrap: anywhere; }
.conversation-message.user { justify-self: end; background: #dce9dc; }
.conversation-role { display: block; margin-bottom: .25rem; color: #315341; font-size: .8rem; font-weight: 650; }
.conversation-message p { margin: 0; line-height: 1.55; white-space: pre-wrap; }
.conversation-message .image-note { margin-top: .25rem; color: #526358; font-size: .78rem; }
.image-matches { padding: .55rem; border-radius: .65rem; background: #fff7df; color: #493c20; }
.markdown-content { min-width: 0; line-height: 1.55; overflow-wrap: anywhere; }
.markdown-content :deep(p) { margin: 0 0 .65em; line-height: 1.55; white-space: pre-wrap; }
.markdown-content :deep(p:last-child) { margin-bottom: 0; }
.markdown-content :deep(h1), .markdown-content :deep(h2), .markdown-content :deep(h3) { margin: .8em 0 .4em; line-height: 1.3; font-weight: 650; }
.markdown-content :deep(h1) { font-size: 1.15em; }
.markdown-content :deep(h2) { font-size: 1.08em; }
.markdown-content :deep(h3) { font-size: 1em; }
.markdown-content :deep(ul), .markdown-content :deep(ol) { margin: .35em 0 .7em; padding-inline-start: 1.35em; }
.markdown-content :deep(li + li) { margin-top: .22em; }
.markdown-content :deep(blockquote) { margin: .55em 0; padding-inline-start: .75em; border-inline-start: 2px solid #91a793; color: #40564a; }
.markdown-content :deep(code) { padding: .08em .28em; border-radius: .3em; background: #dce5dc; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9em; }
.markdown-content :deep(pre) { margin: .55em 0; padding: .65em .75em; overflow-x: auto; border-radius: .6em; background: #e1e9e1; }
.markdown-content :deep(pre code) { padding: 0; background: transparent; }
.markdown-content :deep(a) { color: #245b3d; text-decoration-thickness: .08em; text-underline-offset: .14em; }
.markdown-image-alt { color: #526358; font-size: .9em; }
.action-result { margin-top: .7rem; padding: .7rem .8rem; border: 1px solid #91a793; border-radius: .75rem; background: #f8faf4; color: #253e2f; }
.action-result h3 { margin: 0 0 .35rem; font-size: .85rem; font-weight: 650; }
.action-result p { font-size: .88rem; }
.action-result ul { display: grid; gap: .4rem; margin: .3rem 0 0; padding-inline-start: 1.2rem; }
.action-result li { line-height: 1.45; overflow-wrap: anywhere; }
.action-result-failed { border-color: #c8a17e; background: #fcf5ec; color: #66422e; }
.proposal-review { display: grid; gap: .35rem; }
.proposal-review ul { margin: .1rem 0; }
.proposal-review button { justify-self: start; margin-top: .35rem; padding: .45rem .7rem; border: 1px solid #486c53; border-radius: .55rem; background: #315b3d; color: #fff; font: inherit; cursor: pointer; }
.proposal-review button:disabled { opacity: .6; cursor: wait; }
.proposal-review button:focus-visible { outline: 3px solid #315b3d; outline-offset: 3px; }
</style>
