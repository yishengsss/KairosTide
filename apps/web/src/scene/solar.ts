export interface SolarLocation {
  latitude: number
  longitude: number
}

export interface SunPosition {
  elevationDeg: number
  azimuthDeg: number
  hourAngleDeg: number
  screenX: number
  screenY: number
  accuracy: 'location_based_approximation' | 'local_clock_approximation'
}

const RAD = Math.PI / 180
const DEG = 180 / Math.PI
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))

/** NOAA fractional-year solar approximation, evaluated from the UTC instant. */
export function solarPosition(instant: Date, location: SolarLocation | null): SunPosition {
  if (!Number.isFinite(instant.getTime())) throw new RangeError('Invalid instant')
  let hourAngleDeg: number
  let elevationDeg: number
  let azimuthDeg: number
  let accuracy: SunPosition['accuracy']

  if (location) {
    const { latitude, longitude } = location
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) {
      throw new RangeError('Invalid geographic coordinates')
    }
    const year = instant.getUTCFullYear()
    const dayOfYear = Math.floor((Date.UTC(year, instant.getUTCMonth(), instant.getUTCDate()) - Date.UTC(year, 0, 1)) / 86_400_000) + 1
    const daysInYear = (Date.UTC(year + 1, 0, 1) - Date.UTC(year, 0, 1)) / 86_400_000
    const utcHour = instant.getUTCHours() + instant.getUTCMinutes() / 60 + instant.getUTCSeconds() / 3600 + instant.getUTCMilliseconds() / 3_600_000
    const gamma = 2 * Math.PI / daysInYear * (dayOfYear - 1 + (utcHour - 12) / 24)
    const equationMinutes = 229.18 * (0.000075 + 0.001868 * Math.cos(gamma) - 0.032077 * Math.sin(gamma) - 0.014615 * Math.cos(2 * gamma) - 0.040849 * Math.sin(2 * gamma))
    const declination = 0.006918 - 0.399912 * Math.cos(gamma) + 0.070257 * Math.sin(gamma) - 0.006758 * Math.cos(2 * gamma) + 0.000907 * Math.sin(2 * gamma) - 0.002697 * Math.cos(3 * gamma) + 0.00148 * Math.sin(3 * gamma)
    const solarMinutes = utcHour * 60 + equationMinutes + 4 * longitude
    hourAngleDeg = ((solarMinutes / 4) % 360 + 360) % 360 - 180
    const lat = latitude * RAD
    const hourAngle = hourAngleDeg * RAD
    elevationDeg = Math.asin(clamp(Math.sin(lat) * Math.sin(declination) + Math.cos(lat) * Math.cos(declination) * Math.cos(hourAngle), -1, 1)) * DEG
    azimuthDeg = ((Math.atan2(Math.sin(hourAngle), Math.cos(hourAngle) * Math.sin(lat) - Math.tan(declination) * Math.cos(lat)) * DEG + 180) + 360) % 360
    accuracy = 'location_based_approximation'
  } else {
    const localHour = instant.getHours() + instant.getMinutes() / 60 + instant.getSeconds() / 3600 + instant.getMilliseconds() / 3_600_000
    hourAngleDeg = (localHour - 12) * 15
    elevationDeg = -5 + 60 * Math.cos(hourAngleDeg * RAD)
    azimuthDeg = ((180 + hourAngleDeg) % 360 + 360) % 360
    accuracy = 'local_clock_approximation'
  }

  return {
    elevationDeg,
    azimuthDeg,
    hourAngleDeg,
    screenX: clamp(50 + 44 * Math.sin(hourAngleDeg * RAD), 3, 97),
    screenY: clamp(50 - 0.47 * elevationDeg, 4, 92),
    accuracy,
  }
}
