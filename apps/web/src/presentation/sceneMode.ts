export type SceneMode = 'free' | 'work'

export function reminderUrgency(minutesUntilStart: number): number {
  if (!Number.isFinite(minutesUntilStart)) return 0
  return Math.min(1, Math.max(0, (5 - minutesUntilStart) / 5))
}

/** Active schedule facts change the scene mood automatically; no user mode toggle exists. */
export function sceneModeForActiveCount(activeCount: number): SceneMode {
  return activeCount > 0 ? 'work' : 'free'
}
