export interface WaterTapPoint { x: number; y: number }

interface Press {
  pointerId: number
  x: number
  y: number
  at: number
}

const MAX_TAP_DURATION_MS = 600
const MAX_MOVEMENT_PX = 10

/** Recognizes a short, nearly stationary press without consuming the scene gesture. */
export class WaterTapController {
  private press: Press | null = null

  pointerDown(pointerId: number, x: number, y: number, at: number, eligible = true): void {
    if (this.press) {
      if (this.press.pointerId !== pointerId) this.press = null
      return
    }
    if (eligible) this.press = { pointerId, x, y, at }
  }

  pointerMove(pointerId: number, x: number, y: number): void {
    if (!this.press || this.press.pointerId !== pointerId) return
    if (this.movedTooFar(x, y)) this.press = null
  }

  pointerUp(pointerId: number, x: number, y: number, at: number): WaterTapPoint | null {
    const press = this.press
    this.press = null
    if (!press || press.pointerId !== pointerId) return null
    if (at - press.at < 0 || at - press.at >= MAX_TAP_DURATION_MS || this.movedTooFar(x, y, press)) return null
    return { x, y }
  }

  cancel(): void { this.press = null }

  private movedTooFar(x: number, y: number, press = this.press!): boolean {
    const dx = x - press.x
    const dy = y - press.y
    return dx * dx + dy * dy > MAX_MOVEMENT_PX * MAX_MOVEMENT_PX
  }
}
