import * as THREE from 'three'

type RidgePoint = readonly [x: number, height: number]
type Layer = {
  name: string
  z: number
  depth: number
  seed: number
  points: readonly RidgePoint[]
  color: string
  haze: number
  detail: number
  segments: readonly [number, number]
  valley?: number
}

const clamp = THREE.MathUtils.clamp
const smooth = (a: number, b: number, value: number) => {
  const t = clamp((value - a) / (b - a), 0, 1)
  return t * t * (3 - 2 * t)
}

// Integer hashing and coherent noise keep the same landforms across reloads.
function hash(x: number, z: number, seed: number): number {
  let h = Math.imul(x, 374761393) ^ Math.imul(z, 668265263) ^ Math.imul(seed, 1442695041)
  h = Math.imul(h ^ (h >>> 13), 1274126177)
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295
}

function noise(x: number, z: number, seed: number): number {
  const ix = Math.floor(x)
  const iz = Math.floor(z)
  const tx = smooth(0, 1, x - ix)
  const tz = smooth(0, 1, z - iz)
  return THREE.MathUtils.lerp(
    THREE.MathUtils.lerp(hash(ix, iz, seed), hash(ix + 1, iz, seed), tx),
    THREE.MathUtils.lerp(hash(ix, iz + 1, seed), hash(ix + 1, iz + 1, seed), tx),
    tz,
  ) * 2 - 1
}

function fractal(x: number, z: number, seed: number): number {
  return noise(x, z, seed) * 0.58
    + noise(x * 2.07, z * 2.07, seed + 17) * 0.27
    + noise(x * 4.19, z * 4.19, seed + 41) * 0.11
    + noise(x * 8.37, z * 8.37, seed + 83) * 0.04
}

function ridgeHeight(x: number, points: readonly RidgePoint[]): number {
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]
    const b = points[i]
    if (x <= b[0]) {
      const t = clamp((x - a[0]) / (b[0] - a[0]), 0, 1)
      // Mostly linear shoulders retain geology; eased ends avoid needle summits.
      const blend = t * 0.74 + smooth(0, 1, t) * 0.26
      return THREE.MathUtils.lerp(a[1], b[1], blend)
    }
  }
  return points[points.length - 1][1]
}

function elevation(x: number, z: number, layer: Layer): number {
  const bend = noise(x * 0.035, 7, layer.seed) * layer.depth * 0.19
  const crestZ = layer.z + bend
  const dz = (z - crestZ) / layer.depth
  const crossSection = Math.exp(-Math.pow(Math.abs(dz) * 2.05, 1.65))
  const ridge = ridgeHeight(x, layer.points)
  const broad = fractal(x * 0.12, z * 0.09, layer.seed)
  const ribX = x + dz * 6.5 + noise(x * 0.055, z * 0.07, layer.seed + 2) * 3.2
  const gullies = Math.abs(fractal(ribX * 0.39, z * 0.105, layer.seed + 4))
  const texture = broad * layer.detail - gullies * layer.detail * 0.74
  const shoulder = crossSection * (ridge + texture)
  // A low, continuous valley connects the far slopes without walling off the lake.
  const valley = layer.valley ? smooth(layer.valley * 0.55, layer.valley, Math.abs(x)) : 1
  return shoulder * valley - 1.7
}

function rockMaterial(): THREE.MeshStandardMaterial {
  const material = new THREE.MeshStandardMaterial({
    vertexColors: true,
    roughness: 0.96,
    metalness: 0,
  })
  // Fine albedo detail stays subordinate to the genuine three-dimensional ridges.
  // All illumination still comes from the scene's shared sun and sky lights.
  material.onBeforeCompile = shader => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vTerrainPosition;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvTerrainPosition = position;')
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
        varying vec3 vTerrainPosition;
        float terrainHash(vec3 p) {
          p = fract(p * 0.1031);
          p += dot(p, p.yzx + 33.33);
          return fract((p.x + p.y) * p.z);
        }
        float terrainNoise(vec3 p) {
          vec3 i = floor(p), f = fract(p);
          f = f * f * (3.0 - 2.0 * f);
          return mix(mix(mix(terrainHash(i), terrainHash(i + vec3(1,0,0)), f.x),
            mix(terrainHash(i + vec3(0,1,0)), terrainHash(i + vec3(1,1,0)), f.x), f.y),
            mix(mix(terrainHash(i + vec3(0,0,1)), terrainHash(i + vec3(1,0,1)), f.x),
            mix(terrainHash(i + vec3(0,1,1)), terrainHash(i + vec3(1,1,1)), f.x), f.y), f.z);
        }`)
      .replace('#include <color_fragment>', `#include <color_fragment>
        float grain = terrainNoise(vTerrainPosition * vec3(3.0, 4.0, 3.0));
        float seams = terrainNoise(vTerrainPosition * vec3(1.3, 5.5, 1.3));
        diffuseColor.rgb *= 0.93 + grain * 0.11 + seams * 0.035;
      `)
  }
  material.customProgramCacheKey = () => 'kairos-valley-rock-v1'
  return material
}

function makeLayer(layer: Layer, material: THREE.Material): THREE.Group {
  const group = new THREE.Group()
  group.name = layer.name
  const [nx, nz] = layer.segments
  const positions = new Float32Array((nx + 1) * (nz + 1) * 3)
  const colors = new Float32Array(positions.length)
  const indices: number[] = []
  const rock = new THREE.Color(layer.color)
  const haze = new THREE.Color('#a9b8bd')
  const grass = new THREE.Color('#596b61')
  const snow = new THREE.Color('#d4d9d7')
  const tint = new THREE.Color()
  for (let zi = 0; zi <= nz; zi++) {
    for (let xi = 0; xi <= nx; xi++) {
      const index = zi * (nx + 1) + xi
      const x = -126 + (xi / nx) * 252
      const z = layer.z - layer.depth * 1.35 + (zi / nz) * layer.depth * 2.7
      const y = elevation(x, z, layer)
      positions.set([x, y, z], index * 3)
      const dx = (elevation(x + 0.4, z, layer) - elevation(x - 0.4, z, layer)) / 0.8
      const dz = (elevation(x, z + 0.4, layer) - elevation(x, z - 0.4, layer)) / 0.8
      const slope = Math.hypot(dx, dz)
      const variation = fractal(x * 0.31, z * 0.28, layer.seed + 137)
      tint.copy(rock)
      tint.lerp(grass, (1 - smooth(0.2, 0.9, slope)) * (1 - smooth(7, 16, y)) * 0.45)
      tint.multiplyScalar(0.97 + variation * 0.12)
      const snowHeight = 20.6 + noise(x * 0.48, z * 0.37, layer.seed + 218) * 1.9
      const snowCover = smooth(snowHeight, snowHeight + 1.4, y) * (1 - smooth(0.65, 1.8, slope))
      tint.lerp(snow, snowCover * 0.87)
      tint.lerp(haze, layer.haze)
      colors.set([tint.r, tint.g, tint.b], index * 3)
      if (xi < nx && zi < nz) {
        const a = index
        const b = index + 1
        const c = index + nx + 1
        const d = c + 1
        // Upward winding; alternate diagonals avoid a single visible grid direction.
        if ((xi + zi) % 2) indices.push(a, c, b, b, c, d)
        else indices.push(a, c, d, a, d, b)
      }
    }
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  geometry.computeBoundingBox()
  geometry.computeBoundingSphere()
  const mesh = new THREE.Mesh(geometry, material)
  mesh.name = `${layer.name}-landform`
  mesh.receiveShadow = true
  mesh.castShadow = false
  group.add(mesh)
  return group
}

/** Static, deterministic geometry. Water level is y=0; the camera looks down -Z. */
export function createTerrain(): THREE.Group {
  const terrain = new THREE.Group()
  terrain.name = 'valley-terrain'
  const material = rockMaterial()
  const layers: Layer[] = [
    {
      name: '01-distant-watershed', z: -143, depth: 20, seed: 207,
      color: '#7d8b90', haze: 0.4, detail: 1.15, segments: [252, 66],
      points: [[-126, 12], [-97, 17], [-76, 12], [-59, 20], [-39, 11], [-22, 9], [-6, 5], [9, 6], [27, 12], [43, 18], [64, 13], [84, 17], [103, 12], [126, 16]],
    },
    {
      name: '02-middle-watershed', z: -114, depth: 20, seed: 731,
      color: '#77878a', haze: 0.17, detail: 1.9, segments: [294, 76],
      points: [[-126, 19], [-103, 15], [-78, 22], [-61, 18], [-45, 13], [-26, 7], [-7, 3.8], [9, 4], [24, 9], [38, 16], [53, 20], [76, 16], [93, 22], [126, 18]],
    },
    {
      name: '03-main-mountain-ridge', z: -88, depth: 23, seed: 152,
      color: '#617575', haze: 0.025, detail: 2.0, segments: [420, 112],
      points: [[-126, 27], [-103, 23], [-84, 19], [-67, 22], [-55, 17], [-42, 12], [-29, 5], [-13, 2.4], [1, 2.1], [13, 2.8], [23, 9], [34, 20], [42, 27.5], [49, 25], [60, 16], [73, 19], [95, 22], [126, 25]],
    },
    {
      name: '04-near-valley-shoulders', z: -46, depth: 30, seed: 428,
      color: '#405d59', haze: 0, detail: 1.65, segments: [336, 104], valley: 37,
      points: [[-126, 32], [-104, 28], [-83, 25], [-65, 23], [-51, 17], [-41, 10], [-30, 4], [-15, 0], [15, 0], [30, 2], [43, 7], [58, 13], [77, 20], [101, 27], [126, 31]],
    },
  ]
  for (const layer of layers) terrain.add(makeLayer(layer, material))
  return terrain
}
