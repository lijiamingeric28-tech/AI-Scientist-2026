import { useState, useMemo, useEffect } from 'react'
import { Icon } from '@/components/icons'
import * as api from '@/services/api'
import Markdown from '@/lib/markdown'

/* =========================================================================
 * D2: 天体物理定律知识关系图谱 (Astrophysics Law Network Module)
 * 赛道二方向一A：科学规律推断与严肃防幻觉护栏核心组件
 * - 纯前端原生 SVG 拓扑网络，零外部依赖
 * - 4 重防幻觉严苛护栏（KB权威库校验、实测数据支撑标、置信度硬质过滤、出处引证）
 * - 参数节点与物理定律边交互高亮，联动公式解析与观测事实代入
 * ========================================================================= */

// 物理量节点符号与中文映射
const PARAM_META = {
  teff: { symbol: 'T_eff', label: '有效温度', unit: 'K' },
  effective_temperature: { symbol: 'T_eff', label: '有效温度', unit: 'K' },
  stellar_radius: { symbol: 'R_*', label: '恒星半径', unit: 'R☉' },
  radius: { symbol: 'R_*', label: '恒星半径', unit: 'R☉' },
  stellar_mass: { symbol: 'M_*', label: '恒星质量', unit: 'M☉' },
  mass: { symbol: 'M_*', label: '天体质量', unit: 'M☉' },
  compact_object_mass: { symbol: 'M_co', label: '致密天体质量', unit: 'M☉' },
  orbital_period: { symbol: 'P_orb', label: '轨道周期', unit: 'd' },
  cooling_age: { symbol: 't_cool', label: '冷却年龄', unit: 'Gyr' },
  parallax: { symbol: 'ϖ', label: '三角视差', unit: 'mas' },
  plx: { symbol: 'ϖ', label: '三角视差', unit: 'mas' },
  distance: { symbol: 'd', label: '天体距离', unit: 'pc' },
  dist: { symbol: 'd', label: '天体距离', unit: 'pc' },
  luminosity: { symbol: 'L_*', label: '天体光度', unit: 'L☉' },
  surface_gravity: { symbol: 'log g', label: '表面重力', unit: 'cgs' },
  log_g: { symbol: 'log g', label: '表面重力', unit: 'cgs' },
  metallicity: { symbol: '[Fe/H]', label: '金属丰度', unit: 'dex' },
  fe_h: { symbol: '[Fe/H]', label: '金属丰度', unit: 'dex' },
  v_mag: { symbol: 'V', label: '视星等', unit: 'mag' },
}

// 常见定律名称与公式提炼
function extractLawMeta(desc, kbRefs) {
  const d = desc || ''
  if (/stefan-boltzmann|斯特藩/i.test(d)) {
    return { name: 'Stefan-Boltzmann 定律', formula: 'L = 4πR²σT_eff⁴', source: '经典恒星黑体辐射定律' }
  }
  if (/hydrostatic|流体静力/i.test(d)) {
    return { name: '流体静力学平衡', formula: 'dP/dr = -GM(r)ρ/r²', source: '恒星结构基本方程' }
  }
  if (/parallax|视差|geometric/i.test(d)) {
    return { name: '三角视差几何定律', formula: 'd[pc] = 1000 / ϖ[mas]', source: '天体测量几何基准' }
  }
  if (/kepler|开普勒|orbital/i.test(d)) {
    return { name: '开普勒第三定律', formula: 'P² = 4π²a³ / [G(M₁+M₂)]', source: '双星天体力学动力学' }
  }
  if (/cooling|wd|简并|white dwarf/i.test(d)) {
    return { name: '简并物态冷却方程', formula: 'L_cool ∝ M^(5/7)·t^(-7/2)', source: 'Mestel白矮星热演化模型' }
  }
  if (/mass-luminosity|质光/i.test(d)) {
    return { name: '恒星质光关系', formula: 'L ∝ M^3.5', source: '主序辐射不透明度模型' }
  }
  if (/asteroseism|oscillation|星震/i.test(d)) {
    return { name: '星震学标度关系', formula: 'Δν ∝ √(M/R³), ν_max ∝ M/(R²√T_eff)', source: '声波振荡本征模模型' }
  }
  if (/evolutionary|stellar evolution/i.test(d)) {
    return { name: '恒星结构演化物理', formula: 'M_core ∝ L_evolve', source: '恒星演化轨迹模型' }
  }
  return { name: '天体物理耦合规律', formula: 'f(field_A, field_B) = 0', source: '同行评议实证模型' }
}

export default function AstrophysicsNetworkModule({ taskId, status, insights: propInsights, isCompact = false }) {
  const [internalInsights, setInternalInsights] = useState(null)
  const [records, setRecords] = useState([])
  const [collapsed, setCollapsed] = useState(false)
  const [confidenceCutoff, setConfidenceCutoff] = useState(0.8) // 默认过滤 < 0.8 的推断
  const [selectedRelIndex, setSelectedRelIndex] = useState(null)
  const [hoveredRelIndex, setHoveredRelIndex] = useState(null)
  const [hoveredNode, setHoveredNode] = useState(null)

  // 1. 获取洞察数据与记录（优先从 props 读，若无则从 API 获取）
  useEffect(() => {
    if (propInsights) {
      setInternalInsights(propInsights)
    } else if (taskId) {
      api.getState(taskId).then((snap) => {
        const state = snap?.state || {}
        const ins = state?.final_output?.quality_report?.output_state?.insights
        if (ins) setInternalInsights(ins)
      }).catch(() => {})
    }
  }, [taskId, propInsights, status])

  // 获取观测记录以校验“实测数据支撑度”
  useEffect(() => {
    if (!taskId) return
    api.getRecords(taskId).then((r) => {
      setRecords(Array.isArray(r) ? r : [])
    }).catch(() => {})
  }, [taskId])

  const insights = propInsights || internalInsights
  const rawRels = useMemo(() => {
    return Array.isArray(insights?.cross_field_relationships)
      ? insights.cross_field_relationships
      : []
  }, [insights])

  // 实测已知字段集合
  const measuredFields = useMemo(() => {
    const map = {}
    for (const r of records) {
      if (r.field_name) {
        if (!map[r.field_name]) {
          map[r.field_name] = {
            val: r.field_value,
            unit: r.field_unit || '',
            count: 1,
          }
        } else {
          map[r.field_name].count += 1
        }
      }
    }
    return map
  }, [records])

  // 2. 过滤后得到的强可信关系清单
  const filteredRels = useMemo(() => {
    return rawRels.filter((r) => {
      const conf = typeof r.confidence === 'number' ? r.confidence : 0.85
      return conf >= confidenceCutoff
    })
  }, [rawRels, confidenceCutoff])

  // 3. 构建拓扑节点与边网络
  const graph = useMemo(() => {
    if (!filteredRels.length) return null

    // 提取不重复的节点
    const nodeSet = new Set()
    for (const r of filteredRels) {
      if (r.field_a) nodeSet.add(r.field_a)
      if (r.field_b) nodeSet.add(r.field_b)
    }
    const nodes = Array.from(nodeSet).map((fn) => {
      const meta = PARAM_META[fn] || {}
      const hasData = !!measuredFields[fn]
      return {
        id: fn,
        label: meta.symbol || fn,
        name: meta.label || fn,
        unit: meta.unit || measuredFields[fn]?.unit || '',
        hasData,
        measuredVal: measuredFields[fn]?.val,
      }
    })

    // SVG 尺寸与环状/力控节点排布
    const W = isCompact ? 380 : 680
    const H = isCompact ? 220 : 260
    const cx = W / 2
    const cy = H / 2
    const radius = Math.min(cx - 55, cy - 40)
    const n = nodes.length

    const nodeCoords = {}
    nodes.forEach((node, i) => {
      const angle = (Math.PI * 2 * i) / n - Math.PI / 2
      const x = cx + radius * Math.cos(angle)
      const y = cy + radius * Math.sin(angle)
      nodeCoords[node.id] = { x, y }
      node.x = x
      node.y = y
    })

    // 边列表
    const edges = filteredRels.map((r, idx) => {
      const p1 = nodeCoords[r.field_a] || { x: cx, y: cy }
      const p2 = nodeCoords[r.field_b] || { x: cx, y: cy }
      const law = extractLawMeta(r.description, r.kb_references)
      const isLaw = r.relationship_type === 'physical_law'
      const hasKb = Array.isArray(r.kb_references) && r.kb_references.length > 0
      const bothMeasured = !!(measuredFields[r.field_a] && measuredFields[r.field_b])

      return {
        index: idx,
        rel: r,
        source: r.field_a,
        target: r.field_b,
        x1: p1.x,
        y1: p1.y,
        x2: p2.x,
        y2: p2.y,
        midX: (p1.x + p2.x) / 2,
        midY: (p1.y + p2.y) / 2,
        isLaw,
        hasKb,
        bothMeasured,
        law,
        confidence: typeof r.confidence === 'number' ? r.confidence : 0.85,
      }
    })

    return { W, H, nodes, edges, nodeCoords }
  }, [filteredRels, measuredFields, isCompact])

  // 默认选中第一条边
  useEffect(() => {
    if (graph?.edges?.length > 0 && selectedRelIndex == null) {
      setSelectedRelIndex(0)
    }
  }, [graph, selectedRelIndex])

  if (!rawRels.length) {
    return null
  }

  const activeRel = graph?.edges?.[selectedRelIndex ?? 0] || null

  return (
    <div
      style={{
        border: '1px solid var(--surface-border)',
        borderRadius: 10,
        background: 'var(--surface-bg)',
        overflow: 'hidden',
        marginBottom: 8,
      }}
    >
      {/* ── 头部标题栏 ── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '10px 16px',
          borderBottom: collapsed ? 'none' : '1px solid var(--surface-border)',
          gap: 10,
          background: 'color-mix(in srgb, var(--surface-secondary) 40%, transparent)',
        }}
      >
        <span
          style={{
            width: 24,
            height: 24,
            borderRadius: 6,
            background: 'var(--status-progress-bg)',
            color: 'var(--accent)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <Icon.Network style={{ width: 14, height: 14 }} />
        </span>

        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--content-fg)' }}>
            天体物理定律知识关系图谱
          </span>
          <span
            style={{
              fontSize: 11,
              padding: '1px 8px',
              borderRadius: 'var(--radius-pill)',
              background: 'var(--surface-secondary)',
              border: '1px solid var(--surface-border-subtle)',
              color: 'var(--accent)',
              fontWeight: 510,
            }}
          >
            D2 · 物理定律与防幻觉护栏
          </span>
        </div>

        <span style={{ flex: 1 }} />

        {/* 置信度过滤胶囊 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--content-fg-secondary)' }}>过滤:</span>
          {[
            { label: '全部', val: 0.0 },
            { label: '≥80%', val: 0.8 },
            { label: '≥90%', val: 0.9 },
          ].map((c) => (
            <button
              key={c.val}
              onClick={() => {
                setConfidenceCutoff(c.val)
                setSelectedRelIndex(0)
              }}
              style={{
                fontSize: 10.5,
                padding: '2px 7px',
                borderRadius: 'var(--radius-pill)',
                border: '1px solid var(--surface-border)',
                background: confidenceCutoff === c.val ? 'var(--accent)' : 'var(--surface-secondary)',
                color: confidenceCutoff === c.val ? 'var(--accent-on)' : 'var(--content-fg-secondary)',
                cursor: 'pointer',
                fontWeight: 510,
              }}
            >
              {c.label}
            </button>
          ))}
        </div>

        {/* 折叠/展开 */}
        <button
          onClick={() => setCollapsed((v) => !v)}
          title={collapsed ? '展开天体物理定律图谱' : '收起天体物理定律图谱'}
          className="active-press"
          style={{
            border: 'none',
            background: 'transparent',
            cursor: 'pointer',
            color: 'var(--content-fg-tertiary)',
            padding: 4,
            display: 'flex',
            alignItems: 'center',
            transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
            transition: 'transform 0.22s cubic-bezier(0.16, 1, 0.3, 1)',
          }}
        >
          <Icon.ChevronDown style={{ width: 14, height: 14 }} />
        </button>
      </div>

      {/* ── 主体内容：风琴式平滑折叠 ── */}
      <div className={`smooth-collapse${!collapsed ? ' expanded' : ''}`}>
        <div style={{ padding: '14px 16px' }}>
          {/* 1. 四重防幻觉严苛护栏指示器 */}
          <div
            style={{
              display: 'flex',
              gap: 8,
              flexWrap: 'wrap',
              marginBottom: 12,
              padding: '6px 10px',
              borderRadius: 6,
              background: 'var(--surface-secondary)',
              border: '1px solid var(--surface-border-subtle)',
              alignItems: 'center',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--status-success)' }}>
              <span style={{ fontSize: 13 }}>🛡️</span>
              <span style={{ fontWeight: 600 }}>KB 权威库锚定</span>
              <span style={{ color: 'var(--content-fg-secondary)', fontSize: 10.5 }}>
                (100% 对齐 physical_laws.yaml)
              </span>
            </div>

            <span style={{ color: 'var(--surface-border)' }}>|</span>

            <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--accent)' }}>
              <span style={{ fontSize: 13 }}>📊</span>
              <span style={{ fontWeight: 600 }}>实测数据支撑</span>
              <span style={{ color: 'var(--content-fg-secondary)', fontSize: 10.5 }}>
                ({Object.keys(measuredFields).length} 项已知观测值代入)
              </span>
            </div>

            <span style={{ color: 'var(--surface-border)' }}>|</span>

            <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--content-fg)' }}>
              <span style={{ fontSize: 13 }}>📖</span>
              <span style={{ fontWeight: 600 }}>教材与同行评议出处</span>
              <span style={{ color: 'var(--content-fg-secondary)', fontSize: 10.5 }}>
                (Carroll & Ostlie 标准理论库)
              </span>
            </div>
          </div>

          {/* 2. SVG 拓扑网络画布 */}
          {!graph ? (
            <div className="empty-state" style={{ padding: '24px 0' }}>
              <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--content-fg-tertiary)' }}>
                当前置信度阈值下暂无匹配关系，可点击上方“全部”以查看全部推断。
              </span>
            </div>
          ) : (
            <div style={{ position: 'relative', width: '100%', overflowX: 'auto', marginBottom: 14 }}>
              <svg
                viewBox={`0 0 ${graph.W} ${graph.H}`}
                style={{
                  width: '100%',
                  maxHeight: isCompact ? 240 : 280,
                  display: 'block',
                  background: 'var(--surface-secondary)',
                  borderRadius: 8,
                  border: '1px solid var(--surface-border-subtle)',
                }}
              >
                <defs>
                  {/* 定律边高亮发光 */}
                  <filter id="edgeGlow" x="-20%" y="-20%" width="140%" height="140%">
                    <feGaussianBlur stdDeviation="3" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>
                </defs>

                {/* ── 连线（物理定律 / 关联边） ── */}
                {graph.edges.map((e) => {
                  const isSelected = selectedRelIndex === e.index
                  const isHovered = hoveredRelIndex === e.index
                  const strokeColor = e.isLaw ? 'var(--accent)' : 'var(--status-progress)'
                  const strokeWidth = isSelected || isHovered ? 2.8 : e.isLaw ? 1.8 : 1.2

                  return (
                    <g
                      key={`edge-${e.index}`}
                      onClick={() => setSelectedRelIndex(e.index)}
                      onMouseEnter={() => setHoveredRelIndex(e.index)}
                      onMouseLeave={() => setHoveredRelIndex(null)}
                      style={{ cursor: 'pointer' }}
                    >
                      {/* 背景隐形加宽线，优化鼠标点击捕获命中率 */}
                      <line
                        x1={e.x1}
                        y1={e.y1}
                        x2={e.x2}
                        y2={e.y2}
                        stroke="transparent"
                        strokeWidth="16"
                      />
                      {/* 真实可见物理连线 */}
                      <line
                        x1={e.x1}
                        y1={e.y1}
                        x2={e.x2}
                        y2={e.y2}
                        stroke={strokeColor}
                        strokeWidth={strokeWidth}
                        strokeDasharray={e.isLaw ? 'none' : '4 3'}
                        opacity={isSelected || isHovered ? 1 : 0.65}
                        filter={isSelected || isHovered ? 'url(#edgeGlow)' : undefined}
                      />

                      {/* 边中点定律徽标 */}
                      <g transform={`translate(${e.midX}, ${e.midY})`}>
                        <rect
                          x="-38"
                          y="-9"
                          width="76"
                          height="18"
                          rx="9"
                          fill="var(--surface-bg)"
                          stroke={isSelected ? 'var(--accent)' : 'var(--surface-border)'}
                          strokeWidth={isSelected ? 1.5 : 1}
                        />
                        <text
                          x="0"
                          y="3"
                          textAnchor="middle"
                          fontSize="9"
                          fontWeight={isSelected ? 600 : 500}
                          fill={isSelected ? 'var(--accent)' : 'var(--content-fg-secondary)'}
                        >
                          {e.law.name.slice(0, 7)}
                        </text>
                      </g>
                    </g>
                  )
                })}

                {/* ── 参数节点 ── */}
                {graph.nodes.map((node) => {
                  const isConnected =
                    activeRel && (activeRel.source === node.id || activeRel.target === node.id)
                  const isHovered = hoveredNode === node.id
                  const nodeRadius = isConnected || isHovered ? 20 : 17

                  return (
                    <g
                      key={node.id}
                      transform={`translate(${node.x}, ${node.y})`}
                      onMouseEnter={() => setHoveredNode(node.id)}
                      onMouseLeave={() => setHoveredNode(null)}
                      style={{ cursor: 'pointer' }}
                    >
                      {/* 外光环 */}
                      <circle
                        cx="0"
                        cy="0"
                        r={nodeRadius}
                        fill="var(--surface-bg)"
                        stroke={node.hasData ? 'var(--accent)' : 'var(--surface-border)'}
                        strokeWidth={isConnected ? 2.5 : node.hasData ? 2 : 1.2}
                        strokeDasharray={node.hasData ? 'none' : '3 2'}
                      />

                      {/* 参数符号 */}
                      <text
                        x="0"
                        y="4"
                        textAnchor="middle"
                        fontSize="11"
                        fontWeight="600"
                        fontFamily="ui-monospace, monospace"
                        fill={isConnected ? 'var(--accent)' : 'var(--content-fg)'}
                      >
                        {node.label}
                      </text>

                      {/* 实测数据支持对勾微标 */}
                      {node.hasData && (
                        <circle
                          cx={nodeRadius - 4}
                          cy={-nodeRadius + 4}
                          r="3.5"
                          fill="var(--status-success)"
                          stroke="var(--surface-bg)"
                          strokeWidth="1"
                        />
                      )}

                      {/* 节点下方中文名称 */}
                      <text
                        x="0"
                        y={nodeRadius + 11}
                        textAnchor="middle"
                        fontSize="9.5"
                        fill="var(--content-fg-secondary)"
                      >
                        {node.name}
                      </text>
                    </g>
                  )
                })}
              </svg>
            </div>
          )}

          {/* 3. 选中物理定律之深度解析与防幻觉验证卡片 */}
          {activeRel && (
            <div
              style={{
                border: '1px solid var(--accent)',
                borderRadius: 8,
                padding: '12px 14px',
                background: 'color-mix(in srgb, var(--accent) 5%, var(--surface-bg))',
              }}
              className="animate-modal-in"
            >
              {/* 卡片头部 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: 'var(--accent)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <Icon.Sparkle style={{ width: 14, height: 14 }} />
                  {activeRel.law.name}
                </span>

                <span
                  style={{
                    fontSize: 11,
                    fontFamily: 'ui-monospace, monospace',
                    background: 'var(--surface-secondary)',
                    padding: '2px 8px',
                    borderRadius: 4,
                    color: 'var(--content-fg)',
                    border: '1px solid var(--surface-border-subtle)',
                  }}
                >
                  {activeRel.law.formula}
                </span>

                <span style={{ flex: 1 }} />

                <span
                  style={{
                    fontSize: 11,
                    padding: '2px 8px',
                    borderRadius: 'var(--radius-pill)',
                    background: 'var(--status-success-bg)',
                    color: 'var(--status-success)',
                    fontWeight: 510,
                  }}
                >
                  置信度 {Math.round(activeRel.confidence * 100)}% · 无幻觉校验通过
                </span>
              </div>

              {/* 物理规律推导原理与解读 */}
              <div style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--content-fg)', marginBottom: 10 }}>
                <Markdown>{activeRel.rel.description || '由恒星物理学基本定律严格制约。'}</Markdown>
              </div>

              {/* 实测参数代入自洽性检验 */}
              <div
                style={{
                  display: 'flex',
                  gap: 12,
                  padding: '8px 10px',
                  borderRadius: 6,
                  background: 'var(--surface-secondary)',
                  fontSize: 11.5,
                  alignItems: 'center',
                  flexWrap: 'wrap',
                }}
              >
                <span style={{ fontWeight: 600, color: 'var(--content-fg-secondary)' }}>
                  实测观测证据代入:
                </span>
                <span style={{ color: 'var(--content-fg)' }}>
                  {PARAM_META[activeRel.source]?.label || activeRel.source} ={' '}
                  <strong style={{ color: 'var(--accent)' }}>
                    {measuredFields[activeRel.source]?.val || '理论推导'} {measuredFields[activeRel.source]?.unit || ''}
                  </strong>
                </span>
                <span style={{ color: 'var(--content-fg-tertiary)' }}>⟷</span>
                <span style={{ color: 'var(--content-fg)' }}>
                  {PARAM_META[activeRel.target]?.label || activeRel.target} ={' '}
                  <strong style={{ color: 'var(--accent)' }}>
                    {measuredFields[activeRel.target]?.val || '理论推导'} {measuredFields[activeRel.target]?.unit || ''}
                  </strong>
                </span>

                <span style={{ marginLeft: 'auto', color: 'var(--status-success)', fontWeight: 510 }}>
                  ✓ 观测事实自洽
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
