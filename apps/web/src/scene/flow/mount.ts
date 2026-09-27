import type { EnvironmentFrame } from '../environment.ts'
import { createFlowPainter } from './painter.ts'

/** One canvas and one animation loop; callers own real-time environment inputs. */
export function mountFlow(canvas: HTMLCanvasElement, getFrame: () => EnvironmentFrame, onWaterlineAt?: (waterlineAt: (x: number) => number) => void) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return { refresh() {}, destroy() {} }
  const paint = createFlowPainter(ctx)
  const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
  let request = 0, previous = 0, elapsed = 0, disposed = false
  function draw(timestamp: number) {
    request = 0
    if (disposed || document.hidden) { previous = 0; return }
    if (!previous || timestamp - previous >= 1000 / 30) {
      const delta = previous ? Math.min(timestamp - previous, 100) / 1000 : 0
      previous = timestamp
      if (!preference.matches) elapsed += delta
      const bounds = canvas.getBoundingClientRect()
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      const width = Math.max(1, Math.round(bounds.width * ratio))
      const height = Math.max(1, Math.round(bounds.height * ratio))
      if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height }
      ctx!.setTransform(ratio, 0, 0, ratio, 0, 0)
      const waterlineAt = paint(getFrame(), bounds.width, bounds.height, elapsed)
      onWaterlineAt?.(waterlineAt)
    }
    if (!preference.matches) request = requestAnimationFrame(draw)
  }
  function refresh() {
    if (disposed) return
    if (request) cancelAnimationFrame(request)
    previous = 0
    request = requestAnimationFrame(draw)
  }
  const observer = new ResizeObserver(refresh)
  observer.observe(canvas)
  preference.addEventListener('change', refresh)
  document.addEventListener('visibilitychange', refresh)
  refresh()
  return {
    refresh,
    destroy() {
      disposed = true
      cancelAnimationFrame(request)
      observer.disconnect()
      preference.removeEventListener('change', refresh)
      document.removeEventListener('visibilitychange', refresh)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
    },
  }
}
