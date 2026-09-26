import { RealClock } from '../platform/clocks.ts'
import { computeEnvironment, type EnvironmentFrame, type WeatherResponse } from './environment.ts'
import type { SolarLocation } from './solar.ts'

export interface SceneTimeSource {
  now(): Date
}

/** Maintains the ambient environment from real time and explicit read-only inputs. */
export class SceneEnvironmentSession {
  frame: EnvironmentFrame
  private readonly clock: SceneTimeSource
  private readonly location: SolarLocation | null
  private readonly weather: WeatherResponse | null

  constructor(
    clock: SceneTimeSource = new RealClock(),
    location: SolarLocation | null = null,
    weather: WeatherResponse | null = null,
  ) {
    this.clock = clock
    this.location = location
    this.weather = weather
    this.frame = this.readFrame()
  }

  refresh(): EnvironmentFrame {
    this.frame = this.readFrame()
    return this.frame
  }

  private readFrame(): EnvironmentFrame {
    return computeEnvironment({ instant: this.clock.now(), location: this.location, weather: this.weather })
  }
}
