import test from 'node:test'
import assert from 'node:assert/strict'
import { TimePeekController } from '../../src/platform/timePeek.ts'

class FakeTimers {
  now = 0
  nextId = 1
  tasks = new Map()
  setTimeout(callback, delay) {
    const id = this.nextId++
    this.tasks.set(id, { at: this.now + delay, callback })
    return id
  }
  clearTimeout(id) { this.tasks.delete(id) }
  advance(ms) {
    const end = this.now + ms
    while (true) {
      const next = [...this.tasks.entries()].sort((a, b) => a[1].at - b[1].at)[0]
      if (!next || next[1].at > end) break
      this.now = next[1].at
      this.tasks.delete(next[0])
      next[1].callback()
    }
    this.now = end
  }
}

function harness() {
  const timers = new FakeTimers()
  let current = new Date(2026, 8, 26, 14, 7)
  const states = []
  const peek = new TimePeekController({ now: () => current }, state => states.push(state), timers)
  return { peek, timers, states, setCurrent: date => { current = date } }
}

test('blank-surface long press reveals real local time, refreshes it, then fades away', () => {
  const { peek, timers, states, setCurrent } = harness()
  peek.pointerDown(1, 150, 260)
  timers.advance(599)
  assert.equal(states.length, 0)
  timers.advance(1)
  assert.deepEqual(states.at(-1), { visible: true, time: '14:07', x: 150, y: 260 })

  setCurrent(new Date(2026, 8, 26, 14, 8))
  timers.advance(1000)
  assert.deepEqual(states.at(-1), { visible: true, time: '14:08', x: 150, y: 260 })
  timers.advance(2000)
  assert.deepEqual(states.at(-1), { visible: false, time: '14:08', x: 150, y: 260 })
  peek.dispose()
})

test('moving more than ten pixels before the hold threshold cancels the peek', () => {
  const { peek, timers, states } = harness()
  peek.pointerDown(1, 50, 60)
  peek.pointerMove(1, 61, 60)
  timers.advance(1000)
  assert.equal(states.length, 0)
  peek.dispose()
})

test('interactive controls, early release, and a second pointer never reveal time', () => {
  const { peek, timers, states } = harness()
  peek.pointerDown(1, 10, 10, false)
  timers.advance(700)
  peek.pointerDown(2, 10, 10)
  peek.pointerDown(3, 10, 10)
  peek.pointerUp(2)
  timers.advance(700)
  assert.equal(states.length, 0)
  peek.pointerDown(4, 10, 10)
  timers.advance(300)
  peek.pointerUp(4)
  timers.advance(700)
  assert.equal(states.length, 0)
  peek.dispose()
})

test('a repeated long press refreshes the time and restarts the visible duration', () => {
  const { peek, timers, states, setCurrent } = harness()
  peek.pointerDown(1, 0, 0)
  timers.advance(600)
  setCurrent(new Date(2026, 8, 26, 14, 9))
  peek.pointerUp(1)
  peek.pointerDown(2, 0, 0)
  timers.advance(600)
  assert.deepEqual(states.at(-1), { visible: true, time: '14:09', x: 0, y: 0 })
  timers.advance(2400)
  assert.equal(states.at(-1).visible, true)
  timers.advance(600)
  assert.equal(states.at(-1).visible, false)
  peek.dispose()
})
