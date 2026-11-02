import { useEffect, useMemo, useRef, useState } from 'react'
import { measurementSeries, sourceName } from '@/lib/readableData'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { axisTickLabels, labelLines, measurementAxis, resolveSelection } from '@/lib/chartPresentation'

export default function MeasurementDistribution({ records = [], sources = [], quality, onOpenRecord, onOpenRecords }) {
  const propertyLabel = usePropertyLabel()
  const groups = useMemo(() => measurementSeries(records, quality), [records, quality])
  const [selected, setSelected] = useState(''), [pointId, setPointId] = useState(null)
  const [width, setWidth] = useState(640)
  const plotRef = useRef(null)
  const key = resolveSelection(selected, groups.map(item => item.key))
  const group = groups.find(item => item.key === key)
  useEffect(() => { if (key !== selected) setSelected(key || '') }, [key])
  useEffect(() => {
    if (!plotRef.current) return
    const observer = new ResizeObserver(([entry]) => { if (entry.contentRect.width > 0) setWidth(Math.max(640, Math.floor(entry.contentRect.width))) })
    observer.observe(plotRef.current)
    return () => observer.disconnect()
  }, [!!group])
  if (!group) return <p className="hint">本次任务未提供测量数据</p>
  const bySource = [...new Set(group.valid.map(row => row.record.source_id))]
  const axis = measurementAxis(group.min, group.max, width > 900 ? 5 : 3)
  const tickLabels = axis ? axisTickLabels(axis.ticks) : []
  const labelWidth = Math.min(230, Math.max(174, width * .22)), right = width - 34
  const x = value => {
    const scale = Math.max(Math.abs(axis.lo), Math.abs(axis.hi), 1e-300)
    return labelWidth + (value / scale - axis.lo / scale) / (axis.hi / scale - axis.lo / scale || 1) * (right - labelWidth)
  }
  const height = 20 + bySource.length * 42
  const active = group.valid.find(row => row.record.record_id === pointId)
  const sourceOf = id => sources.find(source => source.source_id === id)
  return <section className="measurement-chart" data-component="measurement-distribution">
    <div className="measurement-controls"><label htmlFor="measurement-group">测量分组</label><select id="measurement-group" value={group.key} onChange={event => { setSelected(event.target.value); setPointId(null); if (plotRef.current) plotRef.current.scrollTop = 0 }}>{groups.map(item => <option key={item.key} value={item.key}>{item.entity} · {propertyLabel(item.field)} · {item.unit || '无单位'}</option>)}</select></div>
    <div className="chart-description"><span>{group.rows.length} 条测量 · {bySource.length} 个来源</span><span>点：测量值　线：已有误差或区间</span></div>
    <div ref={plotRef} className="measurement-plot-scroll">
      {group.valid.length && axis ? <>
        <svg viewBox={`0 0 ${width} 48`} width={width} height="48" className="measurement-axis" aria-hidden="true"><rect width={width} height="48" fill="var(--seed-surface)" /><text x="18" y="29" fill="var(--content-fg-secondary)" fontSize="13">{group.unit || '数值'}</text>{axis.ticks.map((value, index) => <text key={value} x={x(value)} y="29" textAnchor="middle" fill="var(--content-fg-secondary)" fontSize="13">{tickLabels[index]}</text>)}</svg>
        <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="group" aria-label={`${propertyLabel(group.field)}多来源测量图，共享数值轴`} className="shared-measurement-plot">
          {axis.ticks.map(value => <line key={value} x1={x(value)} x2={x(value)} y1="0" y2={height} stroke="var(--surface-border)" strokeDasharray="3 5" />)}
          {bySource.map((id, index) => { const y = 24 + index * 42; return <g key={id}><rect x="0" y={y - 20} width={width} height="40" rx="4" fill={active?.record.source_id === id ? 'var(--accent-light)' : 'transparent'} /><title>{sourceName(sourceOf(id), id)}</title><text x={labelWidth - 20} textAnchor="end" fill={active?.record.source_id === id ? 'var(--accent-text)' : 'var(--content-fg-secondary)'} fontSize="13">{labelLines(sourceName(sourceOf(id), id, true), Math.floor((labelWidth - 30) / 7.5)).map((line, i, all) => <tspan key={i} x={labelWidth - 20} y={y + 4 + i * 15 - (all.length - 1) * 7.5}>{line}</tspan>)}</text></g> })}
          {group.valid.map(({ record, measurement: m }) => {
            const rows = group.valid.filter(row => row.record.source_id === record.source_id), offset = rows.findIndex(row => row.record.record_id === record.record_id)
            const y = 24 + bySource.indexOf(record.source_id) * 42 + (offset - (rows.length - 1) / 2) * Math.min(8, 24 / rows.length)
            const label = `${sourceName(sourceOf(record.source_id), record.source_id)}：${record.field_value} ${group.unit}`
            const chosen = active?.record.record_id === record.record_id
            return <g key={record.record_id} role="button" tabIndex={0} aria-label={`查看测量记录 ${label}`} onMouseEnter={() => setPointId(record.record_id)} onFocus={() => setPointId(record.record_id)} onClick={() => onOpenRecord?.(record)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onOpenRecord?.(record) } }} className={`measurement-point${chosen ? ' active' : ''}`}><title>{label}{m.lower != null ? `，范围 ${m.lower} — ${m.upper}` : ''}</title><rect x={Math.min(x(m.lower ?? m.value), x(m.upper ?? m.value)) - 12} y={y - 14} width={Math.max(28, x(m.upper ?? m.value) - x(m.lower ?? m.value) + 24)} height="28" fill="transparent" />{m.lower != null && m.upper != null && <><line x1={x(m.lower)} x2={x(m.upper)} y1={y} y2={y} stroke="var(--accent-text)" strokeWidth={chosen ? 2.5 : 1.5} /><line x1={x(m.lower)} x2={x(m.lower)} y1={y - 4} y2={y + 4} stroke="var(--accent-text)" /><line x1={x(m.upper)} x2={x(m.upper)} y1={y - 4} y2={y + 4} stroke="var(--accent-text)" /></>}{m.value != null && <circle cx={x(m.value)} cy={y} r={chosen ? 5 : 3.5} fill="var(--accent-text)" />}</g>
          })}
        </svg></> : <p className="hint measurement-empty">该组没有可解析的数值</p>}
    </div>
    <div className="measurement-tooltip" role="status" aria-live="polite">{active ? <><strong>{sourceName(sourceOf(active.record.source_id), active.record.source_id)}</strong><span>{active.record.field_value} {group.unit}{active.measurement.lower != null && ` · 范围 ${active.measurement.lower} — ${active.measurement.upper}`}</span></> : <span>悬停或聚焦测量点查看数值，点击打开记录。</span>}</div>
    {group.unparsed > 0 && <p className="hint">{group.unparsed} 条记录未进入图表。<button className="text-link" onClick={() => onOpenRecords?.(group.field)}>查看记录</button></p>}
  </section>
}
