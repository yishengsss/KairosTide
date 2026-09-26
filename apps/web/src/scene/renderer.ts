import type { EnvironmentFrame } from './environment.ts'
import type { RGB } from './palette.ts'

const rgb = ({ r, g, b }: RGB) => `rgb(${r} ${g} ${b})`
const fraction = (value: number) => String(Math.max(0, Math.min(1, value)))

/** CSS is driven by a single immutable frame; no date or weather lookup occurs here. */
export function sceneStyle(frame: EnvironmentFrame): Record<string, string> {
  const elevation = frame.sun.elevationDeg
  const dawnLift = Math.max(0, Math.min(1, (elevation + 9) / 11))
  const dayFade = 1 - Math.max(0, Math.min(1, (elevation - 4) / 12))
  return {
    '--sky-zenith': rgb(frame.palette.skyZenith),
    '--sky-horizon': rgb(frame.palette.skyHorizon),
    '--mountain-far': rgb(frame.palette.mountainFar),
    '--mountain-mid': rgb(frame.palette.mountainMid),
    '--mountain-near': rgb(frame.palette.mountainNear),
    '--mountain-light': rgb(frame.palette.mountainLight),
    '--water': rgb(frame.palette.water),
    '--shore': rgb(frame.palette.shore),
    '--sun-x': `${frame.sun.screenX}%`,
    '--sun-y': `${frame.sun.screenY}%`,
    '--sun-opacity': fraction((frame.sun.elevationDeg + 5) / 9 * frame.atmosphere.transmission ** 2),
    '--moon-x': `${frame.moon.screenX}%`,
    '--moon-y': `${frame.moon.screenY}%`,
    '--moon-opacity': fraction(frame.moon.opacity),
    '--star-opacity': fraction(frame.atmosphere.stars),
    '--cloud-opacity': fraction(frame.atmosphere.cloud * 0.83),
    '--weather-veil-opacity': fraction(Math.max(0, frame.atmosphere.cloud - 0.35) * 0.72),
    '--weather-veil-color': frame.atmosphere.condition === 'snow' ? '#b8c3c4' : frame.atmosphere.condition === 'fog' ? '#c5d0d2' : frame.atmosphere.condition === 'rain' ? '#425768' : '#687781',
    '--fog-opacity': fraction(frame.atmosphere.fog * 0.68),
    '--rain-opacity': fraction(frame.atmosphere.rain * 0.42),
    '--snow-opacity': fraction(frame.atmosphere.snow * 0.68),
    '--glint-opacity': fraction(frame.water.reflectedLight * 0.78),
    '--glint-x': `${frame.water.glintX}%`,
    '--visibility': fraction(frame.atmosphere.visibility),
    '--bird-opacity': fraction(dawnLift * dayFade),
  }
}

export function shouldAnimateScene(frame: EnvironmentFrame, reducedMotion: boolean, visible: boolean): boolean {
  return !reducedMotion && visible && (frame.atmosphere.rain > 0 || frame.atmosphere.snow > 0 || frame.water.reflectedLight > 0.05)
}

export interface WaterGlint {
  x1: number
  x2: number
  y: number
  alpha: number
}

/** Break reflected sunlight into irregular, depth-scaled ripples. */
export function waterGlints(frame: EnvironmentFrame, width: number, height: number, seconds: number): WaterGlint[] {
  const light = frame.water.reflectedLight
  if (light <= 0.05 || width <= 0 || height <= 0) return []
  const lakeTop = height * 0.63
  const lightX = width * frame.water.glintX / 100
  const count = Math.round(50 * light)
  const glints: WaterGlint[] = []
  for (let index = 0; index < count; index += 1) {
    const depth = (index + 0.4) / count
    const row = Math.sin(index * 11.73 + seconds * 0.31) * height * 0.0025
    const y = lakeTop + depth * height * 0.31 + row
    const reach = width * (0.004 + depth ** 1.55 * 0.13) * light
    const pieces = 1 + index % 3
    for (let piece = 0; piece < pieces; piece += 1) {
      const seed = index * 17.17 + piece * 29.31
      const center = lightX + Math.sin(seed + seconds * 0.08) * reach * 0.78
      const length = reach * (0.1 + ((index * 13 + piece * 7) % 17) / 32)
      glints.push({
        x1: Math.max(0, center - length / 2),
        x2: Math.min(width, center + length / 2),
        y,
        alpha: 0.1 + light * (0.13 + ((index + piece * 3) % 5) * 0.025),
      })
    }
  }
  return glints
}

export interface AmbientRenderer {
  refresh(): void
  destroy(): void
}

/** Local decorative marks only; astronomy and CSS palette remain in the parent frame. */
export function mountAmbientRenderer(
  canvas: HTMLCanvasElement,
  getFrame: () => EnvironmentFrame,
  getReducedMotion: () => boolean,
): AmbientRenderer {
  const context = canvas.getContext('2d')
  if (!context) return { refresh() {}, destroy() {} }
  let animationId = 0
  let previousPaint = 0
  let destroyed = false

  function resize() {
    const rect = canvas.getBoundingClientRect()
    const scale = Math.min(window.devicePixelRatio || 1, 2)
    const width = Math.max(1, Math.round(rect.width * scale))
    const height = Math.max(1, Math.round(rect.height * scale))
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
    }
  }

  function paint(time: number) {
    if (!context || destroyed) return
    resize()
    const frame = getFrame()
    const width = canvas.width
    const height = canvas.height
    context.clearRect(0, 0, width, height)
    const motion = getReducedMotion() ? 0 : time / 1000
    const rainCount = Math.round(frame.atmosphere.rain * Math.min(66, width / 14))
    const snowCount = Math.round(frame.atmosphere.snow * Math.min(54, width / 18))
    const lakeTop = height * 0.6

    if (rainCount) {
      context.strokeStyle = 'rgba(218, 237, 245, 0.36)'
      context.lineWidth = Math.max(1, width / 1200)
      context.beginPath()
      for (let i = 0; i < rainCount; i += 1) {
        const x = (((i * 0.61803398875 + motion * 0.17) % 1) + 1) % 1 * width
        const y = (((i * 0.41421356237 + motion * (0.48 + i % 3 * 0.07)) % 1) + 1) % 1 * height
        context.moveTo(x, y)
        context.lineTo(x - width * 0.004, y + height * 0.027)
      }
      context.stroke()
    }
    if (snowCount) {
      context.fillStyle = 'rgba(246, 250, 249, 0.78)'
      for (let i = 0; i < snowCount; i += 1) {
        const x = (((i * 0.754877666 + motion * (0.008 + i % 4 * 0.003)) % 1) + 1) % 1 * width
        const y = (((i * 0.569840291 + motion * (0.03 + i % 3 * 0.006)) % 1) + 1) % 1 * height
        context.beginPath()
        context.arc(x, y, Math.max(1.5, width / 650 * (1 + i % 2)), 0, Math.PI * 2)
        context.fill()
      }
    }
    if (frame.water.reflectedLight > 0.05) {
      context.strokeStyle = 'rgba(255, 246, 216, 1)'
      context.lineWidth = Math.max(1, height / 1050)
      for (const glint of waterGlints(frame, width, height, motion)) {
        context.globalAlpha = glint.alpha
        context.beginPath()
        context.moveTo(glint.x1, glint.y)
        context.lineTo(glint.x2, glint.y)
        context.stroke()
      }
      context.globalAlpha = 1
    }
    if (frame.water.ripple > 0.1) {
      context.strokeStyle = `rgba(209, 228, 229, ${0.08 + frame.water.ripple * 0.16})`
      context.lineWidth = Math.max(1, width / 1400)
      context.beginPath()
      for (let i = 0; i < 34; i += 1) {
        const x = (((i * 0.754877666 + motion * 0.01) % 1) + 1) % 1 * width
        const y = lakeTop + ((i * 0.61803398875) % 1) * height * 0.36
        const radius = width * (0.003 + ((motion * 0.22 + i * 0.13) % 1) * 0.011)
        context.moveTo(x + radius, y)
        context.ellipse(x, y, radius, radius * 0.21, 0, 0, Math.PI * 2)
      }
      context.stroke()
    }
  }

  function tick(time: number) {
    if (destroyed) return
    const animate = shouldAnimateScene(getFrame(), getReducedMotion(), !document.hidden)
    if (!animate) {
      animationId = 0
      paint(time)
      return
    }
    if (time - previousPaint >= 33) {
      paint(time)
      previousPaint = time
    }
    animationId = requestAnimationFrame(tick)
  }

  function refresh() {
    if (destroyed) return
    if (animationId) cancelAnimationFrame(animationId)
    animationId = requestAnimationFrame(tick)
  }

  const observer = new ResizeObserver(refresh)
  observer.observe(canvas)
  document.addEventListener('visibilitychange', refresh)
  refresh()
  return {
    refresh,
    destroy() {
      destroyed = true
      if (animationId) cancelAnimationFrame(animationId)
      observer.disconnect()
      document.removeEventListener('visibilitychange', refresh)
      context.clearRect(0, 0, canvas.width, canvas.height)
    },
  }
}
