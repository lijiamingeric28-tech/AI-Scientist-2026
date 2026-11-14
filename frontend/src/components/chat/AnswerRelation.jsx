import { useId, useMemo } from 'react'
import { Icon } from '@/components/icons'
import { LatexMath, LatexText } from '@/components/results/LatexMath'
import { BlockHeader, CiteButton } from './AnswerData'

function positions(nodes, edges, layout) {
  const width = 710, height = Math.max(240, Math.ceil(nodes.length / 3) * 98)
  const depth = new Map()
  const remaining = new Set(nodes.map(node => node.id))
  let level = 0
  while (remaining.size) {
    const next = [...remaining].filter(id => !edges.some(edge => edge.target === id && remaining.has(edge.source)))
    if (!next.length) break
    next.forEach(id => { depth.set(id, level); remaining.delete(id) })
    level++
  }
  if (layout === 'network' || remaining.size || level > 4) {
    return { width, height, points: new Map(nodes.map(({ id }, i) => {
      const angle = 2 * Math.PI * i / nodes.length - Math.PI / 2
      return [id, { x: width / 2 + (width / 2 - 95) * Math.cos(angle), y: height / 2 + (height / 2 - 42) * Math.sin(angle) }]
    })) }
  }
  const columns = Array.from({ length: level }, (_, i) => nodes.filter(node => depth.get(node.id) === i))
  const tallest = Math.max(height, Math.max(...columns.map(column => column.length)) * 66 + 24)
  return { width, height: tallest, points: new Map(columns.flatMap((column, col) => column.map(({ id }, row) => [id, {
    x: level === 1 ? width / 2 : 88 + col * (width - 176) / (level - 1),
    y: tallest * (row + 1) / (column.length + 1),
  }]))) }
}

export default function AnswerRelation({ block, state, change, onCite, onAsk, citations }) {
  const arrow = 'relation-' + useId().replace(/[^a-zA-Z0-9-]/g, '')
  const graph = useMemo(() => positions(block.nodes, block.edges, block.layout), [block])
  const node = block.nodes.find(item => item.id === state.node) || block.nodes[0]
  return <div className="research-component">
    <BlockHeader title={block.title || '关系示意'} />
    <div className="research-relation-graph" aria-label="关系示意图" role="group">
      <svg viewBox={'0 0 ' + graph.width + ' ' + graph.height}>
        <defs><marker id={arrow} markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
          <path d="M0,0 L7,3.5 L0,7 Z" fill="currentColor" /></marker></defs>
        {block.edges.map((edge, i) => {
          const from = graph.points.get(edge.source), to = graph.points.get(edge.target)
          const dx = to.x - from.x, dy = to.y - from.y
          if (!dx && !dy) return null
          const step = Math.min(71 / (Math.abs(dx) || 0.001), 24 / (Math.abs(dy) || 0.001))
          return <line key={i} x1={from.x + dx * step} y1={from.y + dy * step} x2={to.x - dx * step} y2={to.y - dy * step}
            stroke="currentColor" strokeWidth="1.5" markerEnd={'url(#' + arrow + ')'} />
        })}
      </svg>
      {block.nodes.map(item => {
        const p = graph.points.get(item.id)
        return <button type="button" key={item.id} aria-pressed={node.id === item.id} className="research-node"
          style={{ left: 100 * p.x / graph.width + '%', top: 100 * p.y / graph.height + '%' }}
          onClick={() => change({ node: item.id })}><LatexText text={item.label} /></button>
      })}
    </div>
    <div className="research-relation-detail">
      <strong><LatexText text={node.label} /></strong>
      {node.description && <p><LatexText text={node.description} /></p>}
      {node.latex && <LatexMath math={node.latex} displayMode />}
      {block.edges.filter(edge => edge.source === node.id && edge.label).map((edge, i) =>
        <p key={i} className="research-node-edge"><Icon.ArrowRight width={15} height={15} /><LatexText text={block.nodes.find(item => item.id === edge.target)?.label} /><span>{edge.label}</span></p>)}
      <footer className="research-block-foot">
        {node.refs.map(id => <CiteButton key={id} id={id} onCite={onCite}>{citations[id]?.label || '查看依据'}</CiteButton>)}
        <button type="button" className="research-action" onClick={() => onAsk({ refs: node.refs, prompt: '请解释「' + node.label + '」。' })}>就此追问</button>
      </footer>
    </div>
  </div>
}
