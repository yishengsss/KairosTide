<script setup lang="ts">
withDefaults(defineProps<{
  type?: 'button' | 'submit'
  disabled?: boolean
  quiet?: boolean
}>(), { type: 'button', disabled: false, quiet: false })
</script>

<template>
  <button :type="type" :disabled="disabled" :class="['kairos-action', { 'is-quiet': quiet }]">
    <slot />
  </button>
</template>

<style scoped>
.kairos-action {
  min-width: 2.75rem; min-height: 2.75rem; padding: .5rem .875rem;
  border: 1px solid #31583d; border-radius: .75rem;
  background: #25583b; color: #fff; font: inherit; font-weight: 600;
  cursor: pointer; touch-action: manipulation;
  transition: transform 120ms ease-out, background-color 120ms ease-out;
}
.kairos-action.is-quiet { background: transparent; color: #1c4930; border-color: #a9bbaa; }
.kairos-action:active:not(:disabled) { transform: scale(.98); background: #19462d; }
.kairos-action.is-quiet:active:not(:disabled) { background: #dce9dc; }
.kairos-action:disabled { opacity: .55; cursor: not-allowed; }
.kairos-action:focus-visible { outline: 2px solid #173c2a; outline-offset: 3px; }
@media (prefers-reduced-motion: reduce) {
  .kairos-action { transition: background-color 80ms ease-out; }
  .kairos-action:active:not(:disabled) { transform: none; }
}
</style>
