import * as THREE from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'

function random(seed: number) {
  let state = seed
  return () => ((state = (Math.imul(state, 1664525) + 1013904223) >>> 0) / 4294967296)
}

function stoneGeometry(): THREE.BufferGeometry {
  const geometry = new THREE.IcosahedronGeometry(1, 3)
  const positions = geometry.getAttribute('position')
  const colors: number[] = []
  const dark = new THREE.Color('#4b5149')
  const light = new THREE.Color('#9c9c87')
  const moss = new THREE.Color('#626e39')
  for (let i = 0; i < positions.count; i++) {
    const x = positions.getX(i), y = positions.getY(i), z = positions.getZ(i)
    const n = Math.sin(x * 9.1 + z * 4.2) * Math.sin(z * 7.7 - y * 6.4)
    const broad = .9 + .12 * Math.sin(x * 3.7 + y * 1.1 + z * 2.3)
    positions.setXYZ(i, x * broad + n * .025, y * broad + n * .02, z * broad + n * .03)
    const c = dark.clone().lerp(light, .35 + n * .13)
    if (y > .35 && Math.sin(x * 8 + z * 3) > .1) c.lerp(moss, .55)
    colors.push(c.r, c.g, c.b)
  }
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
  geometry.computeVertexNormals()
  return geometry
}

function rockMaterial(): THREE.MeshStandardMaterial {
  const material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: .91 })
  material.onBeforeCompile = shader => {
    shader.vertexShader = shader.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vStone;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvStone=position;')
    shader.fragmentShader = shader.fragmentShader.replace('#include <common>', `#include <common>
      varying vec3 vStone;
      float grain(vec3 p){return fract(sin(dot(p,vec3(27.31,61.17,13.73)))*43758.53);}`)
      .replace('#include <color_fragment>', `#include <color_fragment>
        float fleck=grain(floor(vStone*210.0));
        float seam=sin(vStone.y*57.0+sin(vStone.x*9.0)*2.0+vStone.z*13.0);
        diffuseColor.rgb*=.83+fleck*.29;
        diffuseColor.rgb*=1.0-smoothstep(.95,1.0,seam)*.12;`)
  }
  return material
}

export function createForeground(): THREE.Group {
  const root = new THREE.Group()
  root.name = '08-foreground-stone-shore'
  const rng = random(86102)
  const transform = new THREE.Object3D()
  const stones = new THREE.InstancedMesh(stoneGeometry(), rockMaterial(), 160)
  stones.name = 'shore-rocks'
  for (let i = 0; i < stones.count; i++) {
    const t = rng()
    const z = 3 + t * 45
    const edgeX = -26 + t * 29
    const x = edgeX - rng() * (4 + t * 5)
    const size = i < 16 ? .8 + rng() * 1.3 : .15 + rng() * .68
    transform.position.set(x, -.25 + size * .24, z)
    transform.scale.set(size * (1.1 + rng() * .6), size * .65, size)
    transform.rotation.set(rng() * .5, rng() * 6, rng() * .35)
    transform.updateMatrix()
    stones.setMatrixAt(i, transform.matrix)
  }
  stones.castShadow = true
  stones.receiveShadow = true
  stones.computeBoundingSphere()
  root.add(stones)

  // A continuous asymmetric near bank keeps every grass tuft grounded.
  const positions: number[] = [], indices: number[] = []
  for (let i = 0; i <= 60; i++) {
    const t = i / 60, z = 2 + t * 49
    const edge = -26 + t * 30 + Math.sin(t * 19) * .35
    positions.push(edge, -.18, z, edge - 2, .15, z, edge - 15, .6, z)
    if (i < 60) {
      const a = i * 3
      indices.push(a, a + 3, a + 1, a + 1, a + 3, a + 4, a + 1, a + 4, a + 2, a + 2, a + 4, a + 5)
    }
  }
  const bankGeometry = new THREE.BufferGeometry()
  bankGeometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  bankGeometry.setIndex(indices)
  bankGeometry.computeVertexNormals()
  const bank = new THREE.Mesh(bankGeometry, new THREE.MeshStandardMaterial({ color: '#484c32', roughness: 1, side: THREE.DoubleSide }))
  bank.name = 'near-shore-ground'
  bank.receiveShadow = true
  root.add(bank)

  const blade = new THREE.BufferGeometry()
  blade.setAttribute('position', new THREE.Float32BufferAttribute([-.025,0,0,.025,0,0,-.019,.4,.025,.019,.4,.025,.08,.9,.06],3))
  blade.setIndex([0,1,2,1,3,2,2,3,4])
  blade.computeVertexNormals()
  const grasses = new THREE.InstancedMesh(blade, new THREE.MeshStandardMaterial({ color: '#718147', roughness: 1, side: THREE.DoubleSide }), 2600)
  grasses.name = 'grounded-grass'
  for (let i = 0; i < grasses.count; i++) {
    const t = rng(), z = 2 + t * 47
    const x = -26 + t * 30 - .8 - rng() * 5
    transform.position.set(x, .12, z)
    transform.rotation.set((rng() - .5) * .5, rng() * 6.28, (rng() - .5) * .4)
    transform.scale.setScalar(.18 + rng() * .58)
    transform.updateMatrix()
    grasses.setMatrixAt(i, transform.matrix)
  }
  grasses.computeBoundingSphere()
  root.add(grasses)
  root.add(createOverhangingBranch())
  return root
}

function createOverhangingBranch(): THREE.Group {
  const group = new THREE.Group()
  group.name = '09-overhanging-branch'
  const rng = random(7423), parts: THREE.BufferGeometry[] = []
  const twigs: Array<[THREE.Vector3, THREE.Vector3]> = []
  function branch(a: THREE.Vector3, b: THREE.Vector3, radius: number) {
    const direction = b.clone().sub(a)
    const geometry = new THREE.CylinderGeometry(radius * .36, radius, direction.length(), 7)
    geometry.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0), direction.clone().normalize()))
    geometry.translate(...a.clone().add(b).multiplyScalar(.5).toArray())
    parts.push(geometry)
  }
  const a = new THREE.Vector3(-17, 12.7, 29)
  const b = new THREE.Vector3(-6.1, 10.9, 28)
  branch(a, b, .19)
  branch(new THREE.Vector3(-16,10.5,31), new THREE.Vector3(-8.3,8.6,30), .1)
  for (let i = 0; i < 23; i++) {
    const t = i / 23
    const start = a.clone().lerp(b,t)
    const end = start.clone().add(new THREE.Vector3(.5 + rng() * 2, (i % 2 ? 1 : -1) * (.8 + rng() * 1.2), (rng() - .5) * 2.4))
    branch(start,end,.042 * (1 - t * .65))
    twigs.push([start,end])
  }
  const merged = mergeGeometries(parts)
  parts.forEach(g => g.dispose())
  const wood = new THREE.Mesh(merged, new THREE.MeshStandardMaterial({ color: '#443b29', roughness: 1 }))
  group.add(wood)
  // Curved, pointed individual leaves preserve an airy branch silhouette.
  const leaf = new THREE.BufferGeometry()
  leaf.setAttribute('position',new THREE.Float32BufferAttribute([0,0,0,-.13,.15,.018,.13,.15,.018,-.17,.3,.04,.17,.3,.04,-.1,.44,.035,.1,.44,.035,0,.58,0],3))
  leaf.setIndex([0,2,1,1,2,3,2,4,3,3,4,5,4,6,5,5,6,7])
  leaf.computeVertexNormals()
  const leaves = new THREE.InstancedMesh(leaf,new THREE.MeshStandardMaterial({color:'#ffffff',roughness:.9,side:THREE.DoubleSide}),640)
  leaves.name = 'individual-foreground-leaves'
  const dummy=new THREE.Object3D()
  for(let i=0;i<leaves.count;i++){
    const [start,end]=twigs[i%twigs.length]
    const p=start.clone().lerp(end,.15+rng()*.95)
    dummy.position.copy(p).add(new THREE.Vector3((rng()-.5)*.8,(rng()-.5)*.65,(rng()-.5)*.8))
    dummy.rotation.set((rng()-.5)*1.2,rng()*6.28,(rng()-.5)*5)
    dummy.scale.setScalar(.65+rng()*.7)
    dummy.updateMatrix(); leaves.setMatrixAt(i,dummy.matrix)
    leaves.setColorAt(i,new THREE.Color('#354b19').lerp(new THREE.Color('#809143'),rng()*.7))
  }
  leaves.computeBoundingSphere()
  group.add(leaves)
  return group
}
