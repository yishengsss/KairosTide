import test from 'node:test'
import assert from 'node:assert/strict'

import { createSceneWeatherGateway } from '../../src/platform/weather.ts'

const choice = { name: 'Xi An', admin1: 'Shaanxi', country: 'China', latitude: 34.3416, longitude: 108.9398, timezone: 'Asia/Shanghai' }
const body = { availability: 'available', location_id: 'Xi An', latitude: choice.latitude, longitude: choice.longitude,
  location_label: 'Xi An, Shaanxi, China', timezone: choice.timezone, source: 'Open-Meteo', fetched_at: '2026-09-26T07:00:00Z',
  observations: [{ kind: 'current', condition: 'clear', cloud_cover: 0, precipitation: 0,
    visibility: 10000, observed_at: '2026-09-26T07:00:00Z', valid_until: '2026-09-26T08:00:00Z' }] }

test('scene weather gateway sends only the explicitly selected city and candidate fields', async () => {
  let requested
  const gateway = createSceneWeatherGateway(async (input, init) => {
    requested = { url: String(input), init }
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  const result = await gateway.query({ city: 'Xi An', choice })
  const url = new URL(requested.url, 'http://localhost')
  assert.equal(url.pathname, '/api/v1/weather')
  assert.equal(url.searchParams.get('location_id'), 'Xi An')
  assert.equal(url.searchParams.get('selected_latitude'), '34.3416')
  assert.equal(url.searchParams.get('selected_longitude'), '108.9398')
  assert.equal(url.searchParams.get('selected_timezone'), 'Asia/Shanghai')
  assert.equal(url.searchParams.get('selected_name'), 'Xi An')
  assert.equal(url.searchParams.get('selected_country'), 'China')
  assert.equal(url.searchParams.get('selected_admin1'), 'Shaanxi')
  assert.equal(requested.init.cache, 'no-store')
  assert.equal(result.observations[0].condition, 'clear')
})

test('scene weather gateway rejects malformed weather payloads before they reach the scene', async () => {
  const gateway = createSceneWeatherGateway(async () => new Response(JSON.stringify({ ...body, observations: 'rain' }), { status: 200 }))
  await assert.rejects(gateway.query({ city: 'Xi An' }), /Invalid weather response/)
})
