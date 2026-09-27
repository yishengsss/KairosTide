<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { EnvironmentFrame } from './environment.ts'
import { mountAmbientRenderer, sceneStyle, type AmbientRenderer } from './renderer.ts'

const props = defineProps<{ frame: Readonly<EnvironmentFrame> }>()
const style = computed(() => sceneStyle(props.frame))
const canvas = ref<HTMLCanvasElement | null>(null)
let ambient: AmbientRenderer | null = null
let motionPreference: MediaQueryList | null = null

function updateMotion() { ambient?.refresh() }

onMounted(() => {
  motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
  ambient = canvas.value
    ? mountAmbientRenderer(canvas.value, () => props.frame, () => motionPreference?.matches ?? false)
    : null
  motionPreference.addEventListener('change', updateMotion)
})

watch(() => props.frame, () => ambient?.refresh())

onUnmounted(() => {
  motionPreference?.removeEventListener('change', updateMotion)
  ambient?.destroy()
})
</script>

<template>
  <div class="nature-scene" :style="style" aria-hidden="true">
    <div class="sky"></div>
    <div class="horizon-glow"></div>
    <div class="stars">
      <i v-for="n in 24" :key="n" :style="{ '--n': n }"></i>
    </div>
    <div class="moon"></div>
    <div class="sun-aura"></div>
    <div class="sun"></div>

    <div class="clouds clouds-back">
      <span class="cloud cloud-one"></span>
      <span class="cloud cloud-two"></span>
    </div>
    <div class="clouds clouds-front">
      <span class="cloud cloud-three"></span>
      <span class="cloud cloud-four"></span>
    </div>
    <svg class="birds" viewBox="0 0 180 72" aria-hidden="true">
      <g class="bird-flock bird-flock-one">
        <path d="M5 27q8-9 16 0 8-9 16 0M52 40q7-8 14 0 7-8 14 0M107 24q6-7 12 0 6-7 12 0" />
      </g>
      <g class="bird-flock bird-flock-two">
        <path d="M24 13q5-6 10 0 5-6 10 0M82 18q6-7 12 0 6-7 12 0M143 39q5-6 10 0 5-6 10 0" />
      </g>
    </svg>
    <div class="weather-veil"></div>

    <div class="air-haze"></div>
    <div class="lake"></div>
    <svg class="landscape" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="ridgeFarFill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stop-color="var(--mountain-light)" />
          <stop offset="1" stop-color="var(--mountain-far)" />
        </linearGradient>
        <linearGradient id="ridgeNearFill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stop-color="var(--mountain-near)" />
          <stop offset="1" stop-color="var(--shore)" />
        </linearGradient>
      </defs>
      <path class="ridge-haze" d="M0 565 C110 543 170 552 253 525 C359 491 431 505 516 534 C599 516 642 491 749 506 C841 478 947 481 1052 515 C1136 494 1221 504 1329 533 C1425 516 1523 526 1600 539 L1600 639 L0 639 Z" />
      <path class="ridge-far" d="M0 607 C92 582 150 532 226 529 C263 527 286 546 310 564 C352 532 377 464 421 458 C465 452 492 516 524 545 C592 539 638 527 693 551 C744 526 790 481 836 476 C878 470 903 512 937 531 C979 511 1004 439 1047 433 C1095 427 1129 496 1166 523 C1218 520 1257 513 1310 543 C1374 530 1428 493 1470 492 C1516 491 1544 530 1600 550 L1600 645 L0 645 Z" />
      <path class="ridge-light" d="M269 535 C329 509 381 460 421 458 C461 456 488 513 509 534 M777 506 C802 484 819 476 836 476 C864 476 890 507 909 523 M1007 481 C1022 452 1034 434 1047 433 C1077 431 1101 466 1122 496" />
      <path class="ridge-mid" d="M0 627 C97 610 157 578 239 584 C308 588 348 618 412 617 C493 616 540 574 617 582 C684 589 726 623 801 622 C879 621 930 584 1005 583 C1072 582 1123 613 1194 614 C1274 615 1331 581 1407 583 C1480 585 1535 611 1600 615 L1600 650 L0 650 Z" />
      <path class="ridge-near" d="M0 642 C103 630 168 616 245 632 C319 647 357 622 438 631 C502 610 552 616 611 635 C682 626 728 618 792 636 C884 620 952 625 1006 642 C1087 626 1151 612 1215 624 C1310 611 1402 633 1471 635 C1528 628 1571 631 1600 637 L1600 654 L0 654 Z" />
      <g class="far-trees">
        <path d="M115 628 129 599 143 628h-8l13 15h-37l13-15Zm48-3 15-40 16 40h-9l13 16h-40l14-16Zm65 5 12-31 13 31h-7l11 13h-32l11-13Zm1100-2 13-34 14 34h-8l12 14h-35l12-14Zm54-7 17-43 18 43h-10l14 17h-43l14-17Zm66 9 12-30 12 30h-7l10 12h-30l10-12Z" />
        <path d="M176 642v-35m14 39v-45m1154 42v-37m30 42v-49" class="tree-trunks" />
      </g>
      <path class="far-shore" d="M0 627 C174 616 337 627 490 621 C641 618 757 620 899 622 C1074 618 1216 618 1350 627 C1471 625 1531 625 1600 628 L1600 649 L0 649 Z" />
      <path class="near-shore" d="M0 783 C113 755 215 745 320 772 C421 800 508 838 574 900 L0 900 Z M1600 763 C1511 749 1427 763 1359 802 C1306 831 1265 860 1226 900 L1600 900 Z" />
      <path class="shore-detail" d="M0 796 C93 779 189 778 271 795 C357 808 430 849 477 900 M1600 778 C1488 772 1417 794 1368 831 C1332 855 1304 879 1282 900" />
      <path class="reeds" d="M56 821 l-11 -75 m11 75 l22 -90 m-20 86 l-41 -42 M100 805 l-8 -87 m8 87 l31 -65 M1498 799 l-24 -80 m24 80 l20 -91 m9 92 l38 -67 M1569 795 l5 -62" />
    </svg>
    <div class="reflection"></div>
    <div class="fog"></div>
    <canvas ref="canvas" class="ambient-canvas"></canvas>
    <div class="grain"></div>
  </div>
</template>

<style scoped>
.nature-scene { position: absolute; inset: 0; overflow: hidden; isolation: isolate; pointer-events: none; background: var(--sky-zenith); transition: --sky-zenith 12s linear, --sky-horizon 12s linear, --mountain-far 12s linear, --mountain-near 12s linear, --water 12s linear, --shore 12s linear; }
.nature-scene > * { position: absolute; }
.sky { inset: 0; background: linear-gradient(to bottom, var(--sky-zenith) 0%, color-mix(in srgb, var(--sky-zenith) 76%, var(--sky-horizon)) 34%, var(--sky-horizon) 72%, color-mix(in srgb, var(--sky-horizon) 82%, #d7b58f) 100%); transition: background 12s linear; }
.horizon-glow { inset: 15% 0 30%; background: radial-gradient(ellipse 55% 48% at var(--sun-x) 72%, rgba(255, 226, 172, .54), transparent 74%); opacity: var(--sun-opacity); mix-blend-mode: screen; }
.stars { inset: 0 0 42%; opacity: var(--star-opacity); transition: opacity 12s linear; }
.stars i { position: absolute; width: 2px; height: 2px; border-radius: 50%; background: #f1f4ee; box-shadow: 0 0 7px 2px #eef2ed55; left: calc((var(--n) * 43.739%) - 3%); top: calc((var(--n) * 27.713%) - 3%); }
.stars i:nth-child(5n) { width: 1px; height: 1px; opacity: .7; }
.moon { width: clamp(42px, 6vw, 92px); aspect-ratio: 1; left: var(--moon-x); top: var(--moon-y); transform: translate(-50%, -50%); border-radius: 50%; background: radial-gradient(circle at 38% 35%, #f2f0df 0%, #dddfe3 57%, #b7c1cf 100%); box-shadow: 0 0 24px 5px #edf1ef66, 0 0 95px 40px #e0edfa24; opacity: var(--moon-opacity); transition: left 12s linear, top 12s linear, opacity 12s linear; }
.sun-aura { width: 38vmin; height: 38vmin; left: var(--sun-x); top: var(--sun-y); transform: translate(-50%, -50%); border-radius: 50%; background: radial-gradient(circle, #fff3d65b 0%, #f9d58936 27%, transparent 70%); opacity: var(--sun-opacity); mix-blend-mode: screen; filter: blur(12px); transition: left 12s linear, top 12s linear, opacity 12s linear; }
.sun { width: clamp(48px, 7vmin, 108px); aspect-ratio: 1; left: var(--sun-x); top: var(--sun-y); transform: translate(-50%, -50%); border-radius: 50%; background: radial-gradient(circle at 40% 37%, #fffef2, #fff4c6 65%, #f4d696); box-shadow: 0 0 21px 5px #fff0bf92, 0 0 70px 25px #ffe9a641; opacity: var(--sun-opacity); transition: left 12s linear, top 12s linear, opacity 12s linear; }
.clouds { inset: 0 0 35%; opacity: var(--cloud-opacity); transition: opacity 12s linear; }
.clouds-back { filter: blur(24px); opacity: calc(var(--cloud-opacity) * .5); }
.clouds-front { filter: blur(9px); }
.clouds-back { animation: cloud-drift-back 210s ease-in-out infinite alternate; }
.clouds-front { animation: cloud-drift-front 154s ease-in-out infinite alternate; }
@keyframes cloud-drift-back { to { transform: translateX(2.2%); } }
@keyframes cloud-drift-front { to { transform: translateX(-1.7%); } }
.birds { position: absolute; z-index: 2; top: 19%; left: 55%; width: clamp(8rem, 13vw, 13rem); height: auto; overflow: visible; opacity: var(--bird-opacity); color: #253842; filter: drop-shadow(0 1px 2px #eef0db55); animation: flock-glide 46s ease-in-out infinite alternate; }
.bird-flock { fill: none; stroke: currentColor; stroke-linecap: round; stroke-width: 1.8; }
.bird-flock-two { opacity: .65; transform: translateY(7px); }
@keyframes flock-glide { to { translate: 16px -3px; } }
.cloud { position: absolute; height: 10%; border-radius: 50%; background: linear-gradient(#f4f4e7b3, #e9e9df35); box-shadow: 15px 7px 35px #e8e9e966, 0 12px 22px #a2b6c32b; }
.cloud::before, .cloud::after { content: ''; position: absolute; border-radius: 50%; background: inherit; }
.cloud::before { width: 46%; height: 115%; left: 17%; bottom: 18%; }
.cloud::after { width: 30%; height: 80%; right: 8%; bottom: 10%; }
.cloud-one { width: 26%; left: 9%; top: 25%; }
.cloud-two { width: 33%; right: 8%; top: 38%; }
.cloud-three { width: 22%; left: -4%; top: 43%; }
.cloud-four { width: 25%; right: 21%; top: 19%; }
.weather-veil { inset: 0 0 35%; background: linear-gradient(to bottom, var(--weather-veil-color), transparent 85%); opacity: var(--weather-veil-opacity); transition: opacity 12s linear, background 12s linear; }
.air-haze { inset: 37% 0 22%; background: linear-gradient(transparent, #e5edf62b 48%, transparent); opacity: calc(1 - var(--visibility)); }
.landscape { inset: 0; width: 100%; height: 100%; }
.ridge-haze { fill: var(--sky-horizon); opacity: .48; filter: blur(7px); }
.ridge-far { fill: url(#ridgeFarFill); opacity: calc(var(--visibility) * .88 + .08); }
.ridge-light { fill: none; stroke: var(--mountain-light); stroke-width: 2.2; stroke-linecap: round; opacity: .34; filter: blur(.7px); }
.ridge-mid { fill: var(--mountain-mid); opacity: .93; }
.ridge-near { fill: url(#ridgeNearFill); }
.far-trees { fill: var(--shore); opacity: .78; }
.tree-trunks { fill: none; stroke: var(--shore); stroke-width: 2; stroke-linecap: round; opacity: .82; }
.far-shore { fill: var(--shore); opacity: .43; }
.near-shore { fill: var(--shore); }
.shore-detail, .reeds { fill: none; stroke: var(--shore); stroke-width: 5; stroke-linecap: round; opacity: .85; }
.lake { inset: 62.8% 0 0; background: linear-gradient(to bottom, color-mix(in srgb, var(--water) 84%, #e2d7bb) 0%, var(--water) 24%, color-mix(in srgb, var(--water) 62%, #071b2b) 100%); opacity: .96; }
.lake::before { content: ""; position: absolute; inset: 0; background: repeating-linear-gradient(180deg, transparent 0 15px, #e9f0e918 16px, transparent 17px 29px); opacity: .44; mix-blend-mode: screen; }
.reflection { inset: 62.8% 0 0; background: radial-gradient(ellipse 42% 110% at var(--glint-x) 0%, #fff0c77a 0%, #f5e5b836 42%, transparent 83%), linear-gradient(180deg, #fff1cb24, transparent 48%); opacity: var(--glint-opacity); mix-blend-mode: screen; filter: blur(4px); transition: opacity 12s linear, background 12s linear; }
.fog { inset: 35% 0 23%; background: linear-gradient(to bottom, transparent, #e3e9e7aa 63%, #dfe8e784); opacity: var(--fog-opacity); transition: opacity 12s linear; }
.ambient-canvas { inset: 0; width: 100%; height: 100%; }
.grain { inset: 0; opacity: .052; mix-blend-mode: soft-light; background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.6' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.4'/%3E%3C/svg%3E"); }
@media (prefers-reduced-motion: reduce) {
  .nature-scene * { transition-duration: .01ms !important; animation: none !important; }
}
@property --sky-zenith { syntax: '<color>'; inherits: true; initial-value: #10243c; }
@property --sky-horizon { syntax: '<color>'; inherits: true; initial-value: #526777; }
@property --mountain-far { syntax: '<color>'; inherits: true; initial-value: #5a7a87; }
@property --mountain-near { syntax: '<color>'; inherits: true; initial-value: #345760; }
@property --water { syntax: '<color>'; inherits: true; initial-value: #376978; }
@property --shore { syntax: '<color>'; inherits: true; initial-value: #375c4e; }
</style>
