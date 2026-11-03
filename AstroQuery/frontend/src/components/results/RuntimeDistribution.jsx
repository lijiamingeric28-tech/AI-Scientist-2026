import { useMemo, useState } from 'react'
import { plotNumber, errorEndpoint, plotBounds } from '../../lib/numericPlot'

const ROLES = { stat: '统计', sys: '系统', total: '原报总误差', unspecified: '未说明类别' }
function intervals(record) {
  const value = record.derived?.value_typed
  if (!value) return []
  if (value.kind === 'interval') return [{ label: '主值区间', lo: value.lower == null ? null : plotNumber(value.lower), hi: value.upper == null ? null : plotNumber(value.upper) }]
  if (!['real', 'integer'].includes(value.kind)) return []
  const centre = plotNumber(value.value)
  if (centre === null) return []
  return (record.derived.uncertainty_typed?.components || []).flatMap(result => {
    const component = result.output_component
    if (!component?.values || !['exact', 'approximate', 'identity'].includes(result.status)) return []
    const values = component.values
    const bounds = component.kind === 'symmetric_delta' ? [errorEndpoint(centre, values.delta, -1), errorEndpoint(centre, values.delta, 1)] : component.kind === 'asymmetric_delta' ? [values.minus == null ? null : errorEndpoint(centre, values.minus, -1), values.plus == null ? null : errorEndpoint(centre, values.plus, 1)] : component.kind === 'interval_endpoints' ? [values.lower == null ? null : plotNumber(values.lower), values.upper == null ? null : plotNumber(values.upper)] : null
    return bounds ? [{ label: `${ROLES[component.role]}${component.level ? `；${component.level.raw_text}` : '；水平未说明'}`, lo: bounds[0], hi: bounds[1] }] : []
  })
}

export default function RuntimeDistribution({ records, onOpenRecord, quality }) {
  const [selected, setSelected] = useState('')
  const [page, setPage] = useState(0)
  const groups = useMemo(() => {
    const map = new Map()
    records.forEach(record => record.comparison_groups?.forEach(group => {
      if (!map.has(group.group_id)) map.set(group.group_id, { ...group, label: record.field_name, unit: record.field_unit, records: [] })
      map.get(group.group_id).records.push(record)
    }))
    return [...map.values()]
  }, [records])
  const group = groups.find(item => item.group_id === selected) || groups[0]
  if (!group) return <p>{quality?.schema_version === 'TaskCompletionScore/1' ? '本任务的对照仅归档有证据的重复和核对明显疑似矛盾，不生成统计分布组。全部原报、独立误差和来源保留在数据表与详情中。' : '尚无满足已审定比较前提的测量组。缺少条件或尚未标准化的记录仍保留在数据表中。'}</p>
  const pageCount = Math.ceil(group.records.length / 30)
  const currentPage = Math.min(page, pageCount - 1)
  const pageRecords = group.records.slice(currentPage * 30, (currentPage + 1) * 30)
  const points = pageRecords.flatMap(record => {
    const value = record.derived?.value_typed
    const centre = ['real', 'integer'].includes(value?.kind) ? plotNumber(value.value) : null
    const ranges = intervals(record).filter(range => (range.lo === null || Number.isFinite(range.lo)) && (range.hi === null || Number.isFinite(range.hi)))
    return centre === null && !ranges.length || centre !== null && !Number.isFinite(centre) ? [] : [{ record, centre, ranges }]
  })
  const { lo, hi, span, valid: axisValid } = plotBounds(points)
  const x = value => span ? 160 + (value - lo) / span * 590 : 455
  const rows = points.flatMap(point => point.ranges.length ? point.ranges.slice(0, 16).map(range => ({ ...point, range })) : [{ ...point, range: null }])
  const limited = records.filter(record => !record.comparison_groups?.length)
  return <section><label>已核实可比组 <select value={group.group_id} onChange={event => { setSelected(event.target.value); setPage(0) }}>{groups.map((item, i) => <option value={item.group_id} key={item.group_id}>{item.label} · 组 {i + 1} · {item.records.length} 条</option>)}</select></label><p className="hint">按对象、性质和必要条件分组。误差分量分别展示，未标置信水平的不当作1σ。主值仅区间时不补中心点。图轴无法保持数值区别的主值或端点不绘制；精确值始终保留在详情。每页30条，每条图示最多16个分量，其余分量见详情。</p>
    {axisValid && rows.length ? <svg viewBox={`0 0 800 ${rows.length * 48 + 55}`} style={{ width: '100%', minWidth: 360 }} role="img" aria-label={`${group.label}可比测量分布`}><text x="160" y="20" fill="currentColor">{lo} {group.unit}</text><text x="750" y="20" textAnchor="end" fill="currentColor">{hi} {group.unit}</text>{rows.map((row, i) => { const y = 48 + i * 48; return <g key={`${row.record.record_id}-${i}`}><title>{row.record.field_value} {group.unit}；{row.range?.label || '未绘制误差区间'}</title><text x="8" y={y} fill="currentColor" fontSize="11">测量 {group.records.indexOf(row.record) + 1}{row.range ? ` · ${row.range.label}` : ''}</text>{row.range?.lo != null && row.range?.hi != null && <line x1={x(row.range.lo)} x2={x(row.range.hi)} y1={y + 10} y2={y + 10} stroke="var(--accent-text)" strokeWidth="2" />}{row.range?.lo != null && <path d={`M ${x(row.range.lo)} ${y + 5} v 10`} stroke="var(--accent-text)" />}{row.range?.hi != null && <path d={`M ${x(row.range.hi)} ${y + 5} v 10`} stroke="var(--accent-text)" />}{row.centre != null && <circle cx={x(row.centre)} cy={y + 10} r="4" fill="var(--accent-text)" />}</g> })}</svg> : <p>该组的值类型或数值范围不适合数值轴；请查看下列完整原报值。</p>}
    <table><thead><tr><th>测量</th><th>值</th><th>误差与上下文</th></tr></thead><tbody>{pageRecords.map((record, i) => <tr key={record.record_id}><td>{currentPage * 30 + i + 1}</td><td>{record.field_value} {record.field_unit}</td><td><button className="text-link" onClick={() => onOpenRecord?.(record)}>查看各分量、原件和条件</button></td></tr>)}</tbody></table>{pageCount > 1 && <p><button disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>上一页</button> {currentPage + 1} / {pageCount} <button disabled={currentPage + 1 >= pageCount} onClick={() => setPage(currentPage + 1)}>下一页</button></p>}{limited.length > 0 && <p>{limited.length} 条记录因比较前提不足而未合并绘制，仍可在数据表查看。</p>}
  </section>
}
