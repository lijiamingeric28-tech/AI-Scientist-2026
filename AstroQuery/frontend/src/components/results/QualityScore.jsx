import { dimensionSummary } from "@/lib/resultData"
import { useId, useState } from "react"

function gradeColor(grade) {
  if (!grade) return 'var(--content-fg-tertiary)'
  const g = String(grade).toLowerCase()
  if (/excellent|good|^a$|^a[-_]|优/.test(g)) return 'var(--status-success)'
  if (/poor|bad|fail|^c$|^d$|^c[-_]|^d[-_]|差/.test(g)) return 'var(--status-error)'
  return 'var(--status-progress)'   // fair / medium / b / 其他 → 中性进度色
}

function scoreColor(v) {
  if (typeof v !== 'number') return 'var(--content-fg-tertiary)'
  if (v >= 0.9) return 'var(--status-success)'
  if (v >= 0.75) return 'var(--status-progress)'
  return 'var(--status-warn)'
}

const QUALITY_DIM_INFO = {
  completeness: {
    label: '完整性',
    desc: '物理性质与元数据字段覆盖率，惩罚未标定或缺失字段',
  },
  consistency: {
    label: '一致性',
    desc: '跨源测量单位、物理量纲与天体物理参数类型一致度',
  },
  format: {
    label: '格式规范',
    desc: '数据值域合规性、数值精度格式与标准化结构契合度',
  },
  source_reliability: {
    label: '来源可信度',
    desc: '权威巡天星表/同行评议核心期刊/高优先级出版源背书可信度',
  },
  conflict_risk: {
    label: '冲突风险',
    desc: '多源交叉观测一致性反比评分，异议越少得分越高',
  },
  extraction_quality: {
    label: '提取质量',
    desc: '大模型与视觉多模态 (VLM) 科学事实提取准确度与保真度',
  },
}

const QUALITY_DIM_LABELS = {
  delivery: '交付就绪',
  adoption: '已知采用限制',
  completeness: '完整性',
  consistency: '一致性',
  format: '格式规范',
  source_reliability: '来源可信度',
  conflict_risk: '冲突风险',
  extraction_quality: '提取质量',
}

function resolveDimensionScores(qScoring, qState) {
  return dimensionSummary(qScoring, qState).scores
}

function RadarChart({ dims, size = 270 }) {
  const [hoveredIdx, setHoveredIdx] = useState(null)
  const gradientId = `radar-${useId().replace(/:/g, '')}`
  const cx = 130
  const cy = 115
  const radius = 68
  const n = dims.length || 1
  const pt = (i, r) => {
    const ang = (Math.PI * 2 * i) / n - Math.PI / 2
    return [cx + r * Math.cos(ang), cy + r * Math.sin(ang)]
  }
  const ringPoly = (frac) => dims.map((_, i) => pt(i, radius * frac).join(',')).join(' ')
  const dataPoly = dims.map((d, i) => {
    const r = radius * Math.max(0.04, Math.min(1, Number(d.score) || 0))
    return pt(i, r).join(',')
  }).join(' ')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100%' }}>
      <svg
        width="100%"
        height={size}
        viewBox="-40 -25 340 280"
        role="img"
        aria-label="质量维度雷达图"
        style={{ overflow: 'visible', maxWidth: 330 }}
      >
        <defs>
          <radialGradient id={gradientId} gradientUnits="userSpaceOnUse" cx={cx} cy={cy} r={radius}>
            <stop offset="0%" stopColor="var(--radar-center)" />
            <stop offset="18%" stopColor="var(--radar-center)" />
            <stop offset="38%" stopColor="var(--radar-pale)" stopOpacity="0.9" />
            <stop offset="60%" stopColor="var(--sage-soft)" stopOpacity="0.8" />
            <stop offset="82%" stopColor="var(--sage)" stopOpacity="0.78" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.8" />
          </radialGradient>
        </defs>
        <polygon points={dataPoly} className="radar-data" fill={`url(#${gradientId})`} />
        {/* 背景同心多边形网格 */}
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <polygon
            key={f}
            points={ringPoly(f)}
            fill="none"
            stroke="var(--chart-grid)"
            strokeWidth={f === 1 ? 1.2 : 0.8}
            strokeDasharray={f === 1 ? 'none' : '3 3'}
          />
        ))}
        {/* 轴线 */}
        {dims.map((_, i) => {
          const [x, y] = pt(i, radius)
          return <line key={`a-${i}`} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--chart-grid)" strokeWidth={1} />
        })}
        {/* Outline stays above the grid; the radial fill stays behind it. */}
        <polygon
          points={dataPoly}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={2}
          style={{ transition: 'fill 0.2s ease, stroke 0.2s ease' }}
        />
        {/* 数据点与交互高亮 */}
        {dims.map((d, i) => {
          const [x, y] = pt(i, radius * Math.max(0.04, Math.min(1, Number(d.score) || 0)))
          const isHov = hoveredIdx === i
          return (
            <g
              key={`pt-group-${i}`}
              onClick={() => setHoveredIdx(i)}
              onMouseEnter={() => setHoveredIdx(i)}
              onMouseLeave={() => setHoveredIdx(null)}
              style={{ cursor: 'pointer' }}
            >
              <title>{`${d.label}: ${Math.round((Number(d.score) || 0) * 100)}%\n${d.desc || ''}`}</title>
              <circle
                cx={x}
                cy={y}
                r={isHov ? 5.5 : 3.2}
                fill={isHov ? 'var(--accent)' : 'var(--accent)'}
                stroke="var(--surface-bg)"
                strokeWidth={isHov ? 2 : 1}
                style={{ transition: 'r 0.15s ease' }}
              />
            </g>
          )
        })}
        {/* 维度文字与百分比标签 */}
        {dims.map((d, i) => {
          const [x, y] = pt(i, radius + 15)
          const isHov = hoveredIdx === i
          const anchor = Math.abs(x - cx) < 10 ? 'middle' : (x < cx ? 'end' : 'start')
          return (
            <g
              key={`label-group-${i}`}
              tabIndex={0}
              onClick={() => setHoveredIdx(i)}
              onFocus={() => setHoveredIdx(i)}
              onBlur={() => setHoveredIdx(null)}
              onMouseEnter={() => setHoveredIdx(i)}
              onMouseLeave={() => setHoveredIdx(null)}
              style={{ cursor: 'pointer' }}
            >
              <title>{`${d.label}: ${Math.round((Number(d.score) || 0) * 100)}%\n${d.desc || ''}`}</title>
              <text
                x={x}
                y={y - 2}
                textAnchor={anchor}
                fontSize={13}
                fontWeight={isHov ? 600 : 500}
                fill={isHov ? 'var(--accent)' : 'var(--content-fg-secondary)'}
              >
                {d.label}
              </text>
              <text
                x={x}
                y={y + 14}
                textAnchor={anchor}
                fontSize={12.5}
                fontWeight={600}
                fill={isHov ? 'var(--accent)' : 'var(--content-fg)'}
              >
                {Math.round((Number(d.score) || 0) * 100)}%
              </text>
            </g>
          )
        })}
      </svg>
      {/* 底部细分指标说明 Tooltip 引导条 */}
      <div className="quality-dimension-description" aria-live="polite">{hoveredIdx != null && dims[hoveredIdx] && <><strong>{dims[hoveredIdx].label}</strong>{dims[hoveredIdx].desc}</>}</div>
    </div>
  )
}

export function QualityScoreSection({ qScoring, qState, normCount, onOpenQuality }) {
  if (!qScoring) {
    return (
      <div className="empty-state" style={{ padding: '20px 12px' }}>
        <span style={{ fontSize: 'var(--fs-sm)' }}>任务进行中，质检完成后展示评分</span>
      </div>
    )
  }
  const overall = typeof qScoring.overall_score === 'number' ? qScoring.overall_score : null
  const rawDims = resolveDimensionScores(qScoring, qState) || {}
  const dims = Object.entries(rawDims).map(([key, score]) => ({
    key,
    label: QUALITY_DIM_INFO[key]?.label || QUALITY_DIM_LABELS[key] || key,
    desc: QUALITY_DIM_INFO[key]?.desc || '',
    score,
  }))
  const level = (qScoring.quality_level || 'unknown').toUpperCase()
  return (
    <div>
      <div className="quality-score-layout" style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 2 }}>
            <span className="font-mono" style={{ fontSize: '2rem', fontWeight: 590, letterSpacing: '-0.03em', lineHeight: 1, color: 'var(--content-fg)' }}>
              {overall == null ? '未提供' : (overall * 100).toFixed(2)}
            </span>
            <span className="font-mono" style={{ fontSize: 'var(--text-note)', color: 'var(--content-fg-tertiary)' }}>/100</span>
          </div>
          <span style={{ fontSize: 'var(--text-note)', fontWeight: 590, letterSpacing: '0.08em', marginTop: 4, color: gradeColor(qScoring.quality_level) }}>{level}</span>
          <div style={{ width: 84, height: 5, borderRadius: 99, background: 'var(--surface-secondary)', marginTop: 6, overflow: 'hidden' }}>
            <div style={{ height: '100%', borderRadius: 99, width: `${overall == null ? '未提供' : (overall * 100).toFixed(2)}%`, background: scoreColor(overall) }} />
          </div>
        </div>
        {/* 雷达图展示区 */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex', justifyContent: 'center' }}>
          <div className="quality-dimensions">{dims.length >= 3 ? <RadarChart dims={dims} /> : dims.length ? <div className="distribution-bars">{dims.map(dimension => <div key={dimension.key}><span>{dimension.label}</span><div><i style={{ width: `${dimension.score * 100}%` }} /></div><strong>{(dimension.score * 100).toFixed(1)}</strong></div>)}</div> : <p className="hint">尚无已核实的质量维度分数</p>}<p className="hint">{dimensionSummary(qScoring, qState).method}</p></div>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
        <span className="section-label">质量等级</span>
        <span style={{ fontSize: 'var(--text-note)', fontWeight: 510, color: gradeColor(qScoring.quality_level) }}>
          {String(qScoring.quality_level || '').toUpperCase()}
        </span>
        {Number.isFinite(normCount) && normCount >= 0 && (
          <span style={{ fontSize: 'var(--text-note)', color: 'var(--content-fg-secondary)' }}>· 归一化 {normCount}</span>
        )}
        <span style={{ flex: 1 }} />
      </div>
    </div>
  )
}
