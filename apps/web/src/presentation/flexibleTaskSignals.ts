import type { components } from '../../../../contracts/backend-api.d.ts'

export type FlexibleTask = components['schemas']['FlexibleTask']
export type Cue = { taskId: string; expiresAt: number }

/** Owns presentation-only cue expiry. A detail panel is deliberately independent of this map. */
export class FlexibleTaskSignals {
  readonly cues = new Map<string, Cue>()
  private timers = new Map<string, ReturnType<typeof setTimeout>>()
  private readonly now: () => number
  private readonly random: () => number
  private readonly onChange: () => void
  private readonly setTimer: typeof setTimeout
  private readonly clearTimer: typeof clearTimeout

  constructor(
    now: () => number = Date.now,
    random: () => number = Math.random,
    onChange: () => void = () => {},
    setTimer: typeof setTimeout = setTimeout,
    clearTimer: typeof clearTimeout = clearTimeout,
  ) { this.now = now; this.random = random; this.onChange = onChange; this.setTimer = setTimer; this.clearTimer = clearTimer }

  show(taskId: string): Cue {
    this.remove(taskId)
    const lifetime = 300_000 + Math.floor(Math.min(0.999999, Math.max(0, this.random())) * 300_001)
    const cue = { taskId, expiresAt: this.now() + lifetime }
    this.cues.set(taskId, cue)
    this.timers.set(taskId, this.setTimer(() => {
      this.cues.delete(taskId)
      this.timers.delete(taskId)
      this.onChange()
    }, lifetime))
    this.onChange()
    return cue
  }

  remove(taskId: string): void {
    const timer = this.timers.get(taskId)
    if (timer !== undefined) this.clearTimer(timer)
    this.timers.delete(taskId)
    if (this.cues.delete(taskId)) this.onChange()
  }

  clear(): void {
    for (const timer of this.timers.values()) this.clearTimer(timer)
    this.timers.clear()
    if (this.cues.size) { this.cues.clear(); this.onChange() }
  }

  expireDue(): void {
    for (const [taskId, cue] of this.cues) if (cue.expiresAt <= this.now()) this.remove(taskId)
  }

  dispose(): void { this.clear() }
}

export function eligibleFlexibleTasks(tasks: FlexibleTask[], cuedIds: Set<string>): FlexibleTask[] {
  return tasks.filter(task => task.lifecycle_status === 'planned' && !cuedIds.has(task.task_id))
}

/** Active tasks are durable scene signals restored from each server task snapshot. */
export function activeFlexibleTasks(tasks: FlexibleTask[]): FlexibleTask[] {
  return tasks.filter(task => task.lifecycle_status === 'active')
}
