import type { components } from '../../../../contracts/backend-api.d.ts'
import { paletteFor, type ScenePalette } from './palette.ts'
import { solarPosition, type SolarLocation, type SunPosition } from './solar.ts'

export type WeatherResponse = components['schemas']['WeatherResponse']
export type WeatherCondition = NonNullable<components['schemas']['WeatherObservation']['condition']>

export interface EnvironmentInput {
  instant: Date
  location: SolarLocation | null
  weather: WeatherResponse | null
  /** A controlled preview may supply its own continuous annual fraction. */
  season?: number
}

export interface EnvironmentFrame {
  instant: Date
  sun: SunPosition
  moon: { screenX: number; screenY: number; opacity: number }
  season: { progress: number; warmth: number }
  atmosphere: {
    availability: WeatherResponse['availability']
    condition: WeatherCondition | null
    cloud: number
    transmission: number
    rain: number
    snow: number
    fog: number
    visibility: number
    stars: number
  }
  palette: ScenePalette
  water: { reflectedLight: number; ripple: number; glintX: number }
}

const clamp = (value: number, low = 0, high = 1) => Math.min(high, Math.max(low, value))
const smoothstep = (edge0: number, edge1: number, value: number) => {
  const t = clamp((value - edge0) / (edge1 - edge0))
  return t * t * (3 - 2 * t)
}

function annualProgress(instant: Date): number {
  const year = instant.getUTCFullYear()
  return (instant.getTime() - Date.UTC(year, 0, 1)) / (Date.UTC(year + 1, 0, 1) - Date.UTC(year, 0, 1))
}

export function computeEnvironment({ instant, location, weather, season }: EnvironmentInput): EnvironmentFrame {
  const sun = solarPosition(instant, location)
  const progress = season === undefined ? annualProgress(instant) : ((season % 1) + 1) % 1
  const hemisphere = location?.latitude !== undefined && location.latitude < 0 ? -1 : 1
  const warmth = hemisphere * Math.cos(2 * Math.PI * (progress - 0.47))

  const current = weather?.observations.find((item) => item.kind === 'current') ?? null
  const isExpired = !!current?.valid_until && Date.parse(current.valid_until) < instant.getTime()
  const availability = !weather || !current ? 'unavailable' : isExpired ? 'stale' : weather.availability
  const condition = availability === 'unavailable' ? null : (current?.condition ?? null)
  const cover = current?.cloud_cover
  const cloudFromSource = typeof cover === 'number' && Number.isFinite(cover)
    ? clamp(cover > 1 ? cover / 100 : cover)
    : null
  const inferredCloud: Record<WeatherCondition, number> = {
    clear: 0.04, partly_cloudy: 0.36, overcast: 0.86, rain: 0.9, fog: 0.7, snow: 0.78,
  }
  const cloud = condition ? Math.max(cloudFromSource ?? 0, inferredCloud[condition]) : 0.3
  const rain = condition === 'rain' ? 0.7 : 0
  const snow = condition === 'snow' ? 0.65 : 0
  const fog = condition === 'fog' ? 0.8 : 0
  const transmission = clamp(1 - cloud * 0.72 - fog * 0.12 - rain * 0.07, 0.1, 1)
  const day = smoothstep(-10, 5, sun.elevationDeg)
  const night = 1 - smoothstep(-16, -3, sun.elevationDeg)
  const palette = paletteFor(sun.elevationDeg, transmission, warmth, snow)

  return {
    instant: new Date(instant.getTime()), sun,
    moon: {
      screenX: 100 - sun.screenX,
      screenY: clamp(18 + 15 * Math.cos(sun.hourAngleDeg * Math.PI / 180), 8, 42),
      opacity: night * (1 - cloud * 0.8),
    },
    season: { progress, warmth },
    atmosphere: {
      availability, condition, cloud, transmission, rain, snow, fog,
      visibility: 1 - fog * 0.72,
      stars: night * (1 - cloud * 0.9),
    },
    palette,
    water: {
      reflectedLight: day * transmission,
      ripple: rain * 0.8 + snow * 0.12,
      glintX: sun.screenX,
    },
  }
}
