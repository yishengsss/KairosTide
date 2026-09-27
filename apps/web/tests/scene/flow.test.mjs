import test from 'node:test'
import assert from 'node:assert/strict'
import { createFlowPainter, horizonGlowStrength, nearRidgeSurfaceY, traceCloudShape } from '../../src/scene/flow/painter.ts'
import { getSeason } from '../../src/scene/flow/season.ts'
import { computeEnvironment } from '../../src/scene/environment.ts'
import { seasonalBankColor } from '../../src/scene/palette.ts'

function recorder() {
  const calls = []
  const ctx = new Proxy({}, {
    get: (_, key) => (...args) => {
      calls.push([key, ...args])
      if (key === 'createLinearGradient' || key === 'createRadialGradient') return { addColorStop(...args) { calls.push(['stop', ...args]) } }
    },
    set: (_, key, value) => { if (typeof value !== 'object') calls.push([key, value]); return true },
  })
  return { calls, ctx }
}
const frame = computeEnvironment({ instant: new Date('2026-09-26T04:30:00Z'), location: { latitude: 34, longitude: 109 }, weather: null })

test('sunrise horizon glow peaks at the ridge and fades symmetrically into day and night', () => {
  assert.equal(horizonGlowStrength(0), 1)
  assert.ok(horizonGlowStrength(-0.16) > 0)
  assert.ok(horizonGlowStrength(0.16) > 0)
  assert.equal(horizonGlowStrength(-0.34), 0)
  assert.equal(horizonGlowStrength(0.34), 0)
})

test('sunrise paints a broad warm glow behind the mountain silhouette', () => {
  const dawn = computeEnvironment({
    instant: new Date('2026-09-26T21:30:00Z'),
    location: { latitude: 34, longitude: 109 }, weather: null,
  })
  const { calls, ctx } = recorder()
  createFlowPainter(ctx)(dawn, 390, 844, 0)
  const ridgeGlows = calls.filter(([name, , y1, , , y2]) => name === 'createRadialGradient'
    && y1 === 844 * 0.7 && y2 === 844 * 0.7)
  assert.equal(ridgeGlows.length, 1)
})

test('tree trunks terminate exactly on the near ridge surface', () => {
  const { calls, ctx } = recorder()
  createFlowPainter(ctx)(frame, 390, 844, 0)
  const trunks = calls.filter(([name, , y, width, height]) => name === 'fillRect'
    && width > 2 && width < 8 && height > 10 && height < 35 && y > 844 * 0.6)
  assert.ok(trunks.length > 0)
  for (const [, x, y, width, height] of trunks) {
    const rootX = x + width / 2
    assert.ok(Math.abs(y + height - nearRidgeSurfaceY(rootX, 844)) < 1e-8)
  }
})

test('reference scene repeats exactly at fixed time, including resize and remount', () => {
  const a = recorder(), b = recorder()
  const paint = createFlowPainter(a.ctx)
  paint(frame, 1440, 900, 20)
  const first = [...a.calls]
  a.calls.length = 0
  paint(frame, 390, 844, 55)
  a.calls.length = 0
  paint(frame, 1440, 900, 20)
  createFlowPainter(b.ctx)(frame, 1440, 900, 20)
  assert.deepEqual(a.calls, first)
  assert.deepEqual(b.calls, first)
  assert.ok(!first.some(([method]) => method === 'fillText'), 'no demo task/time labels are drawn')
  for (const [, ...args] of first) for (const arg of args) if (typeof arg === 'number') assert.ok(Number.isFinite(arg))
})

test('March and September use spring/autumn palettes without January-as-spring bug', () => {
  const spring = getSeason(3)
  assert.equal(spring.name, '春')
  assert.ok(spring.foliage[0] > 130 && spring.foliage[1] > 185 && spring.foliage[2] > 100)
  assert.ok(spring.ground[1] > spring.ground[0])
  assert.equal(getSeason(9).name, '秋')
  assert.equal(getSeason(12).name, '冬')
  assert.deepEqual(getSeason(1).sky1, getSeason(13).sky1)
  assert.ok(getSeason(6).foliageCoverage > getSeason(3).foliageCoverage)
  assert.ok(getSeason(6).shoreCoverage > getSeason(12).shoreCoverage)
  assert.notDeepEqual(getSeason(9).foliage, getSeason(6).foliage)
})

test('summer canopy is fuller than winter while fixed tree positions stay deterministic', () => {
  const radiiAt = (month) => {
    const season = (month - 1) / 12
    const seasonalFrame = computeEnvironment({
      instant: frame.instant, location: { latitude: 34, longitude: 109 }, weather: null, season,
    })
    const { calls, ctx } = recorder()
    createFlowPainter(ctx)(seasonalFrame, 390, 844, 8)
    return calls.filter(([name, , y, radius]) => name === 'arc' && y > 844 * 0.55 && y < 844 * 0.72 && radius < 30)
      .map(([, x, y, radius]) => [x, y, radius])
  }
  const summer = radiiAt(6)
  const winter = radiiAt(12)
  assert.ok(summer.length > 0)
  assert.equal(winter.length, summer.length)
  assert.ok(summer[0][2] > winter[0][2])
  assert.deepEqual(summer.map(([x, y]) => [x, y]), winter.map(([x, y]) => [x, y]))
})

test('seasonal bank hues change without overriding current scene brightness', () => {
  const base = { r: 55, g: 105, b: 78 }
  const summer = seasonalBankColor(base, { r: 50, g: 100, b: 60 }, 0.95)
  const autumn = seasonalBankColor(base, { r: 110, g: 80, b: 50 }, 0.62)
  const winter = seasonalBankColor(base, { r: 90, g: 95, b: 105 }, 0.32)
  const luminance = color => color.r * 0.2126 + color.g * 0.7152 + color.b * 0.0722

  assert.notDeepEqual(summer, autumn)
  assert.notDeepEqual(autumn, winter)
  assert.ok(Math.abs(luminance(base) - luminance(winter)) < 1)
})

test('decorative motion changes canvas strokes without mutating environmental time', () => {
  const a = recorder()
  const paint = createFlowPainter(a.ctx)
  paint(frame, 390, 844, 0)
  const first = [...a.calls]
  a.calls.length = 0
  const instant = frame.instant.toISOString()
  paint(frame, 390, 844, 25)
  assert.notDeepEqual(a.calls, first)
  assert.equal(frame.instant.toISOString(), instant)
})

test('night water keeps visible, moving wave strokes', () => {
  const night = computeEnvironment({ instant: new Date('2026-09-26T18:00:00Z'), location: { latitude: 34, longitude: 109 }, weather: null })
  const { calls, ctx } = recorder()
  const paint = createFlowPainter(ctx)
  const waterPath = () => calls
    .filter(([name, , y]) => (name === 'moveTo' || name === 'lineTo') && y > 650)
    .map(([name, ...point]) => [name, ...point])

  paint(night, 390, 844, 0)
  const firstPath = waterPath()
  const alphas = calls
    .filter(([name, value]) => name === 'strokeStyle' && String(value).startsWith('rgba(255,255,255,'))
    .map(([, value]) => Number(String(value).match(/,([\d.]+)\)$/)?.[1]))
  calls.length = 0
  paint(night, 390, 844, 1.5)

  assert.ok(alphas.length > 0 && Math.min(...alphas) >= 0.149 - 1e-9)
  assert.notDeepEqual(waterPath(), firstPath)
})

test('foreground water has sparse irregular wavelets that move over time', () => {
  const { calls, ctx } = recorder()
  const paint = createFlowPainter(ctx)
  paint(frame, 390, 844, 10)
  const first = calls.filter(([name, , controlY, , endY]) => name === 'quadraticCurveTo' && controlY > 844 * 0.78 && endY > 844 * 0.78)
  calls.length = 0
  paint(frame, 390, 844, 12)
  const later = calls.filter(([name, , controlY, , endY]) => name === 'quadraticCurveTo' && controlY > 844 * 0.78 && endY > 844 * 0.78)
  assert.equal(first.length, 24)
  assert.equal(later.length, 24)
  assert.notDeepEqual(later, first)
})

test('night stars twinkle at independent slow rates without disappearing', () => {
  const night = computeEnvironment({ instant: new Date('2026-09-26T18:00:00Z'), location: { latitude: 34, longitude: 109 }, weather: null })
  const { calls, ctx } = recorder()
  const paint = createFlowPainter(ctx)
  const starAlphas = () => calls
    .filter(([name, value]) => name === 'fillStyle' && String(value).startsWith('rgba(255,255,255,'))
    .map(([, value]) => Number(String(value).match(/,([\d.]+)\)$/)?.[1]))

  paint(night, 390, 844, 0)
  const first = starAlphas()
  calls.length = 0
  paint(night, 390, 844, 8)
  const later = starAlphas()

  assert.equal(first.length, 150)
  assert.equal(later.length, 150)
  assert.ok(first.every(alpha => alpha > 0))
  assert.ok(later.every(alpha => alpha > 0))
  assert.notDeepEqual(later, first)
  assert.ok(new Set(later.map(alpha => alpha.toFixed(3))).size > 20, 'stars do not pulse in sync')
})

test('cloud silhouette uses a varied, softly lobed contour instead of stacked ellipses', () => {
  const { calls, ctx } = recorder()
  traceCloudShape(ctx, 180, 90, 240, 68, 2)
  assert.equal(calls.filter(([method]) => method === 'ellipse').length, 0)
  assert.ok(calls.filter(([method]) => method === 'bezierCurveTo').length >= 5)
  assert.ok(calls.some(([method]) => method === 'closePath'))
})
