export type SceneMarker = {
  id: string
  kind: 'rigid' | 'flexible'
  diameter: number
  x: number
  offsetBelowWaterline: number
}

export type SceneSignal = {
  id: string
  kind: SceneMarker['kind']
  accessibleName: string
  x: number
  y: number
  diameter: number
}

export type MarkerPlacementInput = {
  id: string
  kind: SceneMarker['kind']
  width: number
  height: number
  diameter: number
  minGap: number
  waterlineAt: (x: number) => number
  existing: SceneMarker[]
  random: () => number
  attempts?: number
}

const EDGE_GAP = 8
// Bounds from waterSurfaceYAt: 23px at 0.008 rad/px plus 9.2px at 0.02 rad/px.
const MAX_WAVE_AMPLITUDE = 23 + 23 * 0.4
const MAX_WAVE_SLOPE = 23 * 0.008 + 23 * 0.4 * 0.02

function horizontalWaveDifference(distance: number): number {
  return Math.min(2 * MAX_WAVE_AMPLITUDE, MAX_WAVE_SLOPE * distance)
}

function unitRandom(random: () => number): number {
  const value = random()
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0.5
}

export function screenYForMarker(marker: SceneMarker, waterlineAt: (x: number) => number): number {
  return waterlineAt(marker.x) + marker.offsetBelowWaterline
}

export function findMarkerPosition(input: MarkerPlacementInput): SceneMarker | null {
  const { width, height, diameter, minGap, waterlineAt, existing, random } = input
  if (!Number.isFinite(width) || !Number.isFinite(height) || !Number.isFinite(diameter)
    || width <= 0 || height <= 0 || diameter <= 0) return null
  const radius = diameter / 2
  const horizontalSpace = width - 2 * (radius + EDGE_GAP)
  if (horizontalSpace < 0) return null

  const requestedAttempts = input.attempts ?? 96
  const attempts = Number.isFinite(requestedAttempts)
    ? Math.min(256, Math.max(0, Math.floor(requestedAttempts)))
    : 96
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const x = radius + EDGE_GAP + unitRandom(random) * horizontalSpace
    const surface = waterlineAt(x)
    if (!Number.isFinite(surface)) continue

    // A circle must clear the whole moving edge under its footprint, not only its centre.
    let highestSurface = surface
    for (let sampleX = x - radius; sampleX <= x + radius; sampleX += 2) {
      const sampled = waterlineAt(sampleX)
      if (!Number.isFinite(sampled)) { highestSurface = Number.POSITIVE_INFINITY; break }
      highestSurface = Math.max(highestSurface, sampled)
    }
    const lastSample = waterlineAt(x + radius)
    if (!Number.isFinite(lastSample)) continue
    highestSurface = Math.max(highestSurface, lastSample)
    const minOffset = radius + EDGE_GAP + Math.max(
      highestSurface - surface, horizontalWaveDifference(radius),
    )
    // Across all supported tides, waterSurfaceYAt stays within this band.
    // A sampler outside it uses the full phase swing relative to its own line.
    const flowLowerBound = height * 0.78 - 25 - MAX_WAVE_AMPLITUDE
    const flowUpperBound = height * 0.78 + 11
    const futureSurface = surface >= flowLowerBound && surface <= flowUpperBound
      ? flowUpperBound
      : surface + 2 * MAX_WAVE_AMPLITUDE
    const maxOffset = height - radius - EDGE_GAP - futureSurface
    if (minOffset > maxOffset) continue
    const offset = minOffset + unitRandom(random) * (maxOffset - minOffset)
    const y = surface + offset
    const overlaps = existing.some(marker => {
      const dx = Math.abs(x - marker.x)
      const dy = Math.abs(y - screenYForMarker(marker, waterlineAt))
      // Two waterline samples can change their relative height by at most
      // twice the spatial wave difference over the same horizontal distance.
      const futureDy = Math.max(0, dy - 2 * horizontalWaveDifference(dx))
      return Math.hypot(dx, futureDy) < radius + marker.diameter / 2 + minGap
    })
    if (overlaps) continue
    return { id: input.id, kind: input.kind, diameter, x, offsetBelowWaterline: offset }
  }
  return null
}
