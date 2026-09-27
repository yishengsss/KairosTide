<script setup lang="ts">
import { computed } from 'vue'
import type { components } from '../../../../contracts/backend-api.d.ts'

type Occurrence = components['schemas']['Occurrence']
type Conflict = components['schemas']['Conflict']

const props = defineProps<{
  conflict: Conflict
  occurrences: Occurrence[]
  pending?: boolean
}>()
const emit = defineEmits<{
  choose: [choice: { selectedId: string; memberIds: string[]; snapshotRevision: number }]
}>()

const members = computed(() => props.conflict.member_ids.map(id => ({
  id,
  occurrence: props.occurrences.find(item => item.occurrence_id === id) ?? null,
})))
const incomplete = computed(() => members.value.some(member => member.occurrence === null))
const invalidSelection = computed(() => props.conflict.selected_id !== null &&
  !props.conflict.member_ids.includes(props.conflict.selected_id))
const decisionLocked = computed(() => props.conflict.selected_id !== null && !invalidSelection.value)

function choose(occurrenceId: string) {
  if (incomplete.value || invalidSelection.value || decisionLocked.value || props.pending ||
    !props.conflict.member_ids.includes(occurrenceId)) return
  emit('choose', {
    selectedId: occurrenceId,
    memberIds: [...props.conflict.member_ids],
    snapshotRevision: props.conflict.snapshot_revision,
  })
}
</script>

<template>
  <section class="conflict-choice" aria-labelledby="conflict-title" :aria-busy="pending || undefined">
    <h1 id="conflict-title">有多项事件同时发生</h1>
    <p class="conflict-guidance">请决定当前主要显示哪一项</p>
    <p v-if="incomplete" class="conflict-unavailable" role="status">
      事件信息尚未完整同步，请刷新后再选择。
    </p>
    <p v-else-if="invalidSelection" class="conflict-unavailable" role="status">
      冲突选择与当前事件不匹配，请刷新后重新查看。
    </p>
    <fieldset :disabled="incomplete || invalidSelection || decisionLocked || pending">
      <legend class="visually-hidden">选择当前主要显示的事件</legend>
      <ul class="conflict-list">
        <li v-for="member in members" :key="member.id">
          <label class="conflict-option" :class="{ 'is-selected': conflict.selected_id === member.id }">
            <input
              type="radio"
              name="kairos-conflict-choice"
              :value="member.id"
              :checked="conflict.selected_id === member.id"
              :aria-label="member.occurrence ? `选择 ${member.occurrence.title}${member.occurrence.location ? `，${member.occurrence.location}` : ''}` : '事件信息暂不可用'"
              @change="choose(member.id)"
            >
            <span class="option-copy" v-if="member.occurrence">
              <strong>{{ member.occurrence.title }}</strong>
              <span v-if="member.occurrence.location">{{ member.occurrence.location }}</span>
            </span>
            <span class="option-copy" v-else>
              <strong>事件信息暂不可用</strong>
            </span>
          </label>
        </li>
      </ul>
    </fieldset>
    <p v-if="decisionLocked" class="conflict-result" role="status">
      已选择当前主要事件；其他同时发生的事件按本次选择记录为错过。
    </p>
  </section>
</template>

<style scoped>
.conflict-choice { width: min(32rem, calc(100vw - 2rem)); padding: 1.1rem; border: 1px solid #edf2e87d; border-radius: 1.15rem; background: #152c32ed; color: #f7f5e9; box-shadow: 0 12px 38px #07131c38; backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); }
h1 { margin: 0; font-size: 1.05rem; font-weight: 600; }
.conflict-guidance { margin: .3rem 0 .85rem; color: #d6e3d2; font-size: .84rem; }
fieldset { min-width: 0; margin: 0; padding: 0; border: 0; }
.conflict-list { display: grid; gap: .5rem; margin: 0; padding: 0; list-style: none; }
.conflict-option { display: flex; align-items: center; gap: .8rem; min-height: 3.65rem; padding: .65rem .75rem; border: 1px solid #edf2e832; border-radius: .85rem; background: #edf2e80b; cursor: pointer; }
.conflict-option:has(input:checked), .conflict-option.is-selected { border-color: #dbe8d39c; background: #dbe8d31b; }
.conflict-option:has(input:focus-visible) { outline: 3px solid #fff3bd; outline-offset: 3px; }
input { width: 1.1rem; height: 1.1rem; flex: 0 0 auto; accent-color: #dbe8d3; }
.option-copy { display: grid; gap: .15rem; min-width: 0; }
.option-copy strong { font-size: .92rem; font-weight: 560; overflow-wrap: anywhere; }
.option-copy span { color: #d6e3d2; font-size: .8rem; overflow-wrap: anywhere; }
.conflict-unavailable, .conflict-result { margin: .8rem 0 0; color: #e5eadc; font-size: .82rem; line-height: 1.5; }
.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (prefers-reduced-motion: reduce) { .conflict-option { transition: none; } }
</style>
