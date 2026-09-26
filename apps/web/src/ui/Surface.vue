<template>
  <div class="kairos-surface"><slot /></div>
</template>

<style scoped>
.kairos-surface {
  background: linear-gradient(155deg, rgba(249, 251, 239, .88), rgba(227, 236, 222, .78));
  color: #172920;
  border: 1px solid rgba(247, 250, 237, .68);
  box-shadow: 0 24px 80px rgba(4, 13, 18, .22), inset 0 1px rgba(255, 255, 255, .52);
  backdrop-filter: blur(30px) saturate(1.18);
  -webkit-backdrop-filter: blur(30px) saturate(1.18);
}
@media (prefers-reduced-transparency: reduce) {
  .kairos-surface { background: #f6f8ee; backdrop-filter: none; -webkit-backdrop-filter: none; }
}
@media (prefers-contrast: more) {
  .kairos-surface { background: #fff; border-color: #172920; }
}
</style>
