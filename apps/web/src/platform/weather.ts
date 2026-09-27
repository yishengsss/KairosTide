import type { WeatherResponse } from '../scene/environment.ts'
import type { SceneWeatherGateway, SceneWeatherQuery } from '../scene/weatherController.ts'

const conditions = new Set(['clear', 'partly_cloudy', 'overcast', 'rain', 'fog', 'snow'])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isWeatherResponse(value: unknown): value is WeatherResponse {
  if (!isRecord(value) || !['available', 'stale', 'unavailable'].includes(String(value.availability)) ||
      typeof value.location_id !== 'string' || !Array.isArray(value.observations)) return false
  if (value.latitude != null && (typeof value.latitude !== 'number' || !Number.isFinite(value.latitude) || Math.abs(value.latitude) > 90)) return false
  if (value.longitude != null && (typeof value.longitude !== 'number' || !Number.isFinite(value.longitude) || Math.abs(value.longitude) > 180)) return false
  if (value.location_choices != null && (!Array.isArray(value.location_choices) || !value.location_choices.every((choice) =>
    isRecord(choice) && typeof choice.name === 'string' && typeof choice.timezone === 'string' &&
    typeof choice.latitude === 'number' && Number.isFinite(choice.latitude) && Math.abs(choice.latitude) <= 90 &&
    typeof choice.longitude === 'number' && Number.isFinite(choice.longitude) && Math.abs(choice.longitude) <= 180))) return false
  return value.observations.every((item) => isRecord(item) &&
    (item.kind === 'current' || item.kind === 'forecast') &&
    (item.condition === null || conditions.has(String(item.condition))) &&
    (item.cloud_cover === null || typeof item.cloud_cover === 'number') &&
    (item.valid_until === null || typeof item.valid_until === 'string'))
}

/** Browser adapter for user-selected scene weather. The scene itself never performs HTTP. */
export function createSceneWeatherGateway(fetcher: typeof fetch = fetch): SceneWeatherGateway {
  return {
    async query(request: SceneWeatherQuery): Promise<WeatherResponse> {
      const params = new URLSearchParams({ location_id: request.city })
      if (request.choice) {
        params.set('selected_latitude', String(request.choice.latitude))
        params.set('selected_longitude', String(request.choice.longitude))
        params.set('selected_timezone', request.choice.timezone)
        params.set('selected_name', request.choice.name)
        if (request.choice.country) params.set('selected_country', request.choice.country)
        if (request.choice.admin1) params.set('selected_admin1', request.choice.admin1)
      }
      const response = await fetcher(`/api/v1/weather?${params}`, { cache: 'no-store' })
      if (!response.ok) throw new Error(`Weather HTTP ${response.status}`)
      const value: unknown = await response.json()
      if (!isWeatherResponse(value)) throw new Error('Invalid weather response')
      return value
    },
  }
}
