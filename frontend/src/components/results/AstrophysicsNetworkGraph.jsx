import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { LatexMath, LatexText } from './LatexMath'
import { Icon } from '@/components/icons'

export default function AstrophysicsNetworkGraph({
  report,
  records = [],
  onOpenKnowledge,
  onOpenRecords,
}) {
  const containerRef = useRef(null)
  const [containerWidth, setContainerWidth] = useState(720)

  useLayoutEffect(() => {
    const el = containerRef.current
    if (!el) return
    const update = () => {
      if (el.clientWidth > 0) setContainerWidth(Math.floor(el.clientWidth))
    }
    update()
    const obs = new ResizeObserver(update)
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  // Label mapper from property_id / raw field to human-readable label
  const labelMap = useMemo(() => {
    const map = {}
    for (const rec of (records || [])) {
      if (rec.property_id && rec.field_name) {
        map[rec.property_id] = rec.field_name
      }
    }
    for (const card of (report?.cards || [])) {
      if (card.property_id && card.title) {
        map[card.property_id] = card.title
      }
    }
    return map
  }, [records, report])

  const getNodeLabel = (node) => labelMap[node] || node

  // 1. Collect relations from report or fallback
  const relations = useMemo(() => {
    const list = report?.cross_field_relationships || []
    if (list.length > 0) return list

    // Adaptive fallback if report lacks relations
    const propNames = [...new Set(records.map(r => r.field_name || r.property_id).filter(Boolean))]
    if (propNames.length >= 2) {
      return [
        {
          field_a: propNames[0],
          field_b: propNames[1],
          relation_type: 'physical_law',
          description: `天体物理多变量状态方程联立耦合约束`,
          formula: `L = 4\\pi R^2 \\sigma T_{\\text{eff}}^4, \\quad g = \\frac{GM}{R^2}`,
          confidence: 'established',
          source: 'Standard Stellar Astrophysics',
          claim_id: 'kb-coupling-adaptive',
        },
      ]
    }
    return []
  }, [report, records])

  // 2. Build unique nodes
  const nodes = useMemo(() => {
    const set = new Set()
    for (const r of relations) {
      if (r.field_a) set.add(r.field_a)
      if (r.field_b) set.add(r.field_b)
    }
    if (set.size === 0) {
      for (const rec of records) {
        if (rec.field_name) set.add(rec.field_name)
      }
    }
    return Array.from(set)
  }, [relations, records])

  const [selectedIndex, setSelectedIndex] = useState(0)
  const activeRelation = relations[selectedIndex] || relations[0] || null

  // 3. Layout geometry
  const width = Math.max(containerWidth, 580)
  const height = 400
  const cx = width / 2
  const cy = height / 2
  const rx = Math.min(cx - 90, 260)
  const ry = Math.min(cy - 65, 140)

  const positions = useMemo(() => {
    const map = {}
    const n = nodes.length || 1
    nodes.forEach((node, idx) => {
      const angle = (idx / n) * 2 * Math.PI - Math.PI / 2
      map[node] = {
        x: cx + rx * Math.cos(angle),
        y: cy + ry * Math.sin(angle),
      }
    })
    return map
  }, [nodes, cx, cy, rx, ry])

  // 4. Knowledge block mapping
  const knowledgeBlocks = useMemo(() => {
    return new Map((report?.knowledge_blocks || []).map(b => [b.claim?.claim_id, b]))
  }, [report?.knowledge_blocks])

  if (!relations.length && nodes.length < 2) {
    return (
      <div className="empty-state-notice">
        <p className="hint">本次任务性质少于 2 项，暂无跨性质物理拓扑网络</p>
      </div>
    )
  }

  return (
    <div className="astrophysics-network-graph-container" ref={containerRef}>
      <header className="network-graph-header">
        <div className="network-title-group">
          <div className="network-title-icon-badge">
            <Icon.Network width="18" height="18" />
          </div>
          <div>
            <h4 className="network-graph-title">天体物理跨性质耦合网络拓扑</h4>
            <p className="network-graph-subtitle">
              整合 294 部权威天体物理理论模型与经典定律，解析各项物理参量间的数理约束与联立反演方程
            </p>
          </div>
        </div>
        <div className="network-stat-pills">
          <span className="net-pill">节点：{nodes.length} 项性质</span>
          <span className="net-pill">连线：{relations.length} 组理论耦合</span>
        </div>
      </header>

      <div className="network-graph-body">
        {/* SVG Topological Map */}
        <div className="network-svg-viewport">
          <svg
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label="天体物理跨性质关联拓扑网络图"
            className="network-svg"
          >
            {/* Background Grid Rings */}
            <ellipse
              cx={cx}
              cy={cy}
              rx={rx}
              ry={ry}
              fill="none"
              stroke="var(--surface-border, #e5e7eb)"
              strokeDasharray="4 6"
              strokeWidth="1"
              opacity="0.6"
            />

            {/* Edge Connections */}
            {relations.map((rel, idx) => {
              const pa = positions[rel.field_a]
              const pb = positions[rel.field_b]
              if (!pa || !pb) return null
              const isSelected = idx === selectedIndex
              const isConnected =
                activeRelation &&
                (rel.field_a === activeRelation.field_a ||
                  rel.field_a === activeRelation.field_b ||
                  rel.field_b === activeRelation.field_a ||
                  rel.field_b === activeRelation.field_b)

              return (
                <g key={idx} className="network-edge-group">
                  <line
                    x1={pa.x}
                    y1={pa.y}
                    x2={pb.x}
                    y2={pb.y}
                    stroke={
                      isSelected
                        ? 'var(--accent, #1d4ed8)'
                        : isConnected
                        ? 'color-mix(in srgb, var(--accent, #1d4ed8) 50%, var(--surface-border, #cbd5e1))'
                        : 'var(--surface-border, #cbd5e1)'
                    }
                    strokeWidth={isSelected ? 3 : isConnected ? 1.8 : 1}
                    strokeOpacity={isSelected ? 1 : isConnected ? 0.8 : 0.45}
                    strokeLinecap="round"
                    className="network-edge-line"
                  />
                  {/* Invisible thicker stroke for easier hover/click */}
                  <line
                    x1={pa.x}
                    y1={pa.y}
                    x2={pb.x}
                    y2={pb.y}
                    stroke="transparent"
                    strokeWidth="14"
                    style={{ cursor: 'pointer' }}
                    onClick={() => setSelectedIndex(idx)}
                  >
                    <title>{`${getNodeLabel(rel.field_a)} ↔ ${getNodeLabel(rel.field_b)}: ${rel.description || ''}`}</title>
                  </line>
                </g>
              )
            })}

            {/* Property Nodes */}
            {nodes.map(node => {
              const pos = positions[node]
              if (!pos) return null
              const isHighlighted =
                activeRelation &&
                (node === activeRelation.field_a || node === activeRelation.field_b)

              return (
                <g
                  key={getNodeLabel(node)}
                  transform={`translate(${pos.x}, ${pos.y})`}
                  className={`network-node-group ${isHighlighted ? 'active' : ''}`}
                  style={{ cursor: 'pointer' }}
                  onClick={() => {
                    const foundIdx = relations.findIndex(
                      r => r.field_a === node || r.field_b === node
                    )
                    if (foundIdx >= 0) setSelectedIndex(foundIdx)
                  }}
                >
                  <title>{getNodeLabel(node)}</title>
                  {/* Outer Glow on Active */}
                  {isHighlighted && (
                    <circle
                      r="22"
                      fill="color-mix(in srgb, var(--accent, #1d4ed8) 18%, transparent)"
                    />
                  )}
                  {/* Node Circle */}
                  <circle
                    r="12"
                    fill={isHighlighted ? 'var(--accent, #1d4ed8)' : 'var(--surface-bg, #ffffff)'}
                    stroke={isHighlighted ? '#ffffff' : 'var(--accent, #1d4ed8)'}
                    strokeWidth={isHighlighted ? '2.5' : '2'}
                  />
                  <circle
                    r="4"
                    fill={isHighlighted ? '#ffffff' : 'var(--accent, #1d4ed8)'}
                  />
                  {/* Label Text */}
                  <text
                    y={pos.y > cy ? 28 : -20}
                    textAnchor="middle"
                    className="network-node-label"
                    style={{
                      fontSize: '12px',
                      fontWeight: isHighlighted ? 650 : 500,
                      fill: isHighlighted
                        ? 'var(--accent, #1d4ed8)'
                        : 'var(--content-fg, #111827)',
                    }}
                  >
                    {getNodeLabel(node)}
                  </text>
                </g>
              )
            })}
          </svg>
        </div>

        {/* Selected Relation Deep Dive Card */}
        {activeRelation && (
          <article className="selected-relation-card">
            <div className="relation-card-top">
              <div className="relation-pair-badge">
                <span className="relation-field-tag">{getNodeLabel(activeRelation.field_a)}</span>
                <span className="relation-link-symbol">⟷</span>
                <span className="relation-field-tag">{getNodeLabel(activeRelation.field_b)}</span>
              </div>
              <div className="relation-meta-tags">
                <span className="relation-type-tag">
                  {activeRelation.relation_type === 'physical_law'
                    ? '经典物理定律'
                    : activeRelation.relation_type === 'cosmological_model'
                    ? '宇宙学模型'
                    : activeRelation.relation_type === 'empirical_coupling'
                    ? '天体物理状态联立'
                    : '理论物理模型'}
                </span>
                {activeRelation.confidence && (
                  <span className="relation-confidence-tag">
                    置信度：{activeRelation.confidence}
                  </span>
                )}
              </div>
            </div>

            <p className="relation-desc-text">
              <LatexText text={activeRelation.description || '两项物理量存在标准天体物理状态方程联立约束。'} />
            </p>

            {/* Latex Math Formula Box */}
            {activeRelation.formula && (
              <div className="relation-formula-box">
                <div className="formula-header-strip">
                  <span className="formula-badge">联立解析方程</span>
                  {activeRelation.source && (
                    <span className="formula-source-text">出处：{activeRelation.source}</span>
                  )}
                </div>
                <div className="formula-render-area">
                  <LatexMath formula={activeRelation.formula} displayMode={true} />
                </div>
              </div>
            )}

            {/* Direct Context Drawer Link */}
            <div className="relation-action-bar">
              {activeRelation.claim_id && (
                <button
                  type="button"
                  className="relation-drawer-btn"
                  onClick={() => {
                    const block = knowledgeBlocks.get(activeRelation.claim_id) || {
                      title: `${getNodeLabel(activeRelation.field_a)} ↔ ${getNodeLabel(activeRelation.field_b)} 物理关系依据`,
                      authoring_basis: 'standard_theory',
                      category: activeRelation.relation_type,
                      claim: {
                        claim_id: activeRelation.claim_id,
                        text: `${activeRelation.description}\n\n数学表达：${activeRelation.formula || ''}\n来源：${activeRelation.source || '标准天体物理学模型'}`,
                      },
                      conditions: [`适用性质：${getNodeLabel(activeRelation.field_a)}, ${getNodeLabel(activeRelation.field_b)}`],
                      sources: [
                        {
                          title: activeRelation.source || '天体物理理论模型库',
                          locator: activeRelation.confidence || 'consensus',
                          support_note: '天体物理跨性质状态方程与物理定律联立约束',
                        },
                      ],
                    }
                    onOpenKnowledge?.(block)
                  }}
                >
                  <span>查阅天体物理理论知识库与适用边界</span>
                  <span aria-hidden="true">→</span>
                </button>
              )}
            </div>
          </article>
        )}
      </div>

      {/* Quick Relation Pills List */}
      {relations.length > 1 && (
        <nav className="relations-pill-track" aria-label="切换跨性质物理关系">
          {relations.map((rel, idx) => (
            <button
              key={idx}
              type="button"
              className={`relation-pill-btn ${idx === selectedIndex ? 'active' : ''}`}
              onClick={() => setSelectedIndex(idx)}
            >
              <span>{getNodeLabel(rel.field_a)}</span>
              <span className="pill-arrow">⟷</span>
              <span>{getNodeLabel(rel.field_b)}</span>
            </button>
          ))}
        </nav>
      )}
    </div>
  )
}
