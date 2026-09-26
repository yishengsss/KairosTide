/** The time shown by a deliberate time peek always comes from the device clock. */
export class RealClock {
  now(): Date {
    return new Date()
  }
}

/** A private timeline for scenery previews. Never use it for time peeks or schedules. */
export class SceneClock {
  private readonly originElapsed: number
  private readonly origin: Date
  private readonly monotonicNow: () => number
  private readonly speed: number

  constructor(
    origin: Date = new Date(),
    monotonicNow: () => number = () => performance.now(),
    speed = 1,
  ) {
    if (!Number.isFinite(speed) || speed < 0) throw new RangeError('Scene speed must be nonnegative')
    this.origin = new Date(origin.getTime())
    this.monotonicNow = monotonicNow
    this.speed = speed
    this.originElapsed = monotonicNow()
  }

  now(): Date {
    return new Date(this.origin.getTime() + (this.monotonicNow() - this.originElapsed) * this.speed)
  }
}
