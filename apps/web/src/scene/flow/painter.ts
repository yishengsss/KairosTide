/** Natural drawing layers extracted from the user's Continuous Flow Demo.
 * UI, task suggestions, event river and accelerated demo clock are intentionally absent.
 * Deterministic geometry and elapsed-time motion replace per-frame mutation.
 */
import type { EnvironmentFrame } from '../environment.ts'
import { mixColor, seasonalBankColor, type RGB } from '../palette.ts'
import { getSeason, type FlowSeason } from './season.ts'

type Phase = { sunAlt: number; star: number; tide: number }
/** The visible shoreline point at x; also used to anchor water-level UI. */
export function waterSurfaceYAt(x: number, height: number, tide: number, elapsedSeconds: number): number {
  const waveOffset = elapsedSeconds * 1.25
  const waveEnergy = Math.max(0.35, tide)
  return height * 0.78 - tide * 25 +
    Math.sin(x * 0.008 + waveOffset) * 23 * waveEnergy +
    Math.sin(x * 0.02 + waveOffset * 1.4) * 23 * waveEnergy * 0.4
}

/** Stable, asymmetrical cloud profile: broad bases and softly stepped cumulus crowns. */
export function traceCloudShape(target: CanvasRenderingContext2D, cx: number, cy: number, width: number, height: number, form = 0) {
  const crown = [0.42, 0.34, 0.48][form % 3]
  const leftCrown = [0.2, 0.26, 0.16][form % 3]
  const rightCrown = [0.17, 0.13, 0.24][form % 3]
  target.beginPath()
  target.moveTo(cx - width * 0.49, cy + height * 0.2)
  target.bezierCurveTo(cx - width * 0.53, cy + height * 0.04, cx - width * 0.43, cy - height * leftCrown, cx - width * 0.29, cy - height * 0.1)
  target.bezierCurveTo(cx - width * 0.24, cy - height * 0.34, cx - width * 0.06, cy - height * crown, cx + width * 0.08, cy - height * 0.22)
  target.bezierCurveTo(cx + width * 0.18, cy - height * 0.43, cx + width * 0.38, cy - height * rightCrown, cx + width * 0.39, cy + height * 0.02)
  target.bezierCurveTo(cx + width * 0.54, cy + height * 0.02, cx + width * 0.54, cy + height * 0.2, cx + width * 0.4, cy + height * 0.22)
  target.lineTo(cx - width * 0.34, cy + height * 0.22)
  target.bezierCurveTo(cx - width * 0.45, cy + height * 0.24, cx - width * 0.49, cy + height * 0.22, cx - width * 0.49, cy + height * 0.2)
  target.closePath()
}

export function horizonGlowStrength(sunAlt: number): number {
  const remaining = Math.max(0, Math.min(1, 1 - Math.abs(sunAlt) / 0.34))
  return remaining * remaining * (3 - 2 * remaining)
}

export function nearRidgeSurfaceY(x: number, height: number): number {
  return height * 0.7 + 20 - Math.sin(x * 0.007 + 1) * 15 - Math.sin(x * 0.018) * 8
}

export function createFlowPainter(ctx: CanvasRenderingContext2D) {
  let W = 1, H = 1, seconds = 0
  let frame: EnvironmentFrame
  let seed = 7619
  function random() { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296 }
function lerpArr(a: number[], b: number[], t: number) { return a.map((v, i) => v + (b[i] - v) * t) }
function colorArray(color: RGB) { return [color.r, color.g, color.b] }
function colorCss(color: RGB, alpha = 1) { return `rgba(${color.r},${color.g},${color.b},${alpha})` }

function drawSky() {
  const grad = ctx.createLinearGradient(0, 0, 0, H * 0.82)
  const top = frame.palette.skyZenith
  const horizon = frame.palette.skyHorizon
  const middle = mixColor(top, horizon, 0.56)
  grad.addColorStop(0, colorCss(top))
  grad.addColorStop(0.58, colorCss(middle))
  grad.addColorStop(1, colorCss(horizon))
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);
}

// ============================================
// 太阳/月亮
// ============================================
function drawSun(season: FlowSeason, phase: Phase, hour: number) {
  if (phase.sunAlt < -0.16) return;
  const x = W * frame.sun.screenX / 100;
  const y = H * (0.70 - phase.sunAlt * 0.5);
  const intensity = Math.max(0, phase.sunAlt);
  const visibility = Math.max(0, Math.min(1, (phase.sunAlt + 0.16) / 0.16));

  const glowSize = 60 + intensity * 100;
  const glow = ctx.createRadialGradient(x, y, 0, x, y, glowSize);
  glow.addColorStop(0, `rgba(${season.sunGlow[0]},${season.sunGlow[1]},${season.sunGlow[2]},${(0.4 + intensity * 0.4) * visibility})`);
  glow.addColorStop(1, `rgba(${season.sunGlow.join(',')},0)`);
  ctx.fillStyle = glow;
  ctx.beginPath(); ctx.arc(x, y, glowSize, 0, Math.PI * 2); ctx.fill();

  ctx.beginPath();
  ctx.arc(x, y, 22 + intensity * 12, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(${season.sunColor[0]},${season.sunColor[1]},${season.sunColor[2]},${visibility})`;
  ctx.fill();
}

/** A broad, horizon-bound warm wash lets the sun read as rising behind the ridge. */
function drawHorizonGlow(phase: Phase) {
  const strength = horizonGlowStrength(phase.sunAlt)
  if (strength < 0.01) return
  const x = W * frame.sun.screenX / 100
  const y = H * 0.70
  const color = mixColor(frame.palette.skyHorizon, { r: 255, g: 166, b: 112 }, 0.38)
  const radius = Math.max(W * 0.42, H * 0.46)
  const glow = ctx.createRadialGradient(x, y, 0, x, y, radius)
  glow.addColorStop(0, colorCss(color, strength * 0.19))
  glow.addColorStop(0.42, colorCss(color, strength * 0.095))
  glow.addColorStop(1, colorCss(color, 0))
  ctx.save()
  ctx.beginPath()
  ctx.rect(0, H * 0.44, W, H * 0.4)
  ctx.clip()
  ctx.fillStyle = glow
  ctx.fillRect(0, H * 0.44, W, H * 0.4)
  ctx.restore()
}

function drawMoon(season: FlowSeason, phase: Phase, hour: number) {
  if (phase.star < 0.2) return;
  const x = W * frame.moon.screenX / 100;
  const y = H * frame.moon.screenY / 100;
  const glow = ctx.createRadialGradient(x, y, 0, x, y, 100);
  glow.addColorStop(0, `rgba(220,230,255,${phase.star * 0.3})`);
  glow.addColorStop(1, 'rgba(220,230,255,0)');
  ctx.fillStyle = glow;
  ctx.beginPath(); ctx.arc(x, y, 100, 0, Math.PI * 2); ctx.fill();

  ctx.beginPath(); ctx.arc(x, y, 16, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(240,245,255,${phase.star})`; ctx.fill();

  ctx.beginPath(); ctx.arc(x - 5, y - 2, 14, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(15,20,45,${phase.star * 0.8})`; ctx.fill();
}

// ============================================
// 星星
// ============================================
const stars: { x: number; y: number; r: number; baseAlpha: number; phase: number; twinkleSpeed: number }[] = [];
for (let i = 0; i < 150; i++) {
  stars.push({
    x: random(), y: random() * 0.65,
    r: random() * 1.5 + 0.3,
    baseAlpha: random() * 0.7 + 0.2,
    phase: random() * Math.PI * 2,
    twinkleSpeed: 0.24 + random() * 0.18,
  });
}

function drawStars(phase: Phase) {
  if (phase.star < 0.05) return;
  const t = seconds;
  stars.forEach(s => {
    const a = s.baseAlpha * phase.star * (0.76 + 0.24 * Math.sin(t * s.twinkleSpeed + s.phase));
    ctx.beginPath();
    ctx.arc(s.x * W, s.y * H, s.r, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(255,255,255,${a})`;
    ctx.fill();
  });
}

// ============================================
// 云
// ============================================
const clouds: { x: number; y: number; w: number; h: number; speed: number; alpha: number; form: number }[] = [];
for (let i = 0; i < 6; i++) {
  clouds.push({
    x: random(), y: 0.08 + random() * 0.2,
    w: 150 + random() * 250, h: 30 + random() * 40,
    speed: 0.08 + random() * 0.15,
    alpha: 0.36 + random() * 0.16,
    form: i % 3,
  });
}

function drawClouds(phase: Phase) {
  if (phase.star > 0.5) return;
  clouds.forEach(c => {
    const cx = ((c.x * W + seconds * c.speed * 60 + c.w) % (W + c.w * 2)) - c.w;
    const cy = c.y * H;
    const weatherCoverage = frame.atmosphere.availability === 'unavailable' ? 0.3 : frame.atmosphere.cloud
    const a = c.alpha * (1 - phase.star) * Math.max(0.34, phase.sunAlt + 0.42) * (0.72 + weatherCoverage * 0.5)
    const cloudColor = mixColor(frame.palette.skyHorizon, { r: 250, g: 249, b: 242 }, 0.76)
    const shadeColor = mixColor(frame.palette.skyHorizon, frame.palette.skyZenith, 0.46)

    ctx.save()
    ctx.globalAlpha = a
    const fill = ctx.createLinearGradient(cx, cy - c.h * 0.48, cx, cy + c.h * 0.25)
    fill.addColorStop(0, colorCss(cloudColor))
    fill.addColorStop(0.58, colorCss(mixColor(cloudColor, frame.palette.skyHorizon, 0.16)))
    fill.addColorStop(1, colorCss(shadeColor, 0.88))
    traceCloudShape(ctx, cx, cy, c.w, c.h, c.form)
    ctx.fillStyle = fill
    ctx.fill()

    // A restrained cool underside gives the cloud volume without an outline or glow.
    ctx.save()
    traceCloudShape(ctx, cx, cy, c.w, c.h, c.form)
    ctx.clip()
    const underside = ctx.createLinearGradient(0, cy - c.h * 0.02, 0, cy + c.h * 0.24)
    underside.addColorStop(0, colorCss(frame.palette.skyHorizon, 0))
    underside.addColorStop(1, colorCss(shadeColor, 0.38))
    ctx.fillStyle = underside
    ctx.fillRect(cx - c.w * 0.52, cy, c.w * 1.04, c.h * 0.28)
    ctx.restore()
    ctx.restore()
  });
}

// ============================================
// 地平线 + 植物
// ============================================
function drawHorizon(season: FlowSeason, phase: Phase) {
  const horizonY = H * 0.7;
  const dawn = horizonGlowStrength(phase.sunAlt)
  const dawnTint = mixColor(frame.palette.skyHorizon, { r: 255, g: 166, b: 112 }, 0.38)
  const distantRidge = mixColor(frame.palette.mountainFar, dawnTint, dawn * 0.2)
  const seasonalGround = { r: season.ground[0], g: season.ground[1], b: season.ground[2] }
  const seasonTintedShore = seasonalBankColor(frame.palette.shore, seasonalGround, season.shoreCoverage)
  const nearRidge = mixColor(seasonTintedShore, dawnTint, dawn * 0.055)

  ctx.beginPath();
  ctx.moveTo(0, horizonY);
  for (let x = 0; x <= W + 20; x += 20) {
    const y = horizonY - 40 - Math.sin(x * 0.004) * 25 - Math.sin(x * 0.011) * 12;
    ctx.lineTo(x, y);
  }
  ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath();
  ctx.fillStyle = colorCss(distantRidge, 0.9); ctx.fill();

  ctx.beginPath();
  ctx.moveTo(0, horizonY + 30);
  for (let x = 0; x <= W + 15; x += 15) {
    ctx.lineTo(x, nearRidgeSurfaceY(x, H));
  }
  ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath();
  ctx.fillStyle = colorCss(nearRidge, 0.96); ctx.fill();
}

const trees: { x: number; size: number; type: string }[] = [];
for (let i = 0; i < 14; i++) {
  trees.push({
    x: random(),
    size: 15 + random() * 25,
    type: random() > 0.5 ? 'tree' : 'bush',
  });
}

function drawTrees(season: FlowSeason, phase: Phase) {
  const dayFactor = Math.max(0, phase.sunAlt);
  const leafLight = 0.32 + (1 - phase.star) * 0.16 + dayFactor * 0.36
  const leafScale = 0.7 + season.foliageCoverage * 0.3
  const leafAlpha = 0.85 * (0.62 + season.foliageCoverage * 0.38)
  const bankScale = 0.7 + season.shoreCoverage * 0.3
  const planted = trees.map(tree => {
    const x = tree.x * W
    return { ...tree, x, y: nearRidgeSurfaceY(x, H) }
  }).sort((a, b) => a.y - b.y)
  planted.forEach(t => {
    const s = t.size / 25;
    const col = season.foliage.map(c => c * leafLight);
    const a = 0.85;

    if (t.type === 'tree') {
      ctx.fillStyle = `rgba(60,40,30,${a})`;
      ctx.fillRect(t.x - 2 * s, t.y - 20 * s, 4 * s, 20 * s);
      ctx.beginPath(); ctx.arc(t.x, t.y - 25 * s, 15 * s * leafScale, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${col[0]|0},${col[1]|0},${col[2]|0},${leafAlpha})`; ctx.fill();
      ctx.beginPath(); ctx.arc(t.x - 8 * s, t.y - 20 * s, 10 * s * leafScale, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${col[0]*0.9|0},${col[1]*0.9|0},${col[2]*0.9|0},${leafAlpha})`; ctx.fill();
      ctx.beginPath(); ctx.arc(t.x + 8 * s, t.y - 22 * s, 11 * s * leafScale, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${col[0]*1.1|0},${col[1]*1.1|0},${col[2]*0.9|0},${leafAlpha})`; ctx.fill();
    } else {
      ctx.beginPath(); ctx.ellipse(t.x, t.y - 5 * s, 12 * s * bankScale, 8 * s * bankScale, 0, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${col[0]|0},${col[1]|0},${col[2]|0},${leafAlpha})`; ctx.fill();
    }
  });
}

// ============================================
// 水面潮汐
// ============================================
let waveOffset = 0;

function drawWater(phase: Phase) {
  waveOffset = seconds * 1.25; // Fixed phase speed: changing daylight must not rewind waves.
  const waveEnergy = Math.max(0.35, phase.tide);

  const waterY = H * 0.78;
  const layers = [
    { phase: 0, amp: 1.0, speed: 1.0, alpha: 0.3 },
    { phase: 1.5, amp: 0.6, speed: 1.3, alpha: 0.2 },
    { phase: 3.0, amp: 0.4, speed: 0.8, alpha: 0.15 },
  ];

  const waterBoundary: { x: number; y: number }[] = [];
  layers.forEach((layer, idx) => {
    const points = [];
    const amp = 23 * waveEnergy * layer.amp;
    const baseY = waterY + idx * 18 - phase.tide * 25;

    for (let x = 0; x <= W + 20; x += 10) {
      let y = idx === 0
        ? waterSurfaceYAt(x, H, phase.tide, seconds)
        : baseY + Math.sin(x * 0.008 + waveOffset * layer.speed + layer.phase) * amp +
          Math.sin(x * 0.02 + waveOffset * layer.speed * 1.4 + layer.phase) * amp * 0.4
      points.push({ x, y });
    }

    if (idx === 0) waterBoundary.push(...points);
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    points.forEach(p => ctx.lineTo(p.x, p.y));
    ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath();

    const dayFactor = Math.max(0.1, phase.sunAlt + 0.3);
    const wc = colorArray(frame.palette.water).map(c => c * (0.72 + dayFactor * 0.28));
    ctx.fillStyle = `rgba(${wc[0]|0},${wc[1]|0},${wc[2]|0},${layer.alpha + phase.tide * 0.15})`;
    ctx.fill();

    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    points.forEach(p => ctx.lineTo(p.x, p.y));
    ctx.strokeStyle = `rgba(255,255,255,${0.1 + waveEnergy * 0.14})`;
    ctx.lineWidth = 1;
    ctx.stroke();
  });

  // All detail shares the actual moving water silhouette, including narrow views.
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(waterBoundary[0].x, waterBoundary[0].y);
  waterBoundary.forEach(point => ctx.lineTo(point.x, point.y));
  ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath(); ctx.clip();
  ctx.lineCap = 'round';
  const waterLight = mixColor(frame.palette.water, frame.palette.skyHorizon, 0.58);

  // Perspective compresses distant wavelets; fixed seeds avoid frame-to-frame noise.
  for (let index = 0; index < 24; index += 1) {
    const across = (index * 0.61803398875) % 1;
    const depth = (index * 0.754877666) % 1;
    const x = across * W;
    const y = H * (0.795 + depth * 0.19);
    const length = Math.min(90, W * (0.009 + depth * 0.038)) * (0.6 + (index % 5) * 0.12);
    const motion = seconds * (0.24 + (index % 4) * 0.025) + index * 2.17;
    const sway = Math.sin(motion) * waveEnergy * (0.6 + depth * 2);
    ctx.strokeStyle = colorCss(waterLight, 0.12 + depth * 0.12);
    ctx.lineWidth = 0.6 + depth * 0.6;
    ctx.beginPath();
    ctx.moveTo(x - length / 2, y + sway);
    ctx.quadraticCurveTo(x, y + sway + Math.sin(motion + 1.1) * waveEnergy * 2.2, x + length / 2, y - sway * 0.45);
    ctx.stroke();
  }

  // Short shoreline fragments hug the same sampled water edge, never a second guessed shoreline.
  for (let i = 1; i < waterBoundary.length - 3; i += 5) {
    const fade = 0.5 + 0.5 * Math.sin(seconds * 0.28 + i * 1.73);
    ctx.strokeStyle = colorCss(waterLight, 0.07 + fade * 0.09);
    ctx.lineWidth = 0.8;
    ctx.beginPath();
    for (let j = 0; j < 3; j += 1) {
      const point = waterBoundary[i + j];
      const y = point.y + 4 + fade * 2;
      if (j === 0) ctx.moveTo(point.x, y); else ctx.lineTo(point.x, y);
    }
    ctx.stroke();
  }

  // Broken light path widens toward the viewer. No full-screen glow or flashing dots.
  const sunlight = Math.max(0, Math.min(1, (phase.sunAlt + 0.08) / 0.25));
  const moonlight = phase.star * (1 - sunlight);
  const transmission = frame.atmosphere.condition ? frame.atmosphere.transmission : 1;
  for (const source of [
    { x: frame.sun.screenX, strength: sunlight * 0.25, tint: 0.3 },
    { x: frame.moon.screenX, strength: moonlight * 0.15, tint: 0.75 },
  ]) {
  if (source.strength <= 0) continue;
  const sourceX = source.x * W / 100;
  const strength = source.strength * transmission;
  const lightColor = mixColor(frame.palette.skyHorizon, { r: 229, g: 237, b: 240 }, source.tint);
  for (let i = 0; i < 64; i += 1) {
    const depth = ((i * 0.754877666) % 1);
    const spread = ((i * 0.618033989) % 1) * 2 - 1;
    const envelope = Math.pow(1 - Math.abs(spread), 1.4);
    const shimmer = 0.55 + 0.45 * Math.sin(seconds * (0.22 + (i % 7) * 0.017) + i * 2.4);
    const x = sourceX + spread * W * (0.025 + depth * 0.16);
    const y = H * (0.79 + depth * 0.21) + Math.sin(seconds * 0.3 + i) * (0.3 + depth);
    const length = (2 + depth * 16) * (0.45 + (i % 5) * 0.18);
    ctx.strokeStyle = colorCss(lightColor, strength * envelope * shimmer);
    ctx.lineWidth = 0.65 + depth * 0.75;
    ctx.beginPath(); ctx.moveTo(x - length / 2, y);
    ctx.lineTo(x + length / 2, y + Math.sin(i) * 0.5); ctx.stroke();
  }
  }
  ctx.restore();
}


const birds: { x: number; y: number; speed: number; size: number; phase: number }[] = [];
for (let i = 0; i < 8; i++) {
  birds.push({
    x: random(), y: 0.15 + random() * 0.25,
    speed: 0.3 + random() * 0.4,
    size: 4 + random() * 4,
    phase: random() * Math.PI * 2,
  });
}

function drawBirds(season: FlowSeason, phase: Phase) {
  const isMigration = season.name === '春' || season.name === '秋';
  const hour = frame.instant.getHours();
  const isDawn = phase.sunAlt > -0.2 && phase.sunAlt < 0.4 && hour < 12;
  const isDusk = phase.sunAlt > -0.2 && phase.sunAlt < 0.4 && hour > 12;
  if (!isDawn && !isDusk) return;
  const vis = isMigration ? 1 : 0.5;
  const t = seconds;

  birds.forEach(bird => {
    const b = { ...bird, x: ((bird.x * W + seconds * bird.speed * 60 + 50) % (W + 100)) - 50, y: bird.y * H };
    const flap = Math.sin(t * 8 + b.phase) * 0.5 + 0.5;
    const y = b.y + Math.sin(t + b.phase) * 5;

    ctx.beginPath();
    ctx.moveTo(b.x - b.size, y);
    ctx.quadraticCurveTo(b.x - b.size / 2, y - b.size * flap, b.x, y);
    ctx.quadraticCurveTo(b.x + b.size / 2, y - b.size * flap, b.x + b.size, y);
    ctx.strokeStyle = `rgba(30,30,50,${0.4 * vis})`;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  });
}


  return function paint(next: EnvironmentFrame, width: number, height: number, elapsedSeconds: number): (x: number) => number {
    frame = next; W = width; H = height; seconds = elapsedSeconds
    const season = getSeason(1 + frame.season.progress * 12)
    const altitude = Math.sin(frame.sun.elevationDeg * Math.PI / 180)
    const phase = { sunAlt: altitude, star: frame.atmosphere.stars, tide: Math.max(0.05, altitude * 0.9 + 0.1) }
    const hour = frame.instant.getHours() + frame.instant.getMinutes() / 60
    ctx.clearRect(0, 0, W, H)
    drawSky()
    drawHorizonGlow(phase)
    drawStars(phase)
    drawMoon(season, phase, hour)
    ctx.save()
    ctx.globalAlpha = frame.atmosphere.condition ? frame.atmosphere.transmission : 1
    drawSun(season, phase, hour)
    ctx.restore()
    drawClouds(phase)
    drawBirds(season, phase)
    drawHorizon(season, phase)
    drawTrees(season, phase)
    drawWater(phase)
    // Weather is independent of celestial coordinates; unavailable stays neutral.
    if (frame.atmosphere.condition) {
      ctx.fillStyle = `rgba(47,60,76,${frame.atmosphere.cloud * 0.25})`
      ctx.fillRect(0, 0, W, H)
    }
    if (frame.atmosphere.fog > 0) {
      const fog = ctx.createLinearGradient(0, H * 0.45, 0, H)
      fog.addColorStop(0, 'rgba(211,218,218,0)')
      fog.addColorStop(0.45, `rgba(211,218,218,${frame.atmosphere.fog * 0.45})`)
      fog.addColorStop(1, 'rgba(211,218,218,0)')
      ctx.fillStyle = fog; ctx.fillRect(0, 0, W, H)
    }
    const rain = frame.atmosphere.rain, snow = frame.atmosphere.snow
    ctx.save(); ctx.beginPath(); ctx.rect(0,0,W,H); ctx.clip()
    for (let i = 0; i < Math.round(70 * Math.max(rain, snow)); i++) {
      const x = ((i * 0.618034 + seconds * (rain ? 0.015 : 0.004)) % 1) * W
      const y = ((i * 0.414214 + seconds * (rain ? 0.35 : 0.025)) % 1) * H
      ctx.beginPath()
      if (rain) {
        ctx.strokeStyle = 'rgba(220,230,238,.26)'; ctx.lineWidth = 1
        ctx.moveTo(x, y); ctx.lineTo(x - 2, y + 13); ctx.stroke()
      } else {
        ctx.fillStyle = 'rgba(240,243,247,.65)'; ctx.arc(x,y,1.4,0,Math.PI*2); ctx.fill()
      }
    }
    ctx.restore()
    const sampledHeight = H
    const sampledTide = phase.tide
    const sampledSeconds = seconds
    return (x: number) => waterSurfaceYAt(x, sampledHeight, sampledTide, sampledSeconds)
  }
}
