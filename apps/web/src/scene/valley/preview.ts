import { mountValley } from './scene.ts'
import { bindTimePeek } from '../../platform/timePeek.ts'

const container = document.querySelector<HTMLElement>('#valley')!
const failure = document.querySelector<HTMLElement>('#failure')!
const message = document.querySelector<HTMLElement>('#failure-message')!
const timePeek = document.querySelector<HTMLElement>('#time-peek')!
const unbindTimePeek = bindTimePeek(container, timePeek)
function showFailure(text: string) { message.textContent = text; failure.hidden = false }
container.addEventListener('valley-error', event => showFailure((event as CustomEvent<string>).detail))
container.addEventListener('valley-restored', () => { failure.hidden = true })
document.querySelector('#retry')!.addEventListener('click', () => location.reload())
try {
  const scene = mountValley(container)
  window.addEventListener('pagehide', event => { if (!event.persisted) { scene.dispose(); unbindTimePeek() } }, { once: true })
  if (import.meta.hot) import.meta.hot.dispose(() => { scene.dispose(); unbindTimePeek() })
} catch (error) {
  console.error('Valley renderer failed to start', error)
  showFailure('暂时无法显示自然场景。请确认浏览器已启用图形加速，然后重新加载。')
}
