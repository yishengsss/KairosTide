export interface RGB { r: number; g: number; b: number }

export interface ScenePalette {
  skyZenith: RGB
  skyHorizon: RGB
  mountainFar: RGB
  mountainMid: RGB
  mountainNear: RGB
  mountainLight: RGB
  water: RGB
  shore: RGB
}

type BasePalette = Omit<ScenePalette, 'mountainMid' | 'mountainLight'>
type PaletteKey = keyof BasePalette
type Stop = { elevation: number; colors: BasePalette }

const c = (r: number, g: number, b: number): RGB => ({ r, g, b })
const stops: Stop[] = [
  { elevation: -18, colors: { skyZenith: c(8, 20, 41), skyHorizon: c(27, 45, 68), mountainFar: c(20, 39, 58), mountainNear: c(13, 31, 46), water: c(18, 44, 62), shore: c(19, 36, 40) } },
  { elevation: -7, colors: { skyZenith: c(33, 48, 82), skyHorizon: c(153, 84, 101), mountainFar: c(73, 72, 96), mountainNear: c(35, 55, 71), water: c(58, 75, 96), shore: c(45, 56, 56) } },
  { elevation: 0, colors: { skyZenith: c(79, 113, 153), skyHorizon: c(244, 169, 120), mountainFar: c(125, 126, 138), mountainNear: c(66, 91, 98), water: c(104, 126, 130), shore: c(69, 85, 67) } },
  { elevation: 12, colors: { skyZenith: c(91, 150, 199), skyHorizon: c(224, 207, 162), mountainFar: c(127, 160, 167), mountainNear: c(62, 111, 118), water: c(86, 143, 156), shore: c(66, 101, 75) } },
  { elevation: 45, colors: { skyZenith: c(63, 144, 209), skyHorizon: c(182, 216, 226), mountainFar: c(119, 171, 181), mountainNear: c(57, 113, 120), water: c(73, 147, 167), shore: c(55, 106, 80) } },
  { elevation: 90, colors: { skyZenith: c(53, 139, 207), skyHorizon: c(178, 218, 232), mountainFar: c(111, 170, 182), mountainNear: c(51, 112, 120), water: c(68, 146, 168), shore: c(51, 105, 78) } },
]

export function mixColor(a: RGB, b: RGB, amount: number): RGB {
  const t = Math.min(1, Math.max(0, amount))
  return c(
    Math.round(a.r + (b.r - a.r) * t),
    Math.round(a.g + (b.g - a.g) * t),
    Math.round(a.b + (b.b - a.b) * t),
  )
}

export function paletteFor(elevationDeg: number, transmission: number, seasonalWarmth: number, snow: number): ScenePalette {
  const upper = stops.findIndex((stop) => elevationDeg <= stop.elevation)
  const hi = upper < 0 ? stops.length - 1 : Math.max(1, upper)
  const lo = hi - 1
  const span = stops[hi].elevation - stops[lo].elevation
  const t = Math.min(1, Math.max(0, (elevationDeg - stops[lo].elevation) / span))
  const neutral = c(73, 96, 107)
  const result = {} as ScenePalette
  for (const key of Object.keys(stops[lo].colors) as PaletteKey[]) {
    const daylight = mixColor(stops[lo].colors[key], stops[hi].colors[key], t)
    const overcast = mixColor(daylight, neutral, (1 - transmission) * 0.72)
    let color = key === 'shore'
      ? mixColor(overcast, c(122, 111, 81), Math.max(0, seasonalWarmth) * 0.16)
      : overcast
    if (key === 'shore' || key === 'mountainFar') {
      color = mixColor(color, c(205, 211, 207), snow * (key === 'shore' ? 0.52 : 0.25))
    }
    result[key] = color
  }
  result.mountainMid = mixColor(result.mountainFar, result.mountainNear, 0.48)
  result.mountainLight = mixColor(result.skyHorizon, result.mountainFar, 0.38)
  return result
}
