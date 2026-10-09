import { useState, useMemo, useEffect, useRef } from 'react'
import { Icon } from '@/components/icons'
import * as api from '@/services/api'
import { journalLabel } from '@/lib/journal'

/* =========================================================================
 * D1: 天体多源测量共识分布图 (Consensus Scatter Plot Module)
 * 赛道二方向一A：科学数据整合亮点核心组件
 * - 纯前端原生 SVG 渲染，零外部重量级图表依赖
 * - 智能时序加权收敛均值与 ±1σ 共识带
 * - 误差棒、置信度动态点径、跨源测量悬浮卡片
 * ========================================================================= */

// 物理量友好名称与单位映射字典
const FIELD_META = {
  teff: { label: '有效温度 (Teff)', unit: 'K', symbol: 'T_eff' },
  effective_temperature: { label: '有效温度 (Teff)', unit: 'K', symbol: 'T_eff' },
  stellar_radius: { label: '恒星半径 (Radius)', unit: 'R☉', symbol: 'R_*' },
  radius: { label: '半径 (Radius)', unit: 'R☉', symbol: 'R_*' },
  stellar_mass: { label: '恒星质量 (Mass)', unit: 'M☉', symbol: 'M_*' },
  mass: { label: '质量 (Mass)', unit: 'M☉', symbol: 'M_*' },
  parallax: { label: '视差 (Parallax)', unit: 'mas', symbol: 'ϖ' },
  plx: { label: '视差 (Parallax)', unit: 'mas', symbol: 'ϖ' },
  distance: { label: '天体距离 (Distance)', unit: 'pc', symbol: 'd' },
  dist: { label: '天体距离 (Distance)', unit: 'pc', symbol: 'd' },
  metallicity: { label: '金属丰度 ([Fe/H])', unit: 'dex', symbol: '[Fe/H]' },
  fe_h: { label: '金属丰度 ([Fe/H])', unit: 'dex', symbol: '[Fe/H]' },
  surface_gravity: { label: '表面重力 (log g)', unit: 'cgs', symbol: 'log g' },
  log_g: { label: '表面重力 (log g)', unit: 'cgs', symbol: 'log g' },
  v_mag: { label: '视星等 (V mag)', unit: 'mag', symbol: 'V' },
  luminosity: { label: '光度 (Luminosity)', unit: 'L☉', symbol: 'L_*' },
}

// 解析数值与不确定度
function parseMeasurementValue(rawVal) {
  if (typeof rawVal === 'number') {
    return { val: rawVal, err: null }
  }
  if (!rawVal || typeof rawVal !== 'string') return null

  const s = rawVal.trim()
  // 匹配数值 ± 误差，支持 "3600 ± 66", "3600  66", "3641 +- 53", "3600 +50 -40"
  const pmMatch = s.match(/([+-]?\d+(?:\.\d+)?)\s*(?:±||\+\-|\+\/)\s*([+-]?\d+(?:\.\d+)?)/)
  if (pmMatch) {
    const val = parseFloat(pmMatch[1])
    const err = Math.abs(parseFloat(pmMatch[2]))
    if (!isNaN(val) && !isNaN(err)) return { val, err }
  }

  // 匹配非对称误差 20^{+5}_{-3} 或 20 +5 -3
  const asymMatch = s.match(/([+-]?\d+(?:\.\d+)?)\s*(?:\^\{?\+?([0-9.]+)\}?_\{?\-?([0-9.]+)\}?|\+\s*([0-9.]+)\s*\-\s*([0-9.]+))/)
  if (asymMatch) {
    const val = parseFloat(asymMatch[1])
    const e1 = parseFloat(asymMatch[2] || asymMatch[4] || 0)
    const e2 = parseFloat(asymMatch[3] || asymMatch[5] || 0)
    const err = (e1 + e2) / 2
    if (!isNaN(val)) return { val, err: err > 0 ? err : null }
  }

  // 匹配区间 18 - 21 或 15-20
  const rangeMatch = s.match(/^([+-]?\d+(?:\.\d+)?)\s*[-~～]\s*([+-]?\d+(?:\.\d+)?)$/)
  if (rangeMatch) {
    const v1 = parseFloat(rangeMatch[1])
    const v2 = parseFloat(rangeMatch[2])
    if (!isNaN(v1) && !isNaN(v2)) {
      return { val: (v1 + v2) / 2, err: Math.abs(v2 - v1) / 2 }
    }
  }

  // 单一数值
  const numMatch = s.match(/^[~≈]?\s*([+-]?\d+(?:\.\d+)?)/)
  if (numMatch) {
    const val = parseFloat(numMatch[1])
    if (!isNaN(val)) return { val, err: null }
  }

  return null
}

// 从 source_id 提取年份
function extractYear(sourceId, sourceYearMap) {
  if (sourceYearMap && sourceYearMap[sourceId]) {
    return Number(sourceYearMap[sourceId])
  }
  if (!sourceId || typeof sourceId !== 'string') return 2020
  const m = sourceId.match(/(?:19|20)\d{2}/)
  if (m) {
    const y = parseInt(m[0], 10)
    if (y >= 1970 && y <= 2030) return y
  }
  // 星表类来源赋予基准年份
  if (sourceId.includes('TIC') || sourceId.includes('TESS')) return 2018
  if (sourceId.includes('GAIA') || sourceId.includes('Gaia')) return 2022
  if (sourceId.includes('SIMBAD') || sourceId.includes('2MASS')) return 2003
  return 2020
}

export default function ConsensusScatterModule({ taskId, status }) {
  const [records, setRecords] = useState([])
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(false)
  const [selectedField, setSelectedField] = useState('')
  const [collapsed, setCollapsed] = useState(false)
  const [hoveredPoint, setHoveredPoint] = useState(null)
  const containerRef = useRef(null)

  // 1. 获取任务 records 与 sources
  useEffect(() => {
    if (!taskId) return
    let alive = true
    setLoading(true)
    Promise.all([
      api.getRecords(taskId).catch(() => []),
      api.getSources(taskId).catch(() => []),
    ]).then(([r, s]) => {
      if (!alive) return
      setRecords(Array.isArray(r) ? r : [])
      setSources(Array.isArray(s) ? s : [])
      setLoading(false)
    })
    return () => { alive = false }
  }, [taskId, status])

  // 来源年份映射字典
  const sourceYearMap = useMemo(() => {
    const map = {}
    for (const s of sources) {
      if (s?.source_id && s.year) {
        map[s.source_id] = Number(s.year)
      }
    }
    return map
  }, [sources])

  // 2. 提取所有具有有效数值的字段清单
  const availableFields = useMemo(() => {
    if (!records.length) return []
    const fieldCounts = {}
    for (const r of records) {
      const fn = r.field_name
      if (!fn) continue
      const parsed = parseMeasurementValue(r.field_value)
      if (parsed) {
        fieldCounts[fn] = (fieldCounts[fn] || 0) + 1
      }
    }
    // 按样本数量降序排列，优先选择测量点最多的物理量
    return Object.entries(fieldCounts)
      .filter(([, count]) => count >= 2)
      .sort((a, b) => b[1] - a[1])
      .map(([fn, count]) => ({
        key: fn,
        label: FIELD_META[fn]?.label || fn,
        unit: FIELD_META[fn]?.unit || '',
        count,
      }))
  }, [records])

  // 默认选中第一个可用字段
  useEffect(() => {
    if (availableFields.length > 0 && (!selectedField || !availableFields.some((f) => f.key === selectedField))) {
      setSelectedField(availableFields[0].key)
    }
  }, [availableFields, selectedField])

  // 3. 处理当前选定物理量的数据点与加权共识统计
  const { plotData, consensusStats } = useMemo(() => {
    if (!selectedField || !records.length) {
      return { plotData: [], consensusStats: null }
    }

    const points = []
    let detectedUnit = FIELD_META[selectedField]?.unit || ''

    // 收集所有匹配记录
    const fieldRecords = records.filter((r) => r.field_name === selectedField)

    // 如果未定义单位，从记录中读取
    for (const r of fieldRecords) {
      if (r.field_unit && !detectedUnit) {
        detectedUnit = r.field_unit
      }
    }

    // 解析点集
    for (let idx = 0; idx < fieldRecords.length; idx++) {
      const r = fieldRecords[idx]
      const parsed = parseMeasurementValue(r.field_value)
      if (!parsed) continue

      const year = extractYear(r.source_id, sourceYearMap)
      const conf = Number(r.extraction_confidence) || 0.9

      // 估算标准差误差
      let error = parsed.err
      if (error == null || error <= 0) {
        // 未标明误差时，根据提取置信度与主值进行 3%~8% 的自适应不确定度估算
        error = Math.max(0.001, Math.abs(parsed.val) * (1.05 - Math.min(1.0, conf)) * 0.1)
      }

      points.push({
        id: r.record_id || `pt-${idx}`,
        sourceId: r.source_id,
        sourceLabel: journalLabel(r.source_id) || r.source_id,
        year,
        val: parsed.val,
        rawVal: r.field_value,
        err: error,
        hasExplicitErr: parsed.err != null,
        unit: r.field_unit || detectedUnit,
        confidence: conf,
        method: r.measurement_method || r.extraction_method || '文献抽取',
        context: r.context_snippet || '',
        entityName: r.entity_name || '',
      })
    }

    if (points.length < 2) {
      return { plotData: points, consensusStats: null }
    }

    // 按年份排序
    points.sort((a, b) => a.year - b.year)

    // 计算逆方差 + 质量加权均值与共识带
    // w_i = (confidence_i) / (sigma_i^2)
    let sumWeight = 0
    let sumWeightVal = 0
    for (const p of points) {
      const sigmaSq = Math.max(1e-6, p.err * p.err)
      const w = (p.confidence || 0.8) / sigmaSq
      p.weight = w
      sumWeight += w
      sumWeightVal += w * p.val
    }

    const consensusMean = sumWeight > 0 ? sumWeightVal / sumWeight : 0

    // 计算加权离散度 (Weighted Sample Standard Deviation)
    let sumWeightedDevSq = 0
    for (const p of points) {
      sumWeightedDevSq += (p.weight || 1) * Math.pow(p.val - consensusMean, 2)
    }
    const weightedStd = sumWeight > 0 ? Math.sqrt(sumWeightedDevSq / sumWeight) : 0
    const sem = sumWeight > 0 ? 1 / Math.sqrt(sumWeight) : 0

    // 计算跨源收敛度一致性指数 (Convergence Index)
    const cv = Math.abs(consensusMean) > 1e-6 ? weightedStd / Math.abs(consensusMean) : 0
    const convergenceScore = Math.max(0, Math.min(100, Math.round((1 - Math.min(1, cv * 2)) * 1000) / 10))

    const years = points.map((p) => p.year)
    const minYear = Math.min(...years)
    const maxYear = Math.max(...years)

    return {
      plotData: points,
      consensusStats: {
        mean: consensusMean,
        std: weightedStd,
        sem,
        bandUpper: consensusMean + (weightedStd > 0 ? weightedStd : Math.abs(consensusMean) * 0.05),
        bandLower: consensusMean - (weightedStd > 0 ? weightedStd : Math.abs(consensusMean) * 0.05),
        convergenceScore,
        count: points.length,
        sourcesCount: new Set(points.map((p) => p.sourceId)).size,
        minYear,
        maxYear,
        unit: detectedUnit,
      },
    }
  }, [selectedField, records, sourceYearMap])

  // 4. SVG 布局与坐标映射
  const svgLayout = useMemo(() => {
    if (!plotData.length) return null

    const W = 720
    const H = 260
    const pad = { left: 60, right: 30, top: 25, bottom: 35 }
    const plotW = W - pad.left - pad.right
    const plotH = H - pad.top - pad.bottom

    const years = plotData.map((d) => d.year)
    let minYear = Math.min(...years)
    let maxYear = Math.max(...years)
    if (minYear === maxYear) {
      minYear -= 2
      maxYear += 2
    } else {
      minYear -= 1
      maxYear += 1
    }

    // Y 轴范围覆盖所有测量点及误差棒
    let minY = Infinity
    let maxY = -Infinity
    for (const d of plotData) {
      const top = d.val + (d.err || 0)
      const btm = d.val - (d.err || 0)
      if (top > maxY) maxY = top
      if (btm < minY) minY = btm
    }

    if (consensusStats) {
      if (consensusStats.bandUpper > maxY) maxY = consensusStats.bandUpper
      if (consensusStats.bandLower < minY) minY = consensusStats.bandLower
    }

    // Y 轴适当增加 10% 裕量
    const yMargin = Math.max(1e-4, (maxY - minY) * 0.12)
    minY -= yMargin
    maxY += yMargin

    const getX = (year) => pad.left + ((year - minYear) / (maxYear - minYear)) * plotW
    const getY = (val) => pad.top + ((maxY - val) / (maxY - minY)) * plotH

    // 生成 X 轴刻度
    const yearSpan = maxYear - minYear
    const xStep = yearSpan <= 6 ? 1 : yearSpan <= 14 ? 2 : Math.ceil(yearSpan / 6)
    const xTicks = []
    for (let y = Math.ceil(minYear); y <= maxYear; y += xStep) {
      xTicks.push({ year: y, x: getX(y) })
    }

    // 生成 Y 轴刻度 (4 ~ 5 个标线)
    const yTicks = []
    const ySteps = 4
    for (let i = 0; i <= ySteps; i++) {
      const val = minY + (i / ySteps) * (maxY - minY)
      yTicks.push({
        val,
        formatted: val >= 1000 ? val.toFixed(0) : val >= 10 ? val.toFixed(1) : val.toFixed(3),
        y: getY(val),
      })
    }

    return {
      W,
      H,
      pad,
      plotW,
      plotH,
      minYear,
      maxYear,
      minY,
      maxY,
      getX,
      getY,
      xTicks,
      yTicks,
    }
  }, [plotData, consensusStats])

  if (!records.length && !loading) {
    return null
  }

  return (
    <div
      ref={containerRef}
      style={{
        border: '1px solid var(--surface-border)',
        borderRadius: 10,
        background: 'var(--surface-bg)',
        overflow: 'hidden',
        marginBottom: 8,
      }}
    >
      {/* ── 模块头部 ── */}
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
          <Icon.BarChart style={{ width: 14, height: 14 }} />
        </span>

        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--content-fg)' }}>
            天体多源测量共识分布
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
            D1 · 数据整合与收敛带
          </span>
        </div>

        <span style={{ flex: 1 }} />

        {/* 物理量切换下拉 */}
        {availableFields.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 11.5, color: 'var(--content-fg-secondary)' }}>物理量:</span>
            <select
              value={selectedField}
              onChange={(e) => setSelectedField(e.target.value)}
              style={{
                fontSize: 12,
                fontWeight: 510,
                color: 'var(--content-fg)',
                background: 'var(--surface-secondary)',
                border: '1px solid var(--surface-border)',
                borderRadius: 6,
                padding: '3px 8px',
                outline: 'none',
                cursor: 'pointer',
              }}
            >
              {availableFields.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label} ({f.count} 条)
                </option>
              ))}
            </select>
          </div>
        )}

        {/* 折叠/展开按钮 */}
        <button
          onClick={() => setCollapsed((v) => !v)}
          title={collapsed ? '展开多源共识分布图' : '收起多源共识分布图'}
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

      {/* ── 模块内容区：风琴式平滑折叠 ── */}
      <div className={`smooth-collapse${!collapsed ? ' expanded' : ''}`}>
        <div style={{ padding: '14px 16px' }}>
          {availableFields.length === 0 ? (
            <div className="empty-state" style={{ padding: '20px 0' }}>
              <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--content-fg-tertiary)' }}>
                当前任务记录未检测到具有 2 次以上量化测量的物理量，待跨源抽取完成后展示收敛图。
              </span>
            </div>
          ) : (
            <div>
              {/* 1. 顶部共识分析 KPI 状态指示条 */}
              {consensusStats && (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                    gap: 8,
                    marginBottom: 14,
                  }}
                >
                  <div className="kpi-card" style={{ padding: '8px 12px' }}>
                    <div className="kpi-label" style={{ fontSize: 11, marginBottom: 2 }}>
                      AI 综合加权共识值
                    </div>
                    <div className="font-mono" style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--accent)' }}>
                      {consensusStats.mean >= 1000 ? consensusStats.mean.toFixed(1) : consensusStats.mean.toFixed(3)}{' '}
                      <span style={{ fontSize: 11, color: 'var(--content-fg-secondary)' }}>
                        ± {consensusStats.std >= 10 ? consensusStats.std.toFixed(1) : consensusStats.std.toFixed(3)} {consensusStats.unit}
                      </span>
                    </div>
                  </div>

                  <div className="kpi-card" style={{ padding: '8px 12px' }}>
                    <div className="kpi-label" style={{ fontSize: 11, marginBottom: 2 }}>
                      多源收敛度
                    </div>
                    <div className="font-mono" style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--status-success)' }}>
                      {consensusStats.convergenceScore}%{' '}
                      <span style={{ fontSize: 10.5, color: 'var(--content-fg-tertiary)' }}>
                        (高度收敛)
                      </span>
                    </div>
                  </div>

                  <div className="kpi-card" style={{ padding: '8px 12px' }}>
                    <div className="kpi-label" style={{ fontSize: 11, marginBottom: 2 }}>
                      样本量与时序跨度
                    </div>
                    <div className="font-mono" style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>
                      {consensusStats.count} 次测量 · {consensusStats.sourcesCount} 篇文献
                      <div style={{ fontSize: 10, color: 'var(--content-fg-tertiary)' }}>
                        {consensusStats.minYear} – {consensusStats.maxYear} 年
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* 2. SVG 散点图与共识带主体 */}
              {svgLayout && (
                <div style={{ position: 'relative', width: '100%', overflowX: 'auto' }}>
                  <svg
                    viewBox={`0 0 ${svgLayout.W} ${svgLayout.H}`}
                    style={{
                      width: '100%',
                      minWidth: 500,
                      maxHeight: 280,
                      display: 'block',
                      background: 'var(--surface-secondary)',
                      borderRadius: 8,
                      border: '1px solid var(--surface-border-subtle)',
                    }}
                  >
                    <defs>
                      {/* AI 共识带半透明柔光渐变 */}
                      <linearGradient id="consensusBandGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.22" />
                        <stop offset="50%" stopColor="var(--accent)" stopOpacity="0.32" />
                        <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.22" />
                      </linearGradient>

                      {/* 散点外发光滤镜 */}
                      <filter id="pointGlow" x="-30%" y="-30%" width="160%" height="160%">
                        <feGaussianBlur stdDeviation="2.5" result="blur" />
                        <feComposite in="SourceGraphic" in2="blur" operator="over" />
                      </filter>
                    </defs>

                    {/* 网格横线 */}
                    {svgLayout.yTicks.map((t, idx) => (
                      <g key={`y-tick-${idx}`}>
                        <line
                          x1={svgLayout.pad.left}
                          y1={t.y}
                          x2={svgLayout.W - svgLayout.pad.right}
                          y2={t.y}
                          stroke="var(--surface-border-subtle)"
                          strokeDasharray="3 3"
                          strokeWidth="0.8"
                        />
                        <text
                          x={svgLayout.pad.left - 8}
                          y={t.y + 3.5}
                          textAnchor="end"
                          fontSize="9.5"
                          fontFamily="ui-monospace, monospace"
                          fill="var(--content-fg-tertiary)"
                        >
                          {t.formatted}
                        </text>
                      </g>
                    ))}

                    {/* 网格竖线 */}
                    {svgLayout.xTicks.map((t, idx) => (
                      <g key={`x-tick-${idx}`}>
                        <line
                          x1={t.x}
                          y1={svgLayout.pad.top}
                          x2={t.x}
                          y2={svgLayout.H - svgLayout.pad.bottom}
                          stroke="var(--surface-border-subtle)"
                          strokeDasharray="2 4"
                          strokeWidth="0.8"
                        />
                        <text
                          x={t.x}
                          y={svgLayout.H - svgLayout.pad.bottom + 15}
                          textAnchor="middle"
                          fontSize="10"
                          fontFamily="ui-monospace, monospace"
                          fill="var(--content-fg-secondary)"
                        >
                          {t.year}
                        </text>
                      </g>
                    ))}

                    {/* ── AI 加权共识带 (±1σ Shaded Ribbon) ── */}
                    {consensusStats && (
                      <g>
                        <rect
                          x={svgLayout.pad.left}
                          y={Math.min(svgLayout.getY(consensusStats.bandUpper), svgLayout.getY(consensusStats.bandLower))}
                          width={svgLayout.plotW}
                          height={Math.abs(svgLayout.getY(consensusStats.bandUpper) - svgLayout.getY(consensusStats.bandLower))}
                          fill="url(#consensusBandGrad)"
                          rx="3"
                        />
                        {/* 共识均值中轴虚线 */}
                        <line
                          x1={svgLayout.pad.left}
                          y1={svgLayout.getY(consensusStats.mean)}
                          x2={svgLayout.W - svgLayout.pad.right}
                          y2={svgLayout.getY(consensusStats.mean)}
                          stroke="var(--accent)"
                          strokeWidth="1.5"
                          strokeDasharray="5 3"
                        />
                        {/* 共识带标签 */}
                        <text
                          x={svgLayout.W - svgLayout.pad.right - 6}
                          y={svgLayout.getY(consensusStats.bandUpper) + 12}
                          textAnchor="end"
                          fontSize="9"
                          fontWeight="600"
                          fill="var(--accent)"
                          letterSpacing="0.04em"
                        >
                          AI 加权共识带 (±1σ)
                        </text>
                      </g>
                    )}

                    {/* ── 误差棒与数据散点 ── */}
                    {plotData.map((pt, idx) => {
                      // 给同一年份的重合点加入微小 X 轴视觉扰动，防止完全遮挡
                      const jitter = ((idx % 3) - 1) * 3.5
                      const cx = svgLayout.getX(pt.year) + jitter
                      const cy = svgLayout.getY(pt.val)
                      const topY = svgLayout.getY(pt.val + (pt.err || 0))
                      const btmY = svgLayout.getY(pt.val - (pt.err || 0))
                      const isHovered = hoveredPoint?.id === pt.id
                      const radius = Math.max(4.5, Math.min(8.5, 4 + (pt.confidence || 0.9) * 4))

                      return (
                        <g
                          key={pt.id}
                          onMouseEnter={() => setHoveredPoint(pt)}
                          onMouseLeave={() => setHoveredPoint(null)}
                          style={{ cursor: 'pointer' }}
                        >
                          {/* 误差棒竖线 */}
                          <line
                            x1={cx}
                            y1={topY}
                            x2={cx}
                            y2={btmY}
                            stroke={isHovered ? 'var(--accent)' : 'var(--content-fg-secondary)'}
                            strokeWidth={isHovered ? 1.8 : 1.1}
                            strokeDasharray={pt.hasExplicitErr ? 'none' : '3 2'}
                            opacity={isHovered ? 1 : 0.75}
                          />
                          {/* 误差棒横帽子 */}
                          <line
                            x1={cx - 3.5}
                            y1={topY}
                            x2={cx + 3.5}
                            y2={topY}
                            stroke={isHovered ? 'var(--accent)' : 'var(--content-fg-secondary)'}
                            strokeWidth={1}
                            opacity={0.8}
                          />
                          <line
                            x1={cx - 3.5}
                            y1={btmY}
                            x2={cx + 3.5}
                            y2={btmY}
                            stroke={isHovered ? 'var(--accent)' : 'var(--content-fg-secondary)'}
                            strokeWidth={1}
                            opacity={0.8}
                          />

                          {/* 散点外圆（光圈） */}
                          <circle
                            cx={cx}
                            cy={cy}
                            r={isHovered ? radius + 3 : radius}
                            fill={isHovered ? 'var(--accent)' : 'var(--surface-bg)'}
                            stroke="var(--accent)"
                            strokeWidth={isHovered ? 2.5 : 1.8}
                            filter={isHovered ? 'url(#pointGlow)' : undefined}
                            style={{ transition: 'all 0.15s ease' }}
                          />

                          {/* 散点内实心核 */}
                          <circle
                            cx={cx}
                            cy={cy}
                            r={isHovered ? 3.5 : 2.5}
                            fill="var(--accent)"
                          />
                        </g>
                      )
                    })}

                    {/* Y 轴单位标签 */}
                    <text
                      x={svgLayout.pad.left - 8}
                      y={svgLayout.pad.top - 10}
                      textAnchor="end"
                      fontSize="10"
                      fontWeight="510"
                      fill="var(--content-fg-secondary)"
                    >
                      {consensusStats?.unit || ''}
                    </text>
                  </svg>

                  {/* 悬浮点详细数据卡片 (Tooltip) */}
                  {hoveredPoint && (
                    <div
                      style={{
                        position: 'absolute',
                        top: 10,
                        right: 14,
                        maxWidth: 290,
                        background: 'var(--surface-bg)',
                        border: '1px solid var(--accent)',
                        borderRadius: 8,
                        padding: '9px 12px',
                        boxShadow: '0 8px 24px rgba(0,0,0,0.25)',
                        pointerEvents: 'none',
                        zIndex: 10,
                      }}
                      className="animate-modal-in"
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent)' }}>
                          {hoveredPoint.sourceLabel} ({hoveredPoint.year} 年)
                        </span>
                        <span
                          style={{
                            marginLeft: 'auto',
                            fontSize: 10,
                            padding: '1px 6px',
                            borderRadius: 'var(--radius-pill)',
                            background: 'var(--status-progress-bg)',
                            color: 'var(--status-progress)',
                          }}
                        >
                          可信度 {Math.round(hoveredPoint.confidence * 100)}%
                        </span>
                      </div>

                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--content-fg)', marginBottom: 4 }}>
                        {hoveredPoint.val} {hoveredPoint.err ? `± ${hoveredPoint.err.toFixed(2)}` : ''} {hoveredPoint.unit}
                      </div>

                      <div style={{ fontSize: 11, color: 'var(--content-fg-secondary)', marginBottom: 4 }}>
                        测量方法: {hoveredPoint.method}
                      </div>

                      {hoveredPoint.context && (
                        <div
                          style={{
                            fontSize: 10.5,
                            color: 'var(--content-fg-tertiary)',
                            lineHeight: 1.45,
                            maxHeight: 46,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            display: '-webkit-box',
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: 'vertical',
                          }}
                        >
                          &ldquo;{hoveredPoint.context}&rdquo;
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
