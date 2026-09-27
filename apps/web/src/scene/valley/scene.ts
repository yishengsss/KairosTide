import * as THREE from 'three'
import { createTerrain } from './terrain.ts'
import { createForest } from './forest.ts'
import { createForeground } from './foreground.ts'
import { createSky } from './sky.ts'
import { createLake } from './lake.ts'
import { createCamera, frameValley } from './camera.ts'

export type SceneQuality = 'high' | 'medium' | 'low'
const QUALITY = {
  high: { pixelRatio: 2, reflection: 1536 },
  medium: { pixelRatio: 1.5, reflection: 1024 },
  low: { pixelRatio: 1, reflection: 512 },
} as const

/** S1 deliberately renders on demand. Time, weather and seasonal evolution are later stages. */
export function mountValley(container: HTMLElement, quality: SceneQuality = 'medium') {
  const settings = QUALITY[quality]
  const scene = new THREE.Scene()
  scene.name = 'Kairos — same-place alpine valley'
  scene.fog = new THREE.FogExp2('#b9c6c4', .0026)
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, settings.pixelRatio))
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.08
  renderer.domElement.setAttribute('role', 'img')
  renderer.domElement.setAttribute('aria-label', '静谧的山谷湖泊，层叠远山、两岸森林、近岸岩石和伸入天空的树枝。')
  container.append(renderer.domElement)
  const camera = createCamera(container.clientWidth, container.clientHeight)
  const sky = createSky()
  const terrain = createTerrain()
  const forest = createForest()
  const foreground = createForeground()
  const lake = createLake(settings.reflection)
  scene.add(sky, terrain, forest, foreground, lake)
  const sunlight = new THREE.DirectionalLight('#ffe5b5', 2.4)
  sunlight.position.set(-60, 40, -45)
  sunlight.target.position.set(0, 0, -60)
  const skylight = new THREE.HemisphereLight('#b7d1ea', '#393c27', 1.9)
  scene.add(sunlight, sunlight.target, skylight)

  let disposed = false, lost = false, renderRequest = 0
  function render() {
    renderRequest = 0
    if (disposed || lost || document.hidden) return
    renderer.render(scene, camera)
    container.dataset.ready = 'true'
  }
  function resize() {
    if (disposed) return
    const width = container.clientWidth, height = container.clientHeight
    if (!width || !height) return
    frameValley(camera, width, height)
    renderer.setSize(width, height)
    if (!renderRequest) renderRequest = requestAnimationFrame(render)
  }
  function contextLost(event: Event) {
    event.preventDefault()
    lost = true
    container.dataset.ready = 'false'
    container.dispatchEvent(new CustomEvent('valley-error', { detail: '画面连接暂时中断，正在等待图形设备恢复。' }))
  }
  function contextRestored() {
    lost = false
    container.dispatchEvent(new CustomEvent('valley-restored'))
    resize()
  }
  function visibility() { if (!document.hidden) resize() }
  const observer = new ResizeObserver(resize)
  observer.observe(container)
  renderer.domElement.addEventListener('webglcontextlost', contextLost)
  renderer.domElement.addEventListener('webglcontextrestored', contextRestored)
  document.addEventListener('visibilitychange', visibility)
  resize()

  return {
    scene, camera, renderer,
    dispose() {
      if (disposed) return
      disposed = true
      cancelAnimationFrame(renderRequest)
      observer.disconnect()
      document.removeEventListener('visibilitychange', visibility)
      renderer.domElement.removeEventListener('webglcontextlost', contextLost)
      renderer.domElement.removeEventListener('webglcontextrestored', contextRestored)
      // Sets account for shared instancing geometry and materials.
      const geometries = new Set<THREE.BufferGeometry>()
      const materials = new Set<THREE.Material>()
      scene.traverse(object => {
        if (object instanceof THREE.Mesh) {
          geometries.add(object.geometry)
          for (const material of Array.isArray(object.material) ? object.material : [object.material]) materials.add(material)
          if (object instanceof THREE.InstancedMesh) object.dispose()
        }
      })
      lake.dispose()
      for (const material of Array.isArray(lake.material) ? lake.material : [lake.material]) materials.delete(material)
      geometries.forEach(geometry => geometry.dispose())
      materials.forEach(material => material.dispose())
      renderer.dispose()
      renderer.domElement.remove()
      scene.clear()
    },
  }
}
