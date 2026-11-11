import { memo, useEffect, useMemo, useRef } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, CustomChart, LineChart, ScatterChart } from 'echarts/charts'
import { AriaComponent, DataZoomComponent, GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { Icon } from '@/components/icons'
import { errorEndpoint, plotBounds, plotNumber } from '@/lib/numericPlot'
import { AnswerTable, BlockHeader, CiteButton, recordText } from './AnswerData'

echarts.use([BarChart, CustomChart, LineChart, ScatterChart, AriaComponent, DataZoomComponent, GridComponent, TooltipComponent, CanvasRenderer])

const themes = {
  light: { ink: '#283f34', line: '#cfdcd4', accent: '#287257', soft: '#dcece3', paper: '#fff' },
  dark: { ink: '#deeee4', line: '#3b5648', accent: '#8cd5ae', soft: '#385448', paper: '#18251e' },
}
const finite = value => plotNumber(typeof value === 'number' ? String(value) : value)
const axisNumber = value => Number(Number(value).toPrecision(7)).toString()

export const ChartCanvas = memo(function ChartCanvas({ options, onClick, chartRef, expanded = false, label, dark }) {
  const container = useRef(null)
  const chart = useRef(null)
  const click = useRef(onClick)
  click.current = onClick
  useEffect(() => {
    const instance = echarts.init(container.current, null, { renderer: 'canvas' })
    chart.current = instance
    if (chartRef) chartRef.current = instance
    instance.on('click', 'series', event => click.current?.(event))
    let frame = 0
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => { if (container.current?.clientWidth) instance.resize() })
    })
    observer.observe(container.current)
    return () => {
      observer.disconnect()
      cancelAnimationFrame(frame)
      if (chartRef?.current === instance) chartRef.current = null
      instance.dispose()
    }
  }, [chartRef])
  useEffect(() => {
    chart.current?.setOption(options, { notMerge: true, lazyUpdate: true })
  }, [options])
  return <div ref={container} role="img" aria-label={label} className={'research-plot' + (expanded ? ' is-expanded' : '')} data-dark={dark || undefined} />
})

export function chartTheme(dark) {
  return themes[dark ? 'dark' : 'light']
}

function rangeFor(centre, error) {
  const v = error.values || {}
  if (error.kind === 'symmetric_delta') {
    return { lo: errorEndpoint(centre, v.delta, -1), hi: errorEndpoint(centre, v.delta, 1) }
  }
  if (error.kind === 'asymmetric_delta') {
    return { lo: errorEndpoint(centre, v.minus, -1), hi: errorEndpoint(centre, v.plus, 1) }
  }
  if (error.kind === 'interval_endpoints') return { lo: finite(v.lower), hi: finite(v.upper) }
  return {}
}

function createPoints(rows) {
  return rows.flatMap(row => {
    const centre = row.limit && row.limit !== 'none' ? null : finite(row.typed?.value)
    if (centre === null) return []
    const ranges = (row.error_components || []).map(error => rangeFor(centre, error))
      .filter(pair => Number.isFinite(pair.lo) && Number.isFinite(pair.hi) && pair.lo <= pair.hi)
    return [{ row, centre, ranges }]
  })
}

function drawRange(params, api) {
  const low = api.coord([api.value(0), api.value(1)])
  const high = api.coord([api.value(0), api.value(2)])
  const x = low[0]
  const { x: left, y: top, width, height } = params.coordSys
  if (x < left || x > left + width || low[1] < top || high[1] > top + height) return null
  const y1 = Math.min(top + height, low[1])
  const y2 = Math.max(top, high[1])
  const color = api.visual('color')
  const line = (x1, y1, x2, y2) => ({ type: 'line', shape: { x1, y1, x2, y2 }, style: { stroke: color, lineWidth: 1.5 } })
  return { type: 'group', children: [line(x, y1, x, y2), line(x - 4, y1, x + 4, y1), line(x - 4, y2, x + 4, y2)] }
}

function buildOptions(points, block, dark) {
  const theme = chartTheme(dark)
  const xByYear = block.x === 'year' && points.every(({ row }) => Number.isFinite(row.year))
  const data = xByYear ? [...points].sort((a, b) => a.row.year - b.row.year) : points
  const x = (point, i) => xByYear ? point.row.year : i
  const labels = data.map(({ row }, i) => block.x === 'source' ? row.source : String(i + 1))
  const values = data.map((point, i) => ({ value: [x(point, i), point.centre], recordId: point.row.id }))
  const ranges = data.flatMap((point, i) => point.ranges.map(range => ({ value: [x(point, i), range.lo, range.hi], recordId: point.row.id })))
  const byId = new Map(data.map(point => [point.row.id, point]))
  const kind = block.chart_type
  const type = kind === 'bar' && !xByYear ? 'bar' :
    kind === 'line' && new Set(data.map(p => p.row.conditions)).size <= 1 ? 'line' : 'scatter'
  const bounds = plotBounds(data)
  const single = type !== 'bar' && bounds.valid && bounds.span === 0
  const margin = single ? Math.max(Math.abs(bounds.lo) * .03, .00001) : 0
  const axis = { axisLabel: { color: theme.ink, fontSize: 12 }, axisLine: { lineStyle: { color: theme.line } } }
  return {
    animation: false, backgroundColor: theme.paper, color: [theme.accent], aria: { enabled: true },
    grid: { left: 65, right: 22, top: 30, bottom: 55 },
    tooltip: {
      trigger: 'item', renderMode: 'richText', confine: true, backgroundColor: theme.paper,
      textStyle: { color: theme.ink }, borderColor: theme.line,
      formatter: ({ data: item }) => {
        const row = byId.get(item?.recordId)?.row
        return row ? [row.source, recordText(row), row.error ? '原报误差 ' + row.error : '未报告误差', row.conditions?.slice(0, 150)].filter(Boolean).join('\n') : ''
      },
    },
    xAxis: xByYear ? { ...axis, type: 'value', minInterval: 1, axisLabel: { ...axis.axisLabel, formatter: value => String(value) }, scale: true } :
      { ...axis, type: 'category', data: labels, axisLabel: { ...axis.axisLabel, width: 105, overflow: 'truncate', hideOverlap: true } },
    yAxis: {
      ...axis, type: 'value', scale: type !== 'bar', name: data[0]?.row.unit || '', nameTextStyle: { color: theme.ink },
      min: single ? bounds.lo - margin : undefined,
      max: single ? bounds.hi + margin : undefined,
      axisLabel: { ...axis.axisLabel, formatter: axisNumber }, splitLine: { lineStyle: { color: theme.line, type: 'dashed' } },
    },
    dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'weakFilter', zoomOnMouseWheel: 'ctrl', moveOnMouseWheel: false }],
    series: [
      { type, data: values, symbolSize: 9, barMaxWidth: 30, itemStyle: { color: theme.accent }, z: 3 },
      ...(ranges.length ? [{ type: 'custom', renderItem: drawRange, data: ranges, itemStyle: { color: theme.accent }, encode: { x: 0, y: [1, 2] }, z: 2 }] : []),
    ],
  }
}

export default function AnswerPlot({ block, state, change, onCite, onAsk, dark }) {
  const chartRef = useRef(null)
  const groups = useMemo(() => {
    const result = new Map()
    for (const row of block.rows) {
      const key = [row.target_id, row.property_id, row.unit, row.representation].join('|')
      if (!result.has(key)) result.set(key, { label: [row.property, row.unit, row.representation].filter(Boolean).join(' · '), rows: [] })
      result.get(key).rows.push(row)
    }
    return result
  }, [block.rows])
  const groupKey = groups.has(state.group) ? state.group : groups.keys().next().value
  const group = groups.get(groupKey)
  const sources = useMemo(() => [...new Set(group.rows.map(row => row.source))], [group])
  const conditions = useMemo(() => [...new Set(group.rows.map(row => row.conditions || ''))], [group])
  const rows = useMemo(() => group.rows.filter(row => (!state.source || state.source === row.source) &&
    (state.condition == null || state.condition === (row.conditions || ''))), [group, state.source, state.condition])
  const points = useMemo(() => createPoints(rows), [rows])
  const options = useMemo(() => points.length ? buildOptions(points, block, dark) : null, [points, block, dark])
  const selected = rows.find(row => row.id === state.recordIds?.[0])
  const missingErrors = points.filter(point => !point.row.error && !point.row.error_components?.length).length
  function exportPng() {
    const image = chartRef.current?.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: chartTheme(dark).paper })
    if (!image) return
    const link = document.createElement('a')
    link.href = image
    link.download = 'AstroQuery-测量图.png'
    link.click()
  }
  function openPoint(event) {
    const row = rows.find(item => item.id === event.data?.recordId)
    if (!row) return
    change({ recordIds: [row.id] })
    if (row.citation_id) onCite(row.citation_id)
  }
  return <div className="research-component">
    <BlockHeader title={block.title || '测量比较'}>
      <button type="button" className="research-action" onClick={() => change({ table: !state.table })}>{state.table ? '看图' : '看表'}</button>
      {!state.table && options && <>
        <button type="button" className="research-action" onClick={() => change({ expanded: !state.expanded })}><Icon.Maximize width={15} height={15} />{state.expanded ? '还原' : '放大'}</button>
        <button type="button" className="research-action" onClick={exportPng}><Icon.Download width={15} height={15} />导出图像</button>
      </>}
    </BlockHeader>
    <div className="research-plot-filters">
      {groups.size > 1 && <label>量与单位<select value={groupKey} onChange={e => change({ group: e.target.value, source: '', condition: null })}>
        {[...groups].map(([key, g], i) => <option key={key} value={key}>{g.label || '组 ' + (i + 1)}</option>)}
      </select></label>}
      {sources.length > 1 && <label>来源<select value={state.source || ''} onChange={e => change({ source: e.target.value })}>
        <option value="">全部来源</option>{sources.map(source => <option key={source}>{source}</option>)}
      </select></label>}
      {conditions.length > 1 && <label>条件<select value={state.condition ?? '__all'} onChange={e => change({ condition: e.target.value === '__all' ? null : e.target.value })}>
        <option value="__all">全部条件</option>{conditions.map(condition => <option key={condition} value={condition}>{condition ? condition.slice(0, 65) : '未记录条件'}</option>)}
      </select></label>}
    </div>
    {state.table || !options ? <>
      {!options && !state.table && <p className="research-quiet">这组数据没有可定位的单点数值，可在表中查看原报。</p>}
      {rows.length > 0 && <AnswerTable block={{ ...block, columns: ['original', 'error', 'conditions', 'source'], rows }} state={state} change={change} onCite={onCite} onAsk={onAsk} compact={!state.table} />}
    </> : <>
      <ChartCanvas options={options} label={block.title || '测量图，可切换为表格'} chartRef={chartRef} onClick={openPoint} expanded={state.expanded} dark={dark} />
      <footer className="research-block-foot">
        <span>{points.length} 个测量点{missingErrors ? ' · ' + missingErrors + ' 项未报误差' : ''}
          {rows.length > points.length ? ' · 其余原报可在表中查看' : ''}</span>
        {selected && <>
          <CiteButton id={selected.citation_id} onCite={onCite}>{recordText(selected)} · {selected.source}</CiteButton>
          <button type="button" className="research-action" onClick={() => onAsk({ recordIds: [selected.id], prompt: '这条测量为什么不同？' })}>就此追问</button>
        </>}
      </footer>
    </>}
  </div>
}
