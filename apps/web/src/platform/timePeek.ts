import { RealClock } from './clocks.ts'

export type TimePeekState = { visible: boolean; time: string; x: number; y: number }
export type ClockSource = { now(): Date }
type TimerHost = { setTimeout(callback: () => void, delay: number): unknown; clearTimeout(handle: unknown): void }

const HOLD_DELAY_MS = 600
const DISPLAY_DURATION_MS = 3000
const POSITION_TOLERANCE_PX = 10

function browserTimers(): TimerHost {
  return {
    setTimeout: (callback, delay) => window.setTimeout(callback, delay),
    clearTimeout: handle => window.clearTimeout(handle as number),
  }
}

function localTime(date: Date): string {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

/** A temporary, read-only time peek. It never mutates schedule or assistant state. */
export class TimePeekController {
  private readonly clock: ClockSource
  private readonly onChange: (state: TimePeekState) => void
  private readonly timers: TimerHost
  private activePointer: number | null = null
  private origin: { x: number; y: number } | null = null
  private holdTimer: unknown = null
  private expiryTimer: unknown = null
  private refreshTimer: unknown = null
  private state: TimePeekState = { visible: false, time: '', x: 0, y: 0 }

  constructor(
    clock: ClockSource = new RealClock(),
    onChange: (state: TimePeekState) => void = () => {},
    timers?: TimerHost,
  ) {
    this.clock = clock
    this.onChange = onChange
    this.timers = timers ?? browserTimers()
  }

  pointerDown(pointerId: number, x: number, y: number, eligible = true): void {
    if (this.activePointer !== null) {
      if (this.activePointer !== pointerId) this.cancelPendingPress()
      return
    }
    if (!eligible) return
    this.activePointer = pointerId
    this.origin = { x, y }
    this.clearTimer('holdTimer')
    this.holdTimer = this.timers.setTimeout(() => {
      this.holdTimer = null
      this.reveal()
    }, HOLD_DELAY_MS)
  }

  pointerMove(pointerId: number, x: number, y: number): void {
    if (pointerId !== this.activePointer || !this.origin || this.holdTimer === null) return
    const dx = x - this.origin.x
    const dy = y - this.origin.y
    if (dx * dx + dy * dy > POSITION_TOLERANCE_PX * POSITION_TOLERANCE_PX) this.cancelPendingPress()
  }

  pointerUp(pointerId: number): void {
    if (pointerId !== this.activePointer) return
    this.cancelPendingPress()
  }

  cancelAll(): void {
    this.cancelPendingPress()
    this.clearTimer('expiryTimer')
    this.clearTimer('refreshTimer')
    if (this.state.visible) {
      this.state = { ...this.state, visible: false }
      this.onChange(this.state)
    }
  }

  dispose(): void {
    this.cancelAll()
  }

  private reveal(): void {
    const anchor = this.origin ?? { x: 0, y: 0 }
    this.state = { visible: true, time: localTime(this.clock.now()), ...anchor }
    this.onChange(this.state)
    this.clearTimer('expiryTimer')
    this.clearTimer('refreshTimer')
    this.expiryTimer = this.timers.setTimeout(() => {
      this.expiryTimer = null
      this.hide()
    }, DISPLAY_DURATION_MS)
    this.refreshTimer = this.timers.setTimeout(() => this.refresh(), 1000)
  }

  private refresh(): void {
    this.refreshTimer = null
    if (!this.state.visible) return
    this.state = { ...this.state, visible: true, time: localTime(this.clock.now()) }
    this.onChange(this.state)
    this.refreshTimer = this.timers.setTimeout(() => this.refresh(), 1000)
  }

  private hide(): void {
    this.clearTimer('refreshTimer')
    if (!this.state.visible) return
    this.state = { ...this.state, visible: false }
    this.onChange(this.state)
  }

  private cancelPendingPress(): void {
    this.clearTimer('holdTimer')
    this.activePointer = null
    this.origin = null
  }

  private clearTimer(key: 'holdTimer' | 'expiryTimer' | 'refreshTimer'): void {
    const handle = this[key]
    if (handle !== null) this.timers.clearTimeout(handle)
    this[key] = null
  }
}

const INTERACTIVE_TARGET = 'button, a, input, textarea, select, [contenteditable="true"], [data-time-peek-ignore], .assistant-panel, .reminder-state'

/** Wire a scene surface to the same time peek without making its canvas interactive. */
export function bindTimePeek(surface: HTMLElement, output: HTMLElement, clock: ClockSource = new RealClock()): () => void {
  const controller = new TimePeekController(clock, state => {
    output.textContent = state.time
    if (state.visible) {
      const { width, height } = output.getBoundingClientRect()
      const margin = 12
      const gap = 16
      const x = Math.max(width / 2 + margin, Math.min(window.innerWidth - width / 2 - margin, state.x))
      const showAbove = state.y - gap - height >= margin
      const y = showAbove ? state.y - gap : state.y + gap
      const boundedY = showAbove
        ? Math.max(height + margin, Math.min(window.innerHeight - margin, y))
        : Math.max(margin, Math.min(window.innerHeight - height - margin, y))
      output.style.setProperty('--time-peek-x', `${x}px`)
      output.style.setProperty('--time-peek-y', `${boundedY}px`)
      output.dataset.placement = showAbove ? 'above' : 'below'
    }
    output.classList.toggle('is-visible', state.visible)
    output.setAttribute('aria-hidden', String(!state.visible))
  })

  const eligibleTarget = (target: EventTarget | null) => {
    if (!(target instanceof Element)) return false
    return !target.closest(INTERACTIVE_TARGET)
  }
  const pointerDown = (event: PointerEvent) => {
    if (!event.isPrimary) {
      controller.pointerDown(event.pointerId, event.clientX, event.clientY, false)
      return
    }
    if (event.button !== 0) return
    controller.pointerDown(event.pointerId, event.clientX, event.clientY, eligibleTarget(event.target))
  }
  const pointerMove = (event: PointerEvent) => controller.pointerMove(event.pointerId, event.clientX, event.clientY)
  const pointerUp = (event: PointerEvent) => controller.pointerUp(event.pointerId)
  const cancel = () => controller.cancelAll()
  const visibility = () => { if (document.visibilityState !== 'visible') cancel() }
  const contextMenu = (event: MouseEvent) => { if (eligibleTarget(event.target)) event.preventDefault() }

  surface.addEventListener('pointerdown', pointerDown)
  surface.addEventListener('contextmenu', contextMenu)
  window.addEventListener('pointermove', pointerMove)
  window.addEventListener('pointerup', pointerUp)
  window.addEventListener('pointercancel', pointerUp)
  window.addEventListener('blur', cancel)
  window.addEventListener('scroll', cancel, true)
  document.addEventListener('visibilitychange', visibility)

  return () => {
    surface.removeEventListener('pointerdown', pointerDown)
    surface.removeEventListener('contextmenu', contextMenu)
    window.removeEventListener('pointermove', pointerMove)
    window.removeEventListener('pointerup', pointerUp)
    window.removeEventListener('pointercancel', pointerUp)
    window.removeEventListener('blur', cancel)
    window.removeEventListener('scroll', cancel, true)
    document.removeEventListener('visibilitychange', visibility)
    controller.dispose()
  }
}
