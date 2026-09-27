import test from 'node:test'
import assert from 'node:assert/strict'
import * as THREE from 'three'
import { createForest } from '../../src/scene/valley/forest.ts'

function instanceRoots(mesh, trunkHeight) {
  const matrix = new THREE.Matrix4()
  const position = new THREE.Vector3()
  const scale = new THREE.Vector3()
  const rotation = new THREE.Quaternion()
  const roots = []
  for (let i = 0; i < mesh.count; i++) {
    mesh.getMatrixAt(i, matrix)
    matrix.decompose(position, rotation, scale)
    roots.push({ x: position.x, y: position.y - trunkHeight * scale.y / 2, z: position.z, height: scale.y })
  }
  return roots
}

function triangleHeightAt(geometry, x, z) {
  const positions = geometry.attributes.position
  const indices = geometry.index.array
  for (let i = 0; i < indices.length; i += 3) {
    const ids = [indices[i], indices[i + 1], indices[i + 2]]
    const a = new THREE.Vector2(positions.getX(ids[0]), positions.getZ(ids[0]))
    const b = new THREE.Vector2(positions.getX(ids[1]), positions.getZ(ids[1]))
    const c = new THREE.Vector2(positions.getX(ids[2]), positions.getZ(ids[2]))
    const p = new THREE.Vector2(x, z)
    const denominator = (b.y - c.y) * (a.x - c.x) + (c.x - b.x) * (a.y - c.y)
    if (Math.abs(denominator) < 1e-9) continue
    const wa = ((b.y - c.y) * (p.x - c.x) + (c.x - b.x) * (p.y - c.y)) / denominator
    const wb = ((c.y - a.y) * (p.x - c.x) + (a.x - c.x) * (p.y - c.y)) / denominator
    const wc = 1 - wa - wb
    if (wa >= -1e-5 && wb >= -1e-5 && wc >= -1e-5) {
      return wa * positions.getY(ids[0]) + wb * positions.getY(ids[1]) + wc * positions.getY(ids[2])
    }
  }
  return null
}

test('each bank mesh advances monotonically from the water edge onto land', () => {
  const forest = createForest()
  const banks = forest.children.filter(child => child.name.startsWith('woodland-bank-'))
  assert.equal(banks.length, 5)
  for (const bank of banks) {
    const positions = bank.geometry.attributes.position
    const rows = bank.userData.depthRows?.length ?? 7
    for (let row = 1; row < rows; row++) {
      assert.ok(positions.getZ(row) < positions.getZ(row - 1), `${bank.name} folds between depth rows ${row - 1} and ${row}`)
    }
  }
})

test('sampled tree trunks sit on the rendered bank surface', () => {
  const forest = createForest()
  const banks = forest.children.filter(child => child.name.startsWith('woodland-bank-'))
  const trunks = forest.children.find(child => child.name === 'woodland-trunks')
  assert.ok(trunks)
  const roots = instanceRoots(trunks, 0.78)
  for (let i = 0; i < roots.length; i += 17) {
    const root = roots[i]
    const surfaces = banks.map(bank => triangleHeightAt(bank.geometry, root.x, root.z)).filter(Number.isFinite)
    assert.ok(surfaces.some(y => Math.abs(y - root.y) < 0.002), `tree ${i} root misses its visible bank by more than 0.002 units`)
  }
})

test('tree scale stays within a coherent landscape range', () => {
  const forest = createForest()
  const trunks = forest.children.find(child => child.name === 'woodland-trunks')
  const heights = instanceRoots(trunks, 0.78).map(root => root.height)
  assert.ok(Math.min(...heights) >= 0.45)
  assert.ok(Math.max(...heights) <= 3.6, `foreground tree scale is out of proportion: ${Math.max(...heights).toFixed(2)}`)
})
