import { chromium } from 'playwright'
import assert from 'node:assert/strict'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'
import { mkdir, writeFile } from 'node:fs/promises'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1100, height: 680 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.addInitScript(() => {
  window.events = []
  window.fixture = { curves: [{ name: 'Fixture response', color: '#2f6fb0', points: [[20, 0], [1000, 4], [20000, -2]] }],
    filters: [{ id: 1, frequency: 1000, gain: 2, q: 0.7, kind: 'PEAK', enabled: true }],
    raw: [], nodeBase: [], rawBase: [], addBase: [], label: 'Synthetic interaction fixture', low: -24, high: 24,
    legend: [{ key: 'original', label: 'Fixture response', color: '#2f6fb0', checked: true, group: 'acoustic' },
      { key: 'target', label: 'Target', color: '#f2c14e', dashed: true, checked: false, group: 'acoustic' }],
    theme: { mode: 'light', tokens: { bg: '#f6f8fb', accent: '#2563d4' } } }
  window.qt = { webChannelTransport: {} }
  window.QWebChannel = class {
    constructor(transport, callback) {
      let receive
      callback({ objects: { bridge: {
        publish: { connect: fn => { receive = fn } },
        ready: () => receive(JSON.stringify(window.fixture)),
        submit: text => {
          const event = JSON.parse(text)
          window.events.push(event)
          if (event.op === 'begin') window.gestureRange = window.fixture.correctionRange && { ...window.fixture.correctionRange }
          if (event.op === 'range') window.fixture.correctionRange = event.range
          if (event.op === 'cancel') window.fixture.correctionRange = window.gestureRange
          if (event.op === 'filter') window.fixture.filters[event.index] = event.filter
          if (event.op === 'add') window.fixture.filters.push({ id: 2, frequency: event.frequency, gain: event.gain, q: 0.7, kind: 'PEAK', enabled: true })
          if (event.op === 'delete') window.fixture.filters.splice(event.index, 1)
          if (event.op === 'view') window.fixture.legend.find(item => item.key === event.key).checked = event.value
          if (event.op !== 'begin') receive(JSON.stringify(window.fixture))
        }
      } } })
    }
  }
})
try {
  await page.goto(pathToFileURL(path.join(root, 'src/heytap_eq/web/index.html')).href)
  await page.waitForFunction(() => window.studioInspect?.().svgPaths > 0)
  const plot = page.locator('.plot')
  const box = await plot.boundingBox()
  await page.mouse.move(box.x + box.width * 0.65, box.y + box.height * 0.6)
  await page.mouse.wheel(0, -100)
  await page.waitForTimeout(100)
  const zoomed = await page.evaluate(() => window.studioInspect().view)
  assert.ok(zoomed.minFreq > 20 && zoomed.maxFreq < 20000)
  await page.mouse.dblclick(box.x + box.width * 0.6, box.y + box.height * 0.5)
  await page.waitForFunction(() => window.fixture.filters.length === 2)
  assert.ok((await page.evaluate(() => window.events.at(-1).frequency)) > zoomed.minFreq)
  assert.deepEqual(await page.evaluate(() => window.studioInspect().view), zoomed)

  const node = page.locator('[data-filter="0"] circle')
  const point = await node.boundingBox()
  await page.mouse.move(point.x + point.width / 2, point.y + point.height / 2)
  await page.mouse.down()
  await page.mouse.move(point.x + 60, point.y - 25, { steps: 5 })
  await page.mouse.up()
  await page.waitForTimeout(150)
  const drag = await page.evaluate(() => window.events.filter(e => e.op === 'filter'))
  assert.ok(drag.some(e => e.phase === 'change'))
  assert.equal(drag.filter(e => e.phase === 'end').length, 1)
  assert.ok(drag.at(-1).filter.frequency > 1000)
  assert.ok(drag.at(-1).filter.gain > 2)
  const moved = await node.boundingBox()
  await page.mouse.move(moved.x + moved.width / 2, moved.y + moved.height / 2)
  await page.mouse.wheel(0, 100)
  await page.waitForTimeout(100)
  assert.ok((await page.evaluate(() => window.fixture.filters[0].q)) > 0.7)
  assert.deepEqual(await page.evaluate(() => window.studioInspect().view), zoomed)
  await page.evaluate(() => {
    window.fixture.filters[0].q = 24
    window.studioUpdate(window.fixture)
  })
  await page.waitForTimeout(50)
  await page.mouse.wheel(0, 100)
  await page.waitForFunction(() => window.fixture.filters[0].q > 24)
  await node.click({ button: 'right' })
  await page.getByLabel('增益 dB', { exact: true }).fill('0')
  await page.getByLabel('增益 dB', { exact: true }).press('Enter')
  await page.waitForFunction(() => window.fixture.filters[0].gain === 0)
  await page.getByRole('button', { name: '删除', exact: true }).click()
  await page.waitForFunction(() => window.fixture.filters.length === 1)
  // Schema 2: legend chips toggle curves through Python, theme tokens restyle the page.
  assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()), '#2563d4')
  assert.equal(await page.evaluate(() => window.studioInspect().theme), 'light')
  // High contrast: the page is told so, draws curves 1.5x thicker and thickens control edges.
  const strokeWidth = () => page.evaluate(() => {
    const curve = [...document.querySelectorAll('.plot svg path')].find(p => getComputedStyle(p).stroke === 'rgb(47, 111, 176)')
    return curve ? parseFloat(getComputedStyle(curve).strokeWidth) : null
  })
  const standardWidth = await strokeWidth()
  assert.ok(standardWidth > 0)
  const setContrast = (contrast, lineScale) => page.evaluate(([contrast, lineScale]) => {
    window.fixture.theme = { ...window.fixture.theme, contrast, lineScale }
    window.studioUpdate(JSON.stringify(window.fixture))  // a fresh payload, as the bridge sends
  }, [contrast, lineScale])
  await setContrast('high', 1.5)
  await page.waitForFunction(() => window.studioInspect().contrast === 'high')
  assert.equal(await strokeWidth(), standardWidth * 1.5)
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('header button')).borderTopWidth), '2px')
  await setContrast('standard', 1)
  await page.waitForFunction(() => window.studioInspect().contrast === 'standard')
  assert.equal(await strokeWidth(), standardWidth)
  await page.locator('.chip[data-key="target"]').click()
  assert.deepEqual(await page.evaluate(() => window.events.at(-1)), { op: 'view', key: 'target', value: true })
  assert.equal(await page.locator('.chip[data-key="target"]').getAttribute('aria-pressed'), 'true')
  await page.getByRole('button', { name: '适配', exact: true }).click()
  const fitted = await page.evaluate(() => window.studioInspect().view)
  assert.ok(fitted.maxGain - fitted.minGain < 48 && fitted.minGain <= -2 && fitted.maxGain >= 4)
  await page.locator('[data-filter="0"] circle').click({ button: 'right' })
  await page.keyboard.press('Delete')
  await page.waitForFunction(() => window.fixture.filters.length === 0)
  // Axis hit areas are continuous; both dB axes use the same view and cursor anchor.
  await page.evaluate(() => { window.fixture.splOffset = 80; window.studioUpdate(window.fixture) })
  await page.getByRole('button', { name: '复位', exact: true }).click()
  const fullView = await page.evaluate(() => window.studioInspect().view)
  const axisX = await page.locator('.axis-x').boundingBox()
  await page.mouse.move(axisX.x + axisX.width * .6, axisX.y + axisX.height / 2)
  await page.mouse.wheel(0, -100)
  await page.waitForTimeout(100)
  const xView = await page.evaluate(() => window.studioInspect().view)
  assert.ok(xView.minFreq > fullView.minFreq && xView.maxFreq < fullView.maxFreq)
  assert.equal(xView.minGain, fullView.minGain)
  const axisLeft = await page.locator('.axis-left').boundingBox()
  await page.mouse.move(axisLeft.x + axisLeft.width / 2, axisLeft.y + axisLeft.height * .4)
  await page.mouse.wheel(0, -100)
  await page.waitForTimeout(100)
  const leftView = await page.evaluate(() => window.studioInspect().view)
  assert.equal(leftView.minFreq, xView.minFreq)
  assert.ok(leftView.maxGain - leftView.minGain < xView.maxGain - xView.minGain)
  const axisRight = await page.locator('.axis-right').boundingBox()
  await page.mouse.move(axisRight.x + axisRight.width / 2, axisRight.y + axisRight.height * .7)
  await page.mouse.wheel(0, -100)
  await page.waitForTimeout(100)
  const rightView = await page.evaluate(() => window.studioInspect().view)
  assert.equal(rightView.minFreq, leftView.minFreq)
  assert.ok(rightView.maxGain - rightView.minGain < leftView.maxGain - leftView.minGain)

  await page.getByRole('button', { name: '复位', exact: true }).click()
  await page.evaluate(() => {
    window.fixture.correctionRange = { enabled: true, low_hz: 200, high_hz: 10000, low_octaves: .5, high_octaves: 1.5 }
    window.fixture.rangeWeights = [[20, 0], [140, 0], [200, .5], [300, 1], [5000, 1], [10000, .5], [17000, 0], [20000, 0]]
    window.studioUpdate(window.fixture)
  })
  const boundary = page.locator('button[data-boundary="low"]')
  await boundary.waitFor()
  const rangeBefore = await page.evaluate(() => window.studioInspect().view)
  const boundaryBox = await boundary.boundingBox()
  const rangeEventsBefore = await page.evaluate(() => window.events.filter(e => e.op === 'range').length)
  await page.mouse.move(boundaryBox.x + boundaryBox.width / 2, boundaryBox.y + boundaryBox.height / 2)
  await page.mouse.down()
  await page.mouse.move(boundaryBox.x + 80, boundaryBox.y + boundaryBox.height / 2, { steps: 6 })
  await page.mouse.up()
  await page.waitForTimeout(100)
  const rangeEvents = await page.evaluate(n => window.events.filter(e => e.op === 'range').slice(n), rangeEventsBefore)
  assert.ok(rangeEvents.some(e => e.phase === 'change'))
  assert.equal(rangeEvents.filter(e => e.phase === 'end').length, 1)
  assert.ok(rangeEvents.at(-1).range.low_hz > 200)
  assert.equal(rangeEvents.at(-1).range.high_octaves, 1.5)
  assert.deepEqual(await page.evaluate(() => window.studioInspect().view), rangeBefore)
  const committedLow = rangeEvents.at(-1).range.low_hz
  await boundary.press('ArrowRight')
  await page.waitForFunction(low => window.fixture.correctionRange.low_hz > low, committedLow)
  await boundary.dblclick()
  assert.equal(await page.evaluate(() => window.fixture.filters.length), 0)
  // Thin-line hit target also drags; an overlapping PEQ node remains ahead of the line.
  const line = page.locator('g.range-hit[data-boundary="low"] rect')
  const lineBox = await line.boundingBox()
  await page.mouse.move(lineBox.x + lineBox.width / 2, lineBox.y + lineBox.height * .2)
  await page.mouse.down()
  await page.mouse.move(lineBox.x + 40, lineBox.y + lineBox.height * .2, { steps: 4 })
  await page.mouse.up()
  await page.waitForTimeout(100)
  assert.ok((await page.evaluate(() => window.fixture.correctionRange.low_hz)) > committedLow)
  await page.evaluate(() => {
    window.fixture.correctionRange.low_hz = 1000
    window.fixture.filters = [{ id: 3, frequency: 1000, gain: 12, q: .7, kind: 'PEAK', enabled: true }]
    window.studioUpdate(window.fixture)
  })
  const overlappingNode = page.locator('[data-filter="0"] circle')
  const overlapBox = await overlappingNode.boundingBox()
  await page.mouse.move(overlapBox.x + overlapBox.width / 2, overlapBox.y + overlapBox.height / 2)
  await page.mouse.wheel(0, 100)
  await page.waitForFunction(() => window.fixture.filters[0].q > .7)
  assert.deepEqual(await page.evaluate(() => window.studioInspect().view), rangeBefore)
  await page.evaluate(() => { window.fixture.correctionRange.enabled = false; window.studioUpdate(window.fixture) })
  await page.waitForFunction(() => window.studioInspect().boundaries === 0)
  await page.evaluate(() => { window.fixture.correctionRange.enabled = true; window.studioUpdate(window.fixture) })
  await page.waitForFunction(() => window.studioInspect().boundaries === 2)
  await page.getByRole('button', { name: '复位', exact: true }).click()
  assert.equal((await page.evaluate(() => window.fixture.correctionRange.low_hz)), 1000)
  await page.setViewportSize({ width: 640, height: 460 })
  await page.waitForTimeout(100)
  assert.equal(await page.locator('button[data-boundary]').count(), 2)
  await page.setViewportSize({ width: 1100, height: 680 })
  await page.evaluate(() => { window.fixture.filters = []; window.fixture.correctionRange.enabled = false })
  await page.evaluate(() => {
    window.fixture.curves = []
    window.fixture.actions = [{ label: '导入测量', command: 'import_measurements' }]
    window.studioUpdate(window.fixture)
  })
  await page.getByRole('button', { name: '导入测量' }).click()
  assert.deepEqual(await page.evaluate(() => window.events.at(-1)), { op: 'command', name: 'import_measurements' })
  assert.deepEqual(errors, [])
  await mkdir(path.join(root, 'reports'), { recursive: true })
  await page.screenshot({ path: path.join(root, 'reports/dsssp-editor.png') })
  await writeFile(path.join(root, 'reports/frontend-interactions.json'), JSON.stringify({ status: 'passed', checks: ['log resampling', 'cursor zoom', 'double click add', 'live drag', 'wheel Q', 'zoom retained', 'zero gain edit', 'delete', 'theme tokens', 'high contrast', 'legend toggle', 'auto-fit', 'delete key', 'axis x zoom', 'both axis y zoom', 'boundary drag and keyboard', 'one gesture end', 'line-node priority', 'range visibility and reset', 'narrow window', 'empty-state command'], errors }, null, 2))
} finally {
  await browser.close()
}
