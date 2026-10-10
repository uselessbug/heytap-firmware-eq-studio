import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { FrequencyResponseGraph, FrequencyResponseCurve, FilterPoint } from 'dsssp'
import { clamp, frequencyAt, gainAt, xAt, yAt, interpolate, resample, zoom, pan, frequencyTicks } from './math.mjs'
import './editor.css'

const defaultView = { minFreq: 20, maxFreq: 20000, minGain: -24, maxGain: 24 }
const kinds = ['PEAK', 'LS', 'HS', 'LP', 'HP', 'NOTCH', 'BAND_PASS', 'ALL_PASS']
const noGain = new Set(['LP', 'HP', 'NOTCH', 'BAND_PASS', 'ALL_PASS'])
const formatHz = f => f >= 1000 ? `${Number((f / 1000).toFixed(2))}k` : `${Math.round(f)}`
let bridge
const send = event => bridge?.submit(JSON.stringify(event))

function Inspector({ filter, index, close }) {
  const [draft, setDraft] = useState(filter)
  useEffect(() => setDraft(filter), [filter])
  const update = (key, value) => {
    const next = { ...draft, [key]: value }
    setDraft(next)
    send({ op: 'filter', phase: 'end', index, filter: next })
  }
  return <section className="inspector" aria-label="PEQ 参数">
    <header><strong>PEQ {filter.id}</strong><button onClick={close}>关闭</button></header>
    <label>类型<select value={draft.kind} onChange={e => update('kind', e.target.value)}>{kinds.map(k => <option key={k}>{k}</option>)}</select></label>
    {[['frequency', '频率 Hz', 20, 20000, 1], ['gain', '增益 dB', -60, 60, 0.1], ['q', 'Q', 0.01, 100, 0.1]].map(([key, title, min, max, step]) =>
      <label key={key}>{title}<input aria-label={title} type="number" min={min} max={max} step={step} value={draft[key]}
        onChange={e => setDraft({ ...draft, [key]: e.target.value })}
        onBlur={() => update(key, clamp(Number.isFinite(Number(draft[key])) ? Number(draft[key]) : min, min, max))}
        onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} /></label>)}
    <footer><label><input type="checkbox" checked={draft.enabled} onChange={e => update('enabled', e.target.checked)} />启用</label>
      <button className="danger" onClick={() => { send({ op: 'delete', index }); close() }}>删除</button></footer>
  </section>
}

function Editor() {
  const [data, setData] = useState({ curves: [], filters: [], raw: [], label: '修正 EQ', empty: '双击图形添加 PEQ，或导入 EQ／频响。' })
  const [view, setView] = useState(defaultView)
  const [size, setSize] = useState({ width: 800, height: 360 })
  const [selected, setSelected] = useState(null)
  const [pointer, setPointer] = useState(null)
  const plotRef = useRef(null)
  const panRef = useRef(null)
  const activeRef = useRef(false)
  const latest = useRef({ data, view, size })
  latest.current = { data, view, size, selected }

  useEffect(() => {
    window.studioEdit = send
    window.studioUpdate = value => {
      const payload = typeof value === 'string' ? JSON.parse(value) : value
      setData(payload)
      if (payload.reset) setView({ ...defaultView, minGain: payload.low, maxGain: payload.high })
    }
    window.studioInspect = () => ({ ready: true, curves: latest.current.data.curves.length,
      filters: latest.current.data.filters.length, view: latest.current.view,
      svgPaths: document.querySelectorAll('.plot svg path').length,
      width: latest.current.size.width, height: latest.current.size.height, selected: latest.current.selected })
    if (window.qt && window.QWebChannel) {
      new window.QWebChannel(window.qt.webChannelTransport, channel => {
        bridge = channel.objects.bridge
        bridge.publish.connect(window.studioUpdate)
        bridge.ready()
      })
    }
    const resize = new ResizeObserver(entries => {
      const r = entries[0].contentRect
      setSize({ width: Math.max(10, r.width), height: Math.max(10, r.height) })
    })
    resize.observe(plotRef.current)
    return () => resize.disconnect()
  }, [])

  useEffect(() => {
    const el = plotRef.current
    const wheel = e => {
      e.preventDefault()
      const node = e.target.closest('[data-node]')
      if (node) {
        if (node.dataset.filter !== undefined) {
          const index = Number(node.dataset.filter)
          const f = latest.current.data.filters[index]
          if (f) send({ op: 'filter', phase: 'end', index,
            filter: { ...f, q: Number(clamp(f.q + (e.deltaY > 0 ? 0.1 : -0.1), 0.01, 100).toFixed(2)) } })
        }
        return
      }
      const rect = el.getBoundingClientRect()
      const x = clamp((e.clientX - rect.left) / rect.width, 0, 1)
      const y = clamp((e.clientY - rect.top) / rect.height, 0, 1)
      setView(v => zoom(v, Math.exp(clamp(e.deltaY, -100, 100) * 0.0025), x, y, e.shiftKey))
    }
    el.addEventListener('wheel', wheel, { passive: false })
    return () => el.removeEventListener('wheel', wheel)
  }, [])

  const coords = e => {
    const r = plotRef.current.getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }
  const changeFilter = (f, index, event) => {
    const frequency = clamp(event.freq, 20, 20000)
    const base = interpolate(data.nodeBase, frequency)
    send({ op: 'filter', phase: event.ended ? 'end' : 'change', index,
      filter: { ...f, frequency, gain: noGain.has(f.kind) ? f.gain : clamp(event.gain - base, -60, 60), q: event.q } })
  }
  const addPoint = e => {
    if (e.target.closest('[data-node]')) return
    const p = coords(e), frequency = frequencyAt(p.x, size.width, view)
    const gain = gainAt(p.y, size.height, view) - interpolate(data.addBase, frequency)
    send({ op: 'add', frequency, gain: clamp(gain, -60, 60) })
  }
  const ticks = useMemo(() => frequencyTicks(view, size.width), [view, size.width])
  const step = (view.maxGain - view.minGain) <= 12 ? 2 : (view.maxGain - view.minGain) <= 60 ? 5 : 10
  const yTicks = []
  for (let v = Math.ceil(view.minGain / step) * step; v <= view.maxGain; v += step) yTicks.push(v)
  const scale = useMemo(() => ({ ...view, dbSteps: step, dbLabels: false, majorTicks: ticks, octaveTicks: 0, octaveLabels: [] }), [view, step, ticks])
  const curves = useMemo(() => data.curves.map(c => ({ ...c,
    magnitudes: resample(c.points, view, Math.min(4000, Math.max(800, Math.ceil(size.width * 2)))),
    left: clamp(xAt(c.points[0][0], size.width, view), 0, size.width),
    right: clamp(xAt(c.points.at(-1)[0], size.width, view), 0, size.width)
  })), [data.curves, view, size.width])
  const selectedFilter = selected === null ? null : data.filters[selected]

  return <main className="editor">
    <div className="top"><span className="title">{data.label}</span><span className="hint">{data.axisLabel || "dB"}</span>
      <button onClick={() => send({ op: 'add', frequency: Math.sqrt(view.minFreq * view.maxFreq), gain: 0 })}>＋ PEQ</button>
      <button onClick={() => setView({ ...defaultView, minGain: data.low ?? -24, maxGain: data.high ?? 24 })}>复位视图</button>
    </div>
    <div className="legend">{data.curves.map(c => <span key={c.name}><i className="swatch" style={{ background: c.color }} />{c.name}</span>)}</div>
    <div className="graph-shell">
      {ticks.map(f => <span className="x-tick" key={f} style={{ left: 54 + xAt(f, size.width, view) }}>{formatHz(f)}</span>)}
      {yTicks.map(v => <span className="y-tick" key={v} style={{ top: 6 + yAt(v, size.height, view) }}>{v}</span>)}
      {data.splOffset !== null && data.splOffset !== undefined && yTicks.map(v => <span className="spl-tick" key={v}
        style={{ top: 6 + yAt(v, size.height, view) }}>{(v + data.splOffset).toFixed(0)}</span>)}
      {data.splOffset !== null && data.splOffset !== undefined && <span className="spl-label">SPL dB</span>}
      <div className="plot" ref={plotRef} style={{ right: data.splOffset !== null && data.splOffset !== undefined ? 54 : 12 }} onDoubleClick={addPoint}
        onContextMenu={e => {
          e.preventDefault()
          const node = e.target.closest('[data-filter]')
          if (node) setSelected(Number(node.dataset.filter))
        }}
        onPointerDown={e => {
          if (e.button !== 0 || e.target.closest('[data-node]')) return
          panRef.current = { ...coords(e), view }
          e.currentTarget.setPointerCapture(e.pointerId)
        }}
        onPointerMove={e => {
          const p = coords(e)
          setPointer({ frequency: frequencyAt(p.x, size.width, view), gain: gainAt(p.y, size.height, view) })
          const start = panRef.current
          if (start) setView(pan(start.view, (p.x - start.x) / size.width, (p.y - start.y) / size.height))
        }}
        onPointerUp={() => { panRef.current = null }}
        onPointerCancel={() => { panRef.current = null }}
        onPointerLeave={() => setPointer(null)}>
        <FrequencyResponseGraph width={size.width} height={size.height} scale={scale} ariaLabel="交互式频响与 PEQ 编辑器"
          theme={{ background: { grid: { lineColor: '#2b3a50' }, label: { color: 'transparent' },
            gradient: { start: '#131e2d', stop: '#0c131d' } }, filters: { point: { radius: 9, label: { fontSize: 11 } } } }}>
          <defs><clipPath id="plot-clip"><rect width={size.width} height={size.height} /></clipPath>
            {curves.map((c, i) => <clipPath id={`curve-clip-${i}`} key={c.name}><rect x={c.left} width={Math.max(0, c.right - c.left)} height={size.height} /></clipPath>)}
          </defs>
          <g clipPath="url(#plot-clip)">
            {(data.bands || []).map((band, i) => {
              const left = clamp(xAt(band.low, size.width, view), 0, size.width)
              const right = clamp(xAt(band.high, size.width, view), 0, size.width)
              return <g key={`band-${i}`} pointerEvents="none"><rect x={left} width={Math.max(0, right-left)} height={size.height} fill="#b29ad4" opacity="0.09" />
                <text x={left+5} y={16} fill="#c0a9df" fontSize={11}>{band.label}</text></g>
            })}
            {curves.map((c, i) => <g key={c.name} clipPath={`url(#curve-clip-${i})`}><FrequencyResponseCurve color={c.color} lineWidth={2} dotted={c.dashed}
              magnitudes={c.magnitudes} /></g>)}
            {data.raw.map((point, index) => <g key={`raw-${index}`} data-node="raw">
              <FilterPoint filter={{ type: 'PEAK', freq: point[0], gain: point[1] + interpolate(data.rawBase, point[0]), q: 1 }}
                index={index} dragX={false} wheelQ={false} radius={4} color="#efb55a" label=""
                onDrag={active => { activeRef.current = active; if (active) send({ op: 'begin' }) }}
                onChange={e => send({ op: 'raw', phase: e.ended ? 'end' : 'change', index,
                  gain: clamp(e.gain - interpolate(data.rawBase, point[0]), -60, 60) })} />
            </g>)}
            {data.filters.map((f, index) => f.enabled && <g key={`peq-${f.id}`} data-node="peq" data-filter={index}
              onClick={() => setSelected(index)}>
              <FilterPoint filter={{ type: 'PEAK', freq: f.frequency,
                gain: (noGain.has(f.kind) ? 0 : f.gain) + interpolate(data.nodeBase, f.frequency), q: f.q }}
                index={index} color="#59debc" label={String(f.id)} active={selected === index} dragY={!noGain.has(f.kind)} wheelQ={false}
                onDrag={active => { activeRef.current = active; if (active) send({ op: 'begin' }) }}
                onChange={e => changeFilter(f, index, e)} />
            </g>)}
            {pointer && <g pointerEvents="none" opacity="0.5"><line x1={xAt(pointer.frequency, size.width, view)} x2={xAt(pointer.frequency, size.width, view)}
              y1={0} y2={size.height} stroke="#a8b9cf" strokeDasharray="3 4" />
              <line x1={0} x2={size.width} y1={yAt(pointer.gain, size.height, view)} y2={yAt(pointer.gain, size.height, view)} stroke="#a8b9cf" strokeDasharray="3 4" /></g>}
          </g>
        </FrequencyResponseGraph>
        {!data.curves.length && <div className="empty">{data.empty}</div>}
      </div>
      {selectedFilter && <Inspector filter={selectedFilter} index={selected} close={() => setSelected(null)} />}
    </div>
    <div className="footer"><span>双击添加 · 拖点调频率／增益 · 点上滚轮调 Q · 右键参数</span>
      <span>空白处滚轮缩放 · Shift＋滚轮纵向缩放 · 拖空白处平移</span>
      <span className="readout">{pointer ? `${formatHz(pointer.frequency)} Hz · ${pointer.gain.toFixed(2)} dB` : '20 Hz—20 kHz'}</span></div>
  </main>
}

createRoot(document.getElementById('root')).render(<Editor />)
