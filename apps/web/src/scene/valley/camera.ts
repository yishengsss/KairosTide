import * as THREE from 'three'

export function frameValley(camera: THREE.PerspectiveCamera, width: number, height: number): void {
  const aspect = Math.max(0.1, width / Math.max(1, height))
  camera.fov = 28
  camera.aspect = aspect
  // Portrait retreats in the same scene, preserving the right summit and valley.
  const retreat = Math.max(0, 1.2 / aspect - 1) * 110
  camera.position.set(retreat > 0 ? 12 : 0, 5, 60 + retreat)
  camera.lookAt(retreat > 0 ? 12 : 0, 1 - retreat * .025, -65)
  camera.updateProjectionMatrix()
  camera.updateMatrixWorld()
}

export function createCamera(width: number, height: number): THREE.PerspectiveCamera {
  const camera = new THREE.PerspectiveCamera(28, 1, .1, 1100)
  frameValley(camera, width, height)
  return camera
}
