import { reactive } from 'vue'
import type { components } from '../../../../contracts/backend-api.d.ts'
import type { EnvironmentFrame, WeatherResponse } from './environment.ts'
import { SceneEnvironmentSession } from './session.ts'

export type WeatherPlaceChoice = components['schemas']['WeatherPlaceChoice']
export interface SceneWeatherQuery { city: string; choice?: WeatherPlaceChoice }
export interface SceneWeatherGateway { query(request: SceneWeatherQuery): Promise<WeatherResponse> }

export interface SceneWeatherState {
  status: 'idle' | 'loading' | 'available' | 'stale' | 'ambiguous' | 'unavailable'
  city: string | null
  label: string | null
  source: string | null
  attribution: string | null
  fetchedAt: string | null
  detail: string | null
  choices: WeatherPlaceChoice[]
}

/** Weather only changes after an explicit scene-location selection. AI weather queries use another path. */
export class SceneWeatherController {
  readonly state = reactive<SceneWeatherState>({
    status: 'idle', city: null, label: null, source: null, attribution: null,
    fetchedAt: null, detail: null, choices: [],
  })
  private selection: WeatherPlaceChoice | undefined
  private selectedCoordinates: { latitude: number; longitude: number } | null = null
  private requestNumber = 0
  private nextRefreshAt = Number.POSITIVE_INFINITY
  private readonly session: SceneEnvironmentSession
  private readonly gateway: SceneWeatherGateway
  private readonly onFrame?: (frame: EnvironmentFrame) => void

  constructor(
    session: SceneEnvironmentSession,
    gateway: SceneWeatherGateway,
    onFrame?: (frame: EnvironmentFrame) => void,
  ) {
    this.session = session
    this.gateway = gateway
    this.onFrame = onFrame
  }

  async setCity(city: string): Promise<void> {
    const clean = city.trim()
    if (!clean) throw new RangeError('请先输入城市')
    this.selection = undefined
    this.selectedCoordinates = null
    this.state.city = clean
    this.state.label = null
    this.state.choices = []
    this.clearScene()
    await this.fetchSelected()
  }

  async selectChoice(choice: WeatherPlaceChoice): Promise<void> {
    const match = this.state.choices.find((item) =>
      item.name === choice.name && item.latitude === choice.latitude && item.longitude === choice.longitude &&
      item.timezone === choice.timezone && item.admin1 === choice.admin1 && item.country === choice.country)
    if (!this.state.city || !match) throw new RangeError('请从当前地点候选中选择')
    this.selection = match
    this.state.choices = []
    await this.fetchSelected()
  }

  clear(): void {
    this.requestNumber++
    this.selection = undefined
    this.selectedCoordinates = null
    this.nextRefreshAt = Number.POSITIVE_INFINITY
    Object.assign(this.state, { status: 'idle', city: null, label: null, source: null,
      attribution: null, fetchedAt: null, detail: null, choices: [] })
    this.clearScene()
  }

  async maybeRefresh(now = Date.now()): Promise<void> {
    if (!this.state.city || this.state.status === 'loading' || this.state.status === 'ambiguous' || now < this.nextRefreshAt) return
    await this.fetchSelected()
  }

  private async fetchSelected(): Promise<void> {
    const city = this.state.city
    if (!city) return
    const requestNumber = ++this.requestNumber
    this.state.status = 'loading'
    this.state.detail = null
    try {
      const result = await this.gateway.query({ city, choice: this.selection })
      if (requestNumber !== this.requestNumber) return
      this.state.source = result.source
      this.state.attribution = result.attribution ?? null
      this.state.fetchedAt = result.fetched_at
      this.state.detail = result.detail ?? null
      const choices = result.location_choices ?? []
      if (choices.length && result.availability === 'unavailable') {
        this.state.status = 'ambiguous'
        this.state.choices = choices
        this.state.label = null
        this.nextRefreshAt = Number.POSITIVE_INFINITY
        this.clearScene()
        return
      }
      const latitude = result.latitude
      const longitude = result.longitude
      const validPlace = typeof latitude === 'number' && typeof longitude === 'number' &&
        Number.isFinite(latitude) && Number.isFinite(longitude) &&
        Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180
      if (validPlace) this.selectedCoordinates = { latitude: latitude!, longitude: longitude! }
      const current = result.observations.find((item) => item.kind === 'current')
      if (result.availability !== 'available' || !validPlace || !current) {
        this.state.status = result.availability === 'stale' ? 'stale' : 'unavailable'
        this.state.label = null
        this.nextRefreshAt = this.session.frame.instant.getTime() + 5 * 60_000
        this.clearWeatherKeepSolarPath()
        return
      }
      this.state.status = 'available'
      this.state.label = result.location_label ?? city
      this.state.choices = []
      this.nextRefreshAt = this.session.frame.instant.getTime() + 15 * 60_000
      const frame = this.session.setInputs(this.selectedCoordinates, result)
      this.onFrame?.(frame)
    } catch {
      if (requestNumber !== this.requestNumber) return
      this.state.status = 'unavailable'
      this.state.detail = '天气服务暂时不可用，可稍后重试。'
      this.state.label = null
      this.nextRefreshAt = this.session.frame.instant.getTime() + 5 * 60_000
      this.clearWeatherKeepSolarPath()
    }
  }

  private clearScene(): void {
    const frame = this.session.setInputs(null, null)
    this.onFrame?.(frame)
  }

  private clearWeatherKeepSolarPath(): void {
    const frame = this.session.setInputs(this.selectedCoordinates, null)
    this.onFrame?.(frame)
  }
}
