import test from 'node:test'
import assert from 'node:assert/strict'

import { SceneEnvironmentSession } from '../../src/scene/session.ts'
import { SceneWeatherController } from '../../src/scene/weatherController.ts'

const instant = new Date('2026-09-26T07:00:00.000Z')
const choice = { name: 'Xi An', admin1: 'Shaanxi', country: 'China', latitude: 34.3416, longitude: 108.9398, timezone: 'Asia/Shanghai' }

function response(condition = 'rain') {
  return {
    availability: 'available', location_id: 'Xi An', location_label: 'Xi An, Shaanxi, China',
    latitude: choice.latitude, longitude: choice.longitude, timezone: choice.timezone,
    source: 'Open-Meteo', attribution: 'Weather data by Open-Meteo (CC BY 4.0)',
    fetched_at: instant.toISOString(), detail: null, location_choices: [],
    observations: [{ kind: 'current', condition, cloud_cover: 80, precipitation: 1,
      visibility: 10000, observed_at: instant.toISOString(), valid_until: '2026-09-26T08:00:00.000Z' }],
  }
}

test('scene weather stays neutral until the user explicitly sets a city', async () => {
  let calls = 0
  const session = new SceneEnvironmentSession({ now: () => instant })
  const controller = new SceneWeatherController(session, { query: async () => { calls++; return response() } })
  await controller.maybeRefresh(instant.getTime())
  assert.equal(calls, 0)
  assert.equal(controller.state.status, 'idle')
  assert.equal(session.frame.atmosphere.condition, null)
  await controller.setCity('Xi An')
  assert.equal(session.frame.atmosphere.condition, 'rain')
  assert.equal(session.frame.sun.accuracy, 'location_based_approximation')
  assert.equal(controller.state.attribution, 'Weather data by Open-Meteo (CC BY 4.0)')
})

test('an unavailable response clears old weather but keeps the selected place solar path', async () => {
  let available = true
  const session = new SceneEnvironmentSession({ now: () => instant })
  const controller = new SceneWeatherController(session, { query: async () => available ? response() : {
    ...response(), availability: 'unavailable', observations: [], detail: 'Weather service is temporarily unavailable.',
  } })
  await controller.setCity('Xi An')
  assert.equal(session.frame.atmosphere.condition, 'rain')
  const sunBefore = session.frame.sun
  available = false
  await controller.maybeRefresh(instant.getTime() + 16 * 60_000)
  assert.equal(controller.state.status, 'unavailable')
  assert.equal(session.frame.atmosphere.condition, null)
  assert.deepEqual(session.frame.sun, sunBefore)
})

test('ambiguous city waits for the user to select a returned place', async () => {
  const requests = []
  const session = new SceneEnvironmentSession({ now: () => instant })
  const controller = new SceneWeatherController(session, { query: async (query) => {
    requests.push(query)
    return query.choice ? response('clear') : {
      availability: 'unavailable', location_id: 'Xi An', location_label: null,
      latitude: null, longitude: null, timezone: null, source: 'Open-Meteo',
      attribution: 'Weather data by Open-Meteo (CC BY 4.0)', fetched_at: instant.toISOString(),
      detail: 'Choose a place', observations: [], location_choices: [choice],
    }
  } })
  await controller.setCity('Xi An')
  assert.equal(controller.state.status, 'ambiguous')
  assert.equal(session.frame.atmosphere.condition, null)
  await controller.selectChoice(choice)
  assert.equal(requests.length, 2)
  assert.deepEqual(requests[1], { city: 'Xi An', choice })
  assert.equal(controller.state.status, 'available')
  assert.equal(session.frame.atmosphere.condition, 'clear')
})

test('late response for a previous city cannot replace a newer selected city', async () => {
  let finishFirst
  const session = new SceneEnvironmentSession({ now: () => instant })
  const controller = new SceneWeatherController(session, { query: ({ city }) => city === 'Old City'
    ? new Promise(resolve => { finishFirst = resolve })
    : Promise.resolve({ ...response('snow'), location_id: city, location_label: city }),
  })
  const first = controller.setCity('Old City')
  await controller.setCity('New City')
  finishFirst(response('rain'))
  await first
  assert.equal(controller.state.city, 'New City')
  assert.equal(session.frame.atmosphere.condition, 'snow')
})
