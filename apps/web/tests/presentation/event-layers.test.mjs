import test from 'node:test'
import assert from 'node:assert/strict'
import { parse, compileScript } from '@vue/compiler-sfc'
import { transformSync } from 'esbuild'
import { createRenderer, createSSRApp, ssrContextKey } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createRequire } from 'node:module'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

const appRoot = fileURLToPath(new URL('../../', import.meta.url))
const require = createRequire(new URL('../../package.json', import.meta.url))
async function loadComponent(name) {
  const filename = resolve(appRoot, `src/presentation/${name}.vue`)
  const source = await readFile(filename, 'utf8')
  const { descriptor } = parse(source, { filename })
  const compiled = compileScript(descriptor, { id: name, inlineTemplate: true }).content
  const javascript = transformSync(compiled, { loader: 'ts', format: 'cjs' }).code
  const module = { exports: {} }
  new Function('require', 'module', 'exports', javascript)(require, module, module.exports)
  return module.exports.default
}

const occurrence = (id, title, location = null) => ({
  occurrence_id: id, event_id: `event-${id}`, version: 1,
  title, location, start_at: '2026-09-26T14:00:00+08:00', end_at: '2026-09-26T15:00:00+08:00',
  temporal_phase: 'active', disposition: 'scheduled',
})

function makeHost() {
  const nodes = []
  const renderer = createRenderer({
    createElement: type => ({ type, props: {}, children: [], parent: null }),
    createText: text => ({ type: '#text', text, parent: null }),
    createComment: text => ({ type: '#comment', text, parent: null }),
    setText(node, text) { node.text = text },
    setElementText(node, text) { node.text = text },
    patchProp(node, key, _old, value) { node.props[key] = value },
    insert(node, parent, anchor = null) {
      node.parent = parent
      const index = anchor ? parent.children.indexOf(anchor) : -1
      if (index < 0) parent.children.push(node)
      else parent.children.splice(index, 0, node)
    },
    remove(node) { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1) },
  })
  const root = { type: 'root', children: [], props: {} }
  return { renderer, root, nodes }
}
function walk(node, predicate, out = []) {
  if (predicate(node)) out.push(node)
  for (const child of node.children ?? []) walk(child, predicate, out)
  return out
}
function textContent(node) { return `${node.text ?? ''}${(node.children ?? []).map(textContent).join('')}` }

test('scene signals render positioned selectable rings without task prompt copy', async () => {
  const SceneEventSignals = await loadComponent('SceneEventSignals')
  const { renderer, root } = makeHost()
  const selected = []
  const signals = [
    { id: 'rigid-1', kind: 'rigid', accessibleName: '查看课程', x: 120, y: 230, diameter: 64 },
    { id: 'flex-1', kind: 'flexible', accessibleName: '查看任务', x: 260, y: 245, diameter: 56 },
  ]
  const app = renderer.createApp(SceneEventSignals, { signals, onSelect: id => selected.push(id) })
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(root)
  const buttons = walk(root, node => node.type === 'button')
  assert.equal(buttons.length, 2)
  assert.deepEqual(buttons.map(button => button.props['aria-label']), ['查看课程', '查看任务'])
  assert.deepEqual(buttons.map(button => button.props.style), [
    { left: '120px', top: '230px', width: '64px', height: '64px' },
    { left: '260px', top: '245px', width: '56px', height: '56px' },
  ])
  assert.doesNotMatch(textContent(root), /如果愿意|从这里开始/)
  buttons[1].props.onClick()
  buttons[0].props.onClick()
  assert.deepEqual(selected, ['flex-1', 'rigid-1'])
  app.unmount()
})

test('active event surfaces title and place without clock values or a timer', async () => {
  const ActiveEventLayer = await loadComponent('ActiveEventLayer')
  const html = await renderToString(createSSRApp(ActiveEventLayer, {
    occurrence: occurrence('o-1', '软件工程课', '教学楼A'),
  }))
  assert.match(html, /软件工程课/)
  assert.match(html, /教学楼A/)
  assert.match(html, /知道了/)
  assert.match(html, /例外/)
  assert.doesNotMatch(html, /14:00|15:00|倒计时|剩余/)
})

test('active event layer renders no empty schedule surface', async () => {
  const ActiveEventLayer = await loadComponent('ActiveEventLayer')
  const html = await renderToString(createSSRApp(ActiveEventLayer, { occurrence: null }))
  assert.equal(html, '<!--v-if-->')
})

test('conflicts show all members without an implicit winner', async () => {
  const ConflictChoice = await loadComponent('ConflictChoice')
  const html = await renderToString(createSSRApp(ConflictChoice, {
    conflict: { conflict_id: 'c-1', member_ids: ['o-a', 'o-b'], selected_id: null, snapshot_revision: 12 },
    occurrences: [occurrence('o-a', '软件工程课', '教学楼A'), occurrence('o-b', '项目讨论', '线上')],
  }))
  assert.match(html, /软件工程课/)
  assert.match(html, /项目讨论/)
  assert.match(html, /教学楼A/)
  assert.match(html, /线上/)
  assert.match(html, /请决定当前主要显示哪一项/)
  assert.doesNotMatch(html, /14:00|15:00|倒计时|剩余/)
  assert.equal((html.match(/type="radio"[^>]*checked/g) ?? []).length, 0)
})

test('an invalid selected id is treated as stale and cannot look like a completed choice', async () => {
  const ConflictChoice = await loadComponent('ConflictChoice')
  const html = await renderToString(createSSRApp(ConflictChoice, {
    conflict: { conflict_id: 'c-1', member_ids: ['o-a', 'o-b'], selected_id: 'o-missing', snapshot_revision: 12 },
    occurrences: [occurrence('o-a', '软件工程课'), occurrence('o-b', '项目讨论')],
  }))
  assert.match(html, /冲突选择与当前事件不匹配，请刷新后重新查看。/)
  assert.doesNotMatch(html, /已选择当前主要事件/)
  assert.match(html, /fieldset disabled/)
})

test('conflict selection emits only the user-selected occurrence with current decision context', async () => {
  const ConflictChoice = await loadComponent('ConflictChoice')
  const { renderer, root } = makeHost()
  const selected = []
  const app = renderer.createApp(ConflictChoice, {
    conflict: { conflict_id: 'c-1', member_ids: ['o-a', 'o-b'], selected_id: null, snapshot_revision: 12 },
    occurrences: [occurrence('o-a', '软件工程课'), occurrence('o-b', '项目讨论')],
    'onChoose': choice => selected.push(choice),
  })
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(root)
  const radios = walk(root, node => node.type === 'input' && node.props.type === 'radio')
  assert.equal(radios.length, 2)
  radios[1].props.onChange({ target: { checked: true } })
  assert.deepEqual(selected, [{ selectedId: 'o-b', memberIds: ['o-a', 'o-b'], snapshotRevision: 12 }])
  app.unmount()
})

test('active event actions carry their occurrence id', async () => {
  const ActiveEventLayer = await loadComponent('ActiveEventLayer')
  const { renderer, root } = makeHost()
  const actions = []
  const app = renderer.createApp(ActiveEventLayer, {
    occurrence: occurrence('o-7', '高数课'),
    onAcknowledge: id => actions.push(['acknowledge', id]),
    onException: id => actions.push(['exception', id]),
  })
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(root)
  const buttons = walk(root, node => node.type === 'button')
  buttons.find(node => textContent(node).includes('知道了')).props.onClick()
  buttons.find(node => textContent(node).includes('例外')).props.onClick()
  assert.deepEqual(actions, [['acknowledge', 'o-7'], ['exception', 'o-7']])
  app.unmount()
})
