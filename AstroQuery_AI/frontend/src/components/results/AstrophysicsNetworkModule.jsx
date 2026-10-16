import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { normalizeInsights } from '@/lib/readableData'
import { labelLines, relationshipKeys, resolveSelection } from '@/lib/chartPresentation'
import { Prose, References } from './ReadableContent'
import { relationshipEndpoints } from '@/lib/viewGeometry'

export default function RelationshipGraph({ insights }) {
  const propertyLabel = usePropertyLabel()
  const relations = normalizeInsights(insights).relations.filter(row => row.field_a && row.field_b)
  const keys = relationshipKeys(relations)
  const [selected, setSelected] = useState(null)
  const plotRef = useRef(null)
  const [plotWidth, setPlotWidth] = useState(640)
  const key = resolveSelection(selected, keys)
  useEffect(() => { if (key !== selected) setSelected(key) }, [key])
  useLayoutEffect(() => {
    const plot = plotRef.current
    if (!plot) return
    const resize = () => { if (plot.clientWidth > 0) setPlotWidth(Math.floor(plot.clientWidth)) }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(plot)
    return () => observer.disconnect()
  }, [Boolean(relations.length)])
  if (!relations.length) return <p className="hint">本次任务未提供字段关系</p>
  const active = keys.indexOf(key), row = relations[active]
  const formula = typeof row.formula === 'string' ? row.formula : null
  const nodes = [...new Set(relations.flatMap(row => [row.field_a, row.field_b]))]
  const width = Math.max(plotWidth, nodes.length <= 6 ? 520 : Math.ceil(nodes.length / 6) * 640), height = Math.max(360, Math.ceil(nodes.length / 8) * 360)
  const positions = Object.fromEntries(nodes.map((node, index) => [node, { x: width / 2 + (width / 2 - 100) * Math.cos(index / nodes.length * 2 * Math.PI), y: height / 2 + (height / 2 - 55) * Math.sin(index / nodes.length * 2 * Math.PI) }]))
  return <section className="relationship-section" data-component="relationship-graph"><div className="relationship-browser">
    <div ref={plotRef} className="relationship-plot"><svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="任务已有字段关系图">
      {relations.map((rel, index) => { const a = positions[rel.field_a], b = positions[rel.field_b]; return <line key={keys[index]} {...relationshipEndpoints(a, b)} stroke={index === active ? 'var(--accent)' : 'var(--chart-grid)'} opacity={index === active ? 1 : .48} strokeWidth={index === active ? 2.5 : 1} strokeLinecap="round" /> })}
      {nodes.map(node => { const chosen = node === row.field_a || node === row.field_b, lines = labelLines(propertyLabel(node), 16); return <g key={node}><title>{propertyLabel(node)}</title><rect x={positions[node].x - 85} y={positions[node].y - 25} width="170" height="50" rx="10" fill={chosen ? 'var(--relation-node-active)' : 'var(--seed-surface)'} stroke={chosen ? 'var(--accent)' : 'var(--header-border)'} /><text textAnchor="middle" fontSize="13" fontWeight={chosen ? 550 : 400} fill={chosen ? 'var(--accent-text)' : 'var(--content-fg-secondary)'}>{lines.map((line,i) => <tspan key={i} x={positions[node].x} y={positions[node].y + 4 + i * 16 - (lines.length - 1) * 8}>{line}</tspan>)}</text></g> })}
    </svg></div><nav className="relationship-list" aria-label="选择字段关系">{relations.map((rel, index) => <button key={keys[index]} aria-current={index === active ? 'true' : undefined} className={index === active ? 'active' : ''} onClick={() => setSelected(keys[index])}>{propertyLabel(rel.field_a)} <span>↔</span> {propertyLabel(rel.field_b)}</button>)}</nav>
  </div><article className="relationship-explanation"><h3>{propertyLabel(row.field_a)}与{propertyLabel(row.field_b)}</h3><Prose value={row.description} />{formula && <div className="relationship-formula"><h4>关系公式</h4><p>{formula}</p></div>}<References values={row.kb_references} /></article></section>
}
