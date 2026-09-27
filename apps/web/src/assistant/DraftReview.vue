<script setup lang="ts">
import { computed } from 'vue'
import type { DraftResponse } from './sessionStore.ts'

const props = defineProps<{ draft: DraftResponse; pending: boolean; conflictPairs?: Array<[string, string]> }>()
const emit = defineEmits<{ confirm: [] }>()

const complete = computed(() => props.draft.status === 'ready' &&
  !!props.draft.confirmation_digest && props.draft.candidates.length > 0 &&
  props.draft.candidates.every(item => item.missing_fields.length === 0))

const fieldLabels: Record<string, string> = {
  title: '名称', location: '地点', start_at: '开始时间', end_at: '结束时间',
  timezone: '时区', recurrence: '重复规则',
}
const fieldName = (field: string) => fieldLabels[field] ?? field
const shown = (value: string | null) => value ?? '待补充'

function recurrenceText(candidate: DraftResponse['candidates'][number]) {
  const rule = candidate.recurrence
  if (!rule) return '不重复'
  const frequency = rule.frequency === 'weekly' ? '每周' : '每天'
  const weekdays = rule.weekdays?.length ? ` · 星期 ${rule.weekdays.join('、')}` : ''
  const end = rule.ends_on ? ` · 至 ${rule.ends_on}` : ''
  return `${frequency}${weekdays} · 从 ${rule.starts_on}${end} · ${rule.timezone}`
}
</script>

<template>
  <section class="draft-review" aria-labelledby="draft-title">
    <header class="draft-heading">
      <div>
        <p class="draft-eyebrow">未保存草稿</p>
        <h2 id="draft-title">请核对每一项</h2>
      </div>
      <span class="draft-count">{{ draft.candidates.length }} 项</span>
    </header>

    <ol class="draft-candidates">
      <li v-for="(candidate, index) in draft.candidates" :key="candidate.candidate_id" class="draft-candidate">
        <span class="draft-index">{{ index + 1 }}</span>
        <div class="draft-details">
          <h3>{{ shown(candidate.title) }}</h3>
          <dl>
            <div><dt>开始</dt><dd>{{ shown(candidate.start_at) }}</dd></div>
            <div><dt>结束</dt><dd>{{ shown(candidate.end_at) }}</dd></div>
            <div><dt>地点</dt><dd>{{ shown(candidate.location) }}</dd></div>
            <div><dt>时区</dt><dd>{{ shown(candidate.timezone) }}</dd></div>
            <div><dt>重复</dt><dd>{{ recurrenceText(candidate) }}</dd></div>
          </dl>
          <p v-if="candidate.missing_fields.length" class="draft-missing">
            尚需补充：{{ candidate.missing_fields.map(fieldName).join('、') }}
          </p>
        </div>
      </li>
    </ol>

    <div v-if="draft.questions.length" class="draft-questions">
      <p>请继续告诉 Kairos：</p>
      <ul><li v-for="question in draft.questions" :key="question">{{ question }}</li></ul>
    </div>
    <p v-if="draft.status === 'expired'" class="draft-warning">草稿已过期，请重新核对后再保存。</p>
    <div v-if="conflictPairs?.length" class="draft-conflict" role="alert">
      <strong>发现时间冲突，尚未保存。</strong>
      <p>再次点击确认表示你已核对并仍要保存这些重叠日程：</p>
      <ul><li v-for="(pair, index) in conflictPairs" :key="index">{{ pair[0] }} ↔ {{ pair[1] }}</li></ul>
    </div>
    <p v-if="draft.status === 'committed'" class="draft-saved">已保存</p>
    <button v-if="complete" type="button" class="draft-confirm" :disabled="pending" @click="emit('confirm')">
      {{ pending ? '正在保存…' : conflictPairs?.length ? '确认仍要保存（接受冲突）' : '确认保存全部项目' }}
    </button>
  </section>
</template>

<style scoped>
.draft-review { padding: 1rem; background: #f4f6f0; border-radius: 1rem; color: #172920; }
.draft-heading { display: flex; justify-content: space-between; align-items: start; gap: .75rem; }
.draft-eyebrow { margin: 0 0 .25rem; font-size: .875rem; font-weight: 650; color: #53665a; }
.draft-heading h2 { margin: 0; font-size: 1.125rem; line-height: 1.3; }
.draft-count { white-space: nowrap; font-size: .875rem; color: #53665a; }
.draft-candidates { margin: 1rem 0; padding: 0; list-style: none; display: grid; gap: .75rem; }
.draft-candidate { display: flex; align-items: start; gap: .75rem; padding: .875rem; background: #fff; border: 1px solid #d9e1d7; border-radius: .8rem; }
.draft-index { flex: none; width: 1.5rem; height: 1.5rem; display: grid; place-items: center; border-radius: 50%; background: #dce9dc; font-size: .75rem; font-weight: 700; }
.draft-details { min-width: 0; flex: 1; }
.draft-details h3 { margin: 0 0 .625rem; font-size: 1rem; line-height: 1.4; overflow-wrap: anywhere; }
.draft-details dl { margin: 0; display: grid; gap: .25rem; }
.draft-details dl div { display: grid; grid-template-columns: 3rem minmax(0, 1fr); gap: .5rem; }
.draft-details dt { color: #52655a; }
.draft-details dd { margin: 0; overflow-wrap: anywhere; }
.draft-missing, .draft-warning { color: #8a422b; font-weight: 600; }
.draft-questions { padding: .75rem; border-radius: .7rem; background: #fff; }
.draft-conflict { margin: .75rem 0; padding: .75rem; border-radius: .7rem; background: #fff0e9; color: #823e29; }
.draft-conflict p { margin: .35rem 0; }
.draft-conflict ul { margin: .25rem 0; padding-inline-start: 1.3rem; }
.draft-questions p { margin: 0 0 .25rem; font-weight: 600; }
.draft-questions ul { margin: 0; padding-inline-start: 1.4rem; }
.draft-saved { font-weight: 650; color: #26583a; }
.draft-confirm { min-height: 2.75rem; width: 100%; padding: .55rem 1rem; border: 0; border-radius: .75rem; background: #25583b; color: #fff; font: inherit; font-weight: 650; cursor: pointer; }
.draft-confirm:disabled { opacity: .65; cursor: wait; }
.draft-confirm:active { background: #19452c; transform: scale(.98); }
.draft-confirm:focus-visible { outline: 2px solid #123b27; outline-offset: 3px; }
@media (prefers-reduced-motion: reduce) { .draft-confirm:active { transform: none; } }
</style>
