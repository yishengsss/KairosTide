/** Palette adapted from the user-selected Continuous Flow HTML; no demo clock. */
const SEASONS = [
  { name: '春', sunrise: 6.0, sunset: 18.5, sky1: [80, 110, 140], sky2: [180, 200, 210], sky3: [240, 220, 220], sunColor: [255, 240, 200], sunGlow: [255, 220, 180], water: [80, 130, 120], ground: [83, 128, 73], foliage: [145, 198, 112], foliageCoverage: 0.82, shoreCoverage: 0.7 },
  { name: '夏', sunrise: 5.0, sunset: 20.0, sky1: [30, 100, 180], sky2: [100, 180, 230], sky3: [255, 240, 200], sunColor: [255, 250, 220], sunGlow: [255, 230, 150], water: [40, 100, 160], ground: [50, 100, 60], foliage: [60, 140, 70], foliageCoverage: 1, shoreCoverage: 0.95 },
  { name: '秋', sunrise: 6.5, sunset: 17.5, sky1: [120, 80, 60], sky2: [220, 160, 100], sky3: [255, 200, 130], sunColor: [255, 220, 160], sunGlow: [255, 180, 100], water: [140, 110, 80], ground: [110, 80, 50], foliage: [220, 140, 60], foliageCoverage: 0.6, shoreCoverage: 0.62 },
  { name: '冬', sunrise: 7.5, sunset: 16.5, sky1: [60, 70, 100], sky2: [140, 150, 170], sky3: [220, 225, 235], sunColor: [240, 240, 255], sunGlow: [200, 210, 240], water: [100, 110, 130], ground: [90, 95, 105], foliage: [120, 120, 110], foliageCoverage: 0.12, shoreCoverage: 0.32 },
];

function smoothstep(t: number) { return t * t * (3 - 2 * t); }
function lerpArr(a: number[], b: number[], t: number) { return a.map((v, i) => v + (b[i] - v) * t); }

export function getSeason(month: number) {
  // March is the spring stop; wrap December/January continuously.
  const idx = (((month - 3) % 12 + 12) % 12) / 3;
  const i1 = Math.floor(idx) % 4;
  const i2 = (i1 + 1) % 4;
  const t = smoothstep(idx - Math.floor(idx));
  const a = SEASONS[i1], b = SEASONS[i2];
  return {
    name: t < 0.5 ? a.name : b.name,
    month,
    sunrise: a.sunrise + (b.sunrise - a.sunrise) * t,
    sunset: a.sunset + (b.sunset - a.sunset) * t,
    sky1: lerpArr(a.sky1, b.sky1, t),
    sky2: lerpArr(a.sky2, b.sky2, t),
    sky3: lerpArr(a.sky3, b.sky3, t),
    sunColor: lerpArr(a.sunColor, b.sunColor, t),
    sunGlow: lerpArr(a.sunGlow, b.sunGlow, t),
    water: lerpArr(a.water, b.water, t),
    ground: lerpArr(a.ground, b.ground, t),
    foliage: lerpArr(a.foliage, b.foliage, t),
    foliageCoverage: a.foliageCoverage + (b.foliageCoverage - a.foliageCoverage) * t,
    shoreCoverage: a.shoreCoverage + (b.shoreCoverage - a.shoreCoverage) * t,
  };
}


export type FlowSeason = ReturnType<typeof getSeason>
