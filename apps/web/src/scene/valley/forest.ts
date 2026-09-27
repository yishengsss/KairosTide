import * as THREE from 'three'

/** S1 / K01 / K02: static, seeded woodland in the shared y-up lake coordinates. */
type Shore = {
  name: string
  edge: Array<[number, number]>
  depth: number
  count: number
  landRise: number
}
type Tree = { x: number; y: number; z: number; height: number; width: number; yaw: number; tone: number; variant: number }

const SHORES: Shore[] = [
  { name: 'far-left', edge: [[-87, -55], [-71, -56], [-56, -61], [-43, -68], [-29, -76], [-16, -84]], depth: 15, count: 600, landRise: 0.13 },
  { name: 'far-right', edge: [[14, -85], [27, -80], [42, -73], [59, -65], [74, -59], [87, -57]], depth: 14, count: 530, landRise: 0.13 },
  { name: 'distant-lake-mouth', edge: [[-16, -88], [-8, -88.7], [1, -89], [8, -88.3], [14, -88]], depth: 3, count: 74, landRise: 0.13 },
  { name: 'near-left', edge: [[-66, 6], [-53, 3], [-43, -6], [-34, -18], [-25.8, -30]], depth: 10, count: 92, landRise: 0.25 },
  { name: 'near-right', edge: [[36.8, -39], [45, -30], [56, -17], [69, -8]], depth: 9, count: 60, landRise: 0.25 },
]

function random(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    return state / 4294967296
  }
}

function edgeAt(shore: Shore, x: number): number {
  for (let i = 1; i < shore.edge.length; i++) {
    const a = shore.edge[i - 1]!
    const b = shore.edge[i]!
    if (x <= b[0]) {
      const t = (x - a[0]) / (b[0] - a[0])
      return THREE.MathUtils.lerp(a[1], b[1], t) + Math.sin(x * 0.73) * 0.24 + Math.sin(x * 1.87) * 0.11
    }
  }
  return shore.edge[shore.edge.length - 1]![1]
}

/** The same function places the bank vertices and roots; no unsupported water trees. */
function groundAt(x: number, depth: number, shore: Shore): number {
  const rise = Math.min(1, depth / 2)
  return 0.12 + rise * (0.27 + 0.09 * Math.sin(x * 0.47) + 0.05 * Math.sin(depth * 1.1 + x))
    + Math.min(depth / shore.depth, 1) * shore.landRise
}

function shoreDepths(shore: Shore): number[] {
  return [...new Set([-0.28, 0, 0.45, 1.1, 2.5, shore.depth * 0.55, shore.depth])].sort((a, b) => a - b)
}

/** Interpolate on the same diagonal split used by createShore's indexed triangles. */
function sampleBank(shore: Shore, x: number, depth: number, steps: number, depths: number[]): { y: number; z: number } {
  const minX = shore.edge[0]![0]
  const maxX = shore.edge[shore.edge.length - 1]![0]
  const gx = THREE.MathUtils.clamp((x - minX) / (maxX - minX) * steps, 0, steps - 1e-8)
  const column = Math.floor(gx)
  const u = gx - column
  let row = 0
  while (row < depths.length - 2 && depth > depths[row + 1]!) row++
  const d0 = depths[row]!
  const d1 = depths[row + 1]!
  const v = THREE.MathUtils.clamp((depth - d0) / (d1 - d0), 0, 1)
  const x0 = THREE.MathUtils.lerp(minX, maxX, column / steps)
  const x1 = THREE.MathUtils.lerp(minX, maxX, (column + 1) / steps)
  const values = (px: number, d: number) => ({
    y: d === -0.28 ? -0.24 : groundAt(px, d, shore),
    z: edgeAt(shore, px) - d,
  })
  const a = values(x0, d0)
  const b = values(x1, d0)
  const c = values(x0, d1)
  const d = values(x1, d1)
  if (u + v <= 1) {
    return { y: a.y * (1 - u - v) + b.y * u + c.y * v, z: a.z * (1 - u - v) + b.z * u + c.z * v }
  }
  return { y: b.y * (1 - v) + d.y * (u + v - 1) + c.y * (1 - u), z: b.z * (1 - v) + d.z * (u + v - 1) + c.z * (1 - u) }
}

function createShore(shore: Shore): THREE.Mesh {
  const positions: number[] = []
  const colors: number[] = []
  const indices: number[] = []
  const minX = shore.edge[0]![0]
  const maxX = shore.edge[shore.edge.length - 1]![0]
  const steps = Math.ceil((maxX - minX) / 0.75)
  // A dark, submerged lip continues into the moss-covered bank, never a floating sheet.
  const depths = shoreDepths(shore)
  for (let i = 0; i <= steps; i++) {
    const x = THREE.MathUtils.lerp(minX, maxX, i / steps)
    for (let j = 0; j < depths.length; j++) {
      const d = depths[j]!
      const y = j === 0 ? -0.24 : groundAt(x, d, shore)
      positions.push(x, y, edgeAt(shore, x) - d)
      const color = new THREE.Color(j < 3 ? '#5a6050' : '#384b2e')
      color.multiplyScalar(0.89 + 0.10 * Math.sin(x * 2.8 + j * 1.6))
      colors.push(color.r, color.g, color.b)
      if (i < steps && j < depths.length - 1) {
        const a = i * depths.length + j
        const b = a + depths.length
        indices.push(a, b, a + 1, b, b + 1, a + 1)
      }
    }
  }
  // Close both ends below water so the peninsula silhouette stays solid from side angles.
  for (const i of [0, steps]) {
    const first = i * depths.length
    const bottom = positions.length / 3
    positions.push(positions[first * 3]!, -0.3, positions[first * 3 + 2]!)
    colors.push(0.10, 0.12, 0.08)
    for (let j = 0; j < depths.length - 1; j++) {
      if (i === 0) indices.push(first + j, first + j + 1, bottom)
      else indices.push(first + j + 1, first + j, bottom)
    }
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.98, metalness: 0 }))
  mesh.name = `woodland-bank-${shore.name}`
  mesh.userData.depthRows = depths
  mesh.receiveShadow = true
  return mesh
}

/** Layered branch whorls: serrated skirts, asymmetrical tips and a narrow growing leader. */
function crownGeometry(variant: number): THREE.BufferGeometry {
  const rng = random(483 + variant * 172)
  const vertices: number[] = []
  const colors: number[] = []
  const indices: number[] = []
  const radial = 12
  const layers = 7
  for (let tier = 0; tier < layers; tier++) {
    const base = vertices.length / 3
    const t = tier / (layers - 1)
    const level = 0.17 + t * 0.67
    const spread = (0.235 * Math.pow(1 - t * 0.86, 0.78)) * (1 + (rng() - 0.5) * 0.16)
    const turn = tier * 1.27 + variant * 0.38
    const peak = Math.min(1, level + 0.25 - t * 0.09)
    // Three corrugated rings per whorl break up the outline without alpha-card sorting.
    for (let ring = 0; ring < 3; ring++) {
      for (let k = 0; k < radial; k++) {
        const angle = k / radial * Math.PI * 2 + turn
        const tooth = k % 2 === 0 ? 1 : 0.59
        const radius = spread * [0.24, 1, 0.12][ring]! * (0.84 + rng() * 0.25) * (ring === 1 ? tooth : 1)
        const y = ring === 0 ? level + 0.075 : ring === 1 ? level - rng() * 0.034 : peak
        vertices.push(Math.cos(angle) * radius + Math.sin(tier * 1.3) * 0.012, y, Math.sin(angle) * radius)
        const shade = ring === 0 ? 0.63 : ring === 1 ? 0.85 + rng() * 0.13 : 1.02
        colors.push(shade, shade, shade)
      }
    }
    for (let ring = 0; ring < 2; ring++) {
      for (let k = 0; k < radial; k++) {
        const a = base + ring * radial + k
        const b = base + ring * radial + (k + 1) % radial
        const c = a + radial
        const d = b + radial
        indices.push(a, c, b, b, c, d)
      }
    }
    // Cap the growing tip, avoiding a pinhole when seen from slightly above.
    const tip = vertices.length / 3
    vertices.push(Math.sin(tier * 1.3) * 0.012, peak + 0.025, 0)
    colors.push(1.05, 1.05, 1.05)
    for (let k = 0; k < radial; k++) indices.push(base + 2 * radial + k, tip, base + 2 * radial + (k + 1) % radial)
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3))
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  return geometry
}

export function createForest(): THREE.Group {
  const forest = new THREE.Group()
  forest.name = 'valley-woodland'
  const rng = random(260926)
  const trees: Tree[] = []
  for (const shore of SHORES) {
    forest.add(createShore(shore))
    const left = shore.edge[0]![0]
    const right = shore.edge[shore.edge.length - 1]![0]
    for (let i = 0; i < shore.count; i++) {
      const x = THREE.MathUtils.lerp(left + 0.4, right - 0.4, rng())
      const depth = 0.85 + rng() * (shore.depth - 1.3)
      // Perspective depth controls scale across all banks; growth remains shorter by the water.
      const cameraDepth = THREE.MathUtils.smoothstep(edgeAt(shore, x) - depth, -90, -25)
      const perspectiveScale = THREE.MathUtils.lerp(0.58, 1.12, cameraDepth)
      const edgeScale = THREE.MathUtils.lerp(0.78, 1, Math.min(depth / shore.depth, 1))
      const height = 2.7 * perspectiveScale * edgeScale * THREE.MathUtils.lerp(0.78, 1.12, rng())
      const surface = sampleBank(shore, x, depth, Math.ceil((right - left) / 0.75), shoreDepths(shore))
      trees.push({ x, z: surface.z, y: surface.y, height,
        width: 0.8 + rng() * 0.5, yaw: rng() * Math.PI * 2, tone: rng(), variant: Math.floor(rng() * 3) })
    }
  }
  const matrix = new THREE.Object3D()
  const leafMaterial = new THREE.MeshStandardMaterial({ color: '#ffffff', vertexColors: true, roughness: 0.94, metalness: 0 })
  const darkGreen = new THREE.Color('#25472f')
  const lightGreen = new THREE.Color('#557044')
  for (let variant = 0; variant < 3; variant++) {
    const family = trees.filter(tree => tree.variant === variant)
    const crowns = new THREE.InstancedMesh(crownGeometry(variant), leafMaterial, family.length)
    crowns.name = `needle-whorls-${variant}`
    family.forEach((tree, index) => {
      matrix.position.set(tree.x, tree.y, tree.z)
      matrix.rotation.set(0, tree.yaw, 0)
      matrix.scale.set(tree.height * tree.width, tree.height, tree.height * tree.width)
      matrix.updateMatrix()
      crowns.setMatrixAt(index, matrix.matrix)
      crowns.setColorAt(index, darkGreen.clone().lerp(lightGreen, tree.tone * 0.84))
    })
    crowns.instanceMatrix.needsUpdate = true
    if (crowns.instanceColor) crowns.instanceColor.needsUpdate = true
    crowns.computeBoundingSphere()
    crowns.castShadow = true
    crowns.receiveShadow = true
    forest.add(crowns)
  }
  const trunks = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.009, 0.019, 0.78, 5), new THREE.MeshStandardMaterial({ color: '#574b37', roughness: 1 }), trees.length)
  trunks.name = 'woodland-trunks'
  trees.forEach((tree, index) => {
    matrix.position.set(tree.x, tree.y + tree.height * 0.39, tree.z)
    matrix.rotation.set(0, tree.yaw, 0)
    matrix.scale.setScalar(tree.height)
    matrix.updateMatrix()
    trunks.setMatrixAt(index, matrix.matrix)
  })
  trunks.instanceMatrix.needsUpdate = true
  trunks.computeBoundingSphere()
  forest.add(trunks)
  forest.userData.treeCount = trees.length
  forest.userData.drawCalls = SHORES.length + 4
  forest.userData.seed = 260926
  return forest
}
