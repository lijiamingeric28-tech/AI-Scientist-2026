import { useEffect, useMemo, useRef, useState } from 'react'
import { measurementSeries, sourceName } from '@/lib/readableData'
import { axisTickLabels, labelLines, measurementAxis, resolveSelection } from '@/lib/chartPresentation'
import { Icon } from '@/components/icons'

export default function MeasurementScatterChart({
  records = [],
  sources = [],
  quality,
  onOpenRecord,
  onOpenRecords,
}) {
  const groups = useMemo(() => measurementSeries(records, quality), [records, quality])
  const [selectedKey, setSelectedKey] = useState('')
  const [pointId, setPointId] = useState(null)
  const [chartWidth, setChartWidth] = useState(720)
  const plotRef = useRef(null)

  const activeKey = resolveSelection(selectedKey, groups.map(item => item.key))
  const currentGroup = groups.find(item => item.key === activeKey) || groups[0] || null

  useEffect(() => {
    if (activeKey !== selectedKey) setSelectedKey(activeKey || '')
  }, [activeKey, selectedKey])

  useEffect(() => {
    if (!plotRef.current) return
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) {
        setChartWidth(Math.max(600, Math.floor(entry.contentRect.width)))
      }
    })
    observer.observe(plotRef.current)
    return () => observer.disconnect()
  }, [Boolean(currentGroup)])

  if (!currentGroup || !groups.length) {
    return (
      <div className="empty-state-notice">
        <p className="hint">本次任务未提供可绘制共轴散点的测量记录</p>
      </div>
    )
  }

  const bySource = Array.from(new Set(currentGroup.valid.map(row => row.record.source_id)))
  const axis = measurementAxis(currentGroup.min, currentGroup.max, chartWidth > 900 ? 6 : 4)
  const tickLabels = axis ? axisTickLabels(axis.ticks) : []
  const labelWidth = Math.min(240, Math.max(180, chartWidth * 0.22))
  const right = chartWidth - 30

  const x = value => {
    if (!axis) return 0
    const scale = Math.max(Math.abs(axis.lo), Math.abs(axis.hi), 1e-300)
    const span = axis.hi / scale - axis.lo / scale || 1
    return labelWidth + ((value / scale - axis.lo / scale) / span) * (right - labelWidth)
  }

  const rowHeight = 44
  const height = 24 + bySource.length * rowHeight
  const activeRow = currentGroup.valid.find(row => row.record.record_id === pointId)

  const getSource = id => sources.find(s => s.source_id === id)

  return (
    <div className="measurement-scatter-chart-container" ref={plotRef}>
      <header className="scatter-chart-header">
        <div className="scatter-title-group">
          <div className="scatter-title-icon-badge">
            <Icon.BarChart width="18" height="18" />
          </div>
          <div>
            <h4 className="scatter-chart-title">多源多波段共轴测量离散与一致性分布</h4>
            <p className="scatter-chart-subtitle">
              横坐标共享标度轴，纵向按出版物来源对齐；实心圆点标定测量主值，横线展示文献给定误差区间（|—●—|）
            </p>
          </div>
        </div>

        {/* Group Selector Dropdown */}
        <div className="scatter-controls">
          <label htmlFor="scatter-group-select" className="scatter-select-label">
            选择观测性质：
          </label>
          <select
            id="scatter-group-select"
            className="scatter-group-select"
            value={currentGroup.key}
            onChange={e => {
              setSelectedKey(e.target.value)
              setPointId(null)
              if (plotRef.current) plotRef.current.scrollTop = 0
            }}
          >
            {groups.map(g => (
              <option key={g.key} value={g.key}>
                {g.entity} · {g.field} ({g.unit || '无量纲单位'}) · {g.rows.length} 条
              </option>
            ))}
          </select>
        </div>
      </header>

      {/* Property Summary Strip */}
      <div className="scatter-summary-strip">
        <div className="summary-chip">
          <span className="chip-label">当前观测性质</span>
          <strong className="chip-value">{currentGroup.field}</strong>
        </div>
        <div className="summary-chip">
          <span className="chip-label">测量记录总数</span>
          <strong className="chip-value">{currentGroup.rows.length} 条</strong>
        </div>
        <div className="summary-chip">
          <span className="chip-label">独立贡献文献</span>
          <strong className="chip-value">{bySource.length} 篇</strong>
        </div>
        <div className="summary-chip">
          <span className="chip-label">数值离散跨度</span>
          <strong className="chip-value">
            {currentGroup.min != null && currentGroup.max != null
              ? `${currentGroup.min} ~ ${currentGroup.max} ${currentGroup.unit || ''}`
              : '多值离散'}
          </strong>
        </div>
      </div>

      {/* Plot Canvas */}
      <div className="scatter-plot-scroll-wrapper">
        {currentGroup.valid.length && axis ? (
          <>
            {/* Top X-Axis Scale */}
            <svg
              viewBox={`0 0 ${chartWidth} 48`}
              width={chartWidth}
              height="48"
              className="scatter-x-axis"
              aria-hidden="true"
            >
              <rect width={chartWidth} height="48" fill="var(--surface-secondary, #f8fafc)" rx="6" />
              <text
                x="18"
                y="29"
                fill="var(--content-fg-secondary, #64748b)"
                fontSize="12.5"
                fontWeight="600"
              >
                {currentGroup.unit ? `[${currentGroup.unit}]` : '数值'}
              </text>
              {axis.ticks.map((val, idx) => (
                <g key={val} transform={`translate(${x(val)}, 0)`}>
                  <line y1="36" y2="44" stroke="var(--surface-border, #cbd5e1)" strokeWidth="1.5" />
                  <text
                    y="29"
                    textAnchor="middle"
                    fill="var(--content-fg, #334155)"
                    fontSize="12"
                    fontWeight="500"
                  >
                    {tickLabels[idx]}
                  </text>
                </g>
              ))}
            </svg>

            {/* Main Scatter Rows */}
            <svg
              viewBox={`0 0 ${chartWidth} ${height}`}
              width={chartWidth}
              height={height}
              role="group"
              aria-label={`${currentGroup.field} 多来源共轴测量图`}
              className="scatter-main-svg"
            >
              {/* Vertical Gridlines */}
              {axis.ticks.map(val => (
                <line
                  key={val}
                  x1={x(val)}
                  x2={x(val)}
                  y1="0"
                  y2={height}
                  stroke="var(--surface-border, #e2e8f0)"
                  strokeDasharray="4 4"
                  strokeWidth="1"
                />
              ))}

              {/* Source Rows */}
              {bySource.map((sourceId, index) => {
                const y = 24 + index * rowHeight
                const isRowActive = activeRow?.record?.source_id === sourceId
                const src = getSource(sourceId)
                const titleText = sourceName(src, sourceId)

                return (
                  <g key={sourceId} className="scatter-source-row">
                    {/* Row highlight rect */}
                    <rect
                      x="0"
                      y={y - 18}
                      width={chartWidth}
                      height={rowHeight - 4}
                      rx="4"
                      fill={isRowActive ? 'color-mix(in srgb, var(--accent, #1d4ed8) 10%, transparent)' : 'transparent'}
                      className="source-row-bg"
                    />
                    {/* Source Author/Title label */}
                    <text
                      x={labelWidth - 16}
                      y={y + 4}
                      textAnchor="end"
                      fill={isRowActive ? 'var(--accent, #1d4ed8)' : 'var(--content-fg, #1e293b)'}
                      fontSize="12.5"
                      fontWeight={isRowActive ? '650' : '450'}
                      className="source-row-label"
                    >
                      <title>{titleText}</title>
                      {labelLines(sourceName(src, sourceId, true), Math.floor((labelWidth - 24) / 7.5))[0] || titleText}
                    </text>
                  </g>
                )
              })}

              {/* Measurement Points and Error Bars */}
              {currentGroup.valid.map(({ record, measurement: m }) => {
                const rows = currentGroup.valid.filter(r => r.record.source_id === record.source_id)
                const offsetIdx = rows.findIndex(r => r.record.record_id === record.record_id)
                const y =
                  24 +
                  bySource.indexOf(record.source_id) * rowHeight +
                  (offsetIdx - (rows.length - 1) / 2) * Math.min(8, 22 / rows.length)

                const isPointActive = pointId === record.record_id
                const ptX = x(m.value)
                const hasBounds = m.lower != null && m.upper != null
                const lowerX = hasBounds ? x(m.lower) : ptX
                const upperX = hasBounds ? x(m.upper) : ptX

                return (
                  <g
                    key={record.record_id}
                    role="button"
                    tabIndex={0}
                    aria-label={`查看测量记录 ${record.field_value}`}
                    onMouseEnter={() => setPointId(record.record_id)}
                    onFocus={() => setPointId(record.record_id)}
                    onClick={() => onOpenRecord?.(record)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onOpenRecord?.(record)
                      }
                    }}
                    style={{ cursor: 'pointer' }}
                    className={`scatter-point-item ${isPointActive ? 'active' : ''}`}
                  >
                    {/* Error Bar Line */}
                    {hasBounds && (
                      <g className="error-bar-group">
                        <line
                          x1={lowerX}
                          x2={upperX}
                          y1={y}
                          y2={y}
                          stroke={isPointActive ? 'var(--accent, #1d4ed8)' : 'var(--content-fg-secondary, #64748b)'}
                          strokeWidth={isPointActive ? 2.5 : 1.5}
                        />
                        {/* Lower Cap */}
                        <line
                          x1={lowerX}
                          x2={lowerX}
                          y1={y - 4}
                          y2={y + 4}
                          stroke={isPointActive ? 'var(--accent, #1d4ed8)' : 'var(--content-fg-secondary, #64748b)'}
                          strokeWidth={isPointActive ? 2 : 1.2}
                        />
                        {/* Upper Cap */}
                        <line
                          x1={upperX}
                          x2={upperX}
                          y1={y - 4}
                          y2={y + 4}
                          stroke={isPointActive ? 'var(--accent, #1d4ed8)' : 'var(--content-fg-secondary, #64748b)'}
                          strokeWidth={isPointActive ? 2 : 1.2}
                        />
                      </g>
                    )}

                    {/* Measured Value Circle */}
                    {m.value != null && (
                      <circle
                        cx={ptX}
                        cy={y}
                        r={isPointActive ? 6.5 : 4.5}
                        fill={isPointActive ? 'var(--accent, #1d4ed8)' : 'color-mix(in srgb, var(--accent, #1d4ed8) 85%, #000000)'}
                        stroke="#ffffff"
                        strokeWidth={isPointActive ? 2 : 1.2}
                      />
                    )}
                  </g>
                )
              })}
            </svg>
          </>
        ) : (
          <p className="hint measurement-empty">该组没有可解析的数值区间</p>
        )}
      </div>

      {/* Dynamic Floating / Fixed Tooltip Card */}
      <footer className="scatter-tooltip-footer" role="status" aria-live="polite">
        {activeRow ? (
          <div className="active-point-detail">
            <div className="point-detail-header">
              <span className="point-source-badge">
                {sourceName(getSource(activeRow.record.source_id), activeRow.record.source_id)}
              </span>
              <strong className="point-val-text">
                {activeRow.record.field_value} {currentGroup.unit || ''}
              </strong>
              {activeRow.measurement.lower != null && (
                <span className="point-range-text">
                  (误差区间: {activeRow.measurement.lower} ~ {activeRow.measurement.upper})
                </span>
              )}
            </div>
            <p className="point-hint-action">
              点击散点即可打开该文献原报事实证据链与段落核查 →
            </p>
          </div>
        ) : (
          <div className="point-prompt-text">
            <span>💡 悬停或聚焦散点查看精确测量与误差范围，点击可直接穿透原文事实核对。</span>
          </div>
        )}
      </footer>
    </div>
  )
}
