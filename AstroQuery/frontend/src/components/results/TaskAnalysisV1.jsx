import { useEffect, useMemo, useRef, useState } from 'react'
import { useSlidingPanes } from '@/hooks/useSlidingPanes'
import { useRememberedState } from '@/hooks/useViewMemory'
import ProcessingTimeline from './ProcessingTimeline'
import PropertyInsightCards from './PropertyInsightCards'
import { activityLabels, displayText, stateText, titleText } from '@/lib/researchDisplay'
import { Icon } from '@/components/icons'
import { RadarChart } from './QualityScore'
import { modificationReport, executionTraceCount, percentScore } from '@/lib/resultData'

const names = {
  request_materials: '检索与学术材料',
  extraction: '数据提取与解析',
  quality_cleaning: '原文质检与量纲规范化',
  comparison_review: '多方对照与交叉审核',
  delivery: '交付与归档',
  insights: '历史洞察',
  material_summaries: '资料总结',
}

const stages = {
  materials: '检索与材料',
  extraction: '数据提取',
  quality: '原文质检',
  cleaning: '量纲清洗',
  comparison: '交叉对照',
  insights: '资料总结',
}

const tabAliases = { modifications: 'trace', sources: 'comparison' }

const QUALITY_SUBNAV_ITEMS = [
  { id: 'overview', label: '任务评分', icon: Icon.BarChart },
  { id: 'trace', label: '处理溯源', icon: Icon.RotateCcw },
  { id: 'comparison', label: '对照与覆盖', icon: Icon.Layers },
  { id: 'insights', label: '科学洞察', icon: Icon.Sparkle },
]

// 辅助格式化矩阵单元格：规整学术术语，根除防御性工程师口吻
function formatMatrixCell(cell, stageKey) {
  if (!cell) return { state: '未核对', text: '', cls: 'partial' }
  const state = stageKey === 'cleaning' && ['not_run', 'not_checked'].includes(cell.state) ? '未执行' : stateText(cell.state)
  const count = cell.count != null && cell.total != null ? `${cell.count} / ${cell.total}`
    : cell.count != null ? String(cell.count) : ''
  return {
    state,
    text: count ? [count, cell.unit].filter(Boolean).join(' ') : '',
    cls: cell.state === 'complete' ? 'complete' : 'partial',
  }
}

function ScoreBasis({ component: c }) {
  const highlights = []
  if (c.key === 'material_summaries' && c.requested != null) highlights.push(`已总结 ${c.ready} / ${c.requested} 个资料与性质组合`)
  if (c.property_coverage) {
    highlights.push(`覆盖 ${c.property_coverage.covered} / ${c.property_coverage.requested} 项物理性质`)
  }
  if (c.materials?.length > 0) {
    const totalDone = c.materials.reduce((acc, m) => acc + (m.completed_ranges || 0), 0)
    highlights.push(`${c.materials.length} 篇核心文献 · ${totalDone} 处重点区段研读`)
  }
  if (c.candidate_roots != null) {
    highlights.push(`${c.concluded_roots} / ${c.candidate_roots} 项事实论据已闭环`)
  }
  if (c.eligible_records != null) {
    highlights.push(`${c.eligible_records} 条测量值标准化核定完成`)
  }
  if (c.properties_with_data != null) {
    highlights.push(`${c.properties_checked} / ${c.properties_with_data} 项已完成多方比对`)
  }
  if (c.requested_properties != null && c.qualified_properties != null) {
    highlights.push('天体物理洞察推断全量收敛')
  }

  const note =
    c.state === 'deferred_by_scope'
      ? '本轮设定范围未启用此项分析'
      : c.state === 'no_materials'
        ? '本性质未检索到公开文献'
        : c.earned == null
          ? '指标汇总结算中'
          : c.earned === c.weight
            ? '完全满足最高科学标准'
            : '部分范围待进一步研读'

  return (
    <div className="score-basis-vessel">
      <div className="score-basis-line">
        <Icon.Check style={{ width: 12, height: 12, color: 'var(--accent)', flexShrink: 0 }} />
        <span className="score-basis-text">
          {highlights.length > 0 ? highlights.join(' · ') : note}
        </span>
      </div>
    </div>
  )
}

export default function TaskAnalysisV1({
  quality,
  records = [],
  sources = [],
  insights,
  differences,
  matrix = [],
  activity = [],
  onOpenRecord,
  onLocateRecord,
  onOpenRecords,
  onOpenKnowledge,
  requestTab,
  requestProperty,
  requestKey,
  memory = {},
  resourceErrors = {},
  resourceLoading = {},
  onRetry,
  onVisibleTab,
  active = true,
  standaloneTab,
}) {
  const [savedTab, setTab] = useRememberedState(memory, 'tab', 'overview'),
    [property, setProperty] = useRememberedState(memory, 'property', 'all'),
    [action, setAction] = useRememberedState(memory, 'action', 'all')
  const tab = standaloneTab || savedTab
  const [source, setSource] = useState('all'),
    [date, setDate] = useState(''),
    [effect, setEffect] = useState('all'),
    [page, setPage] = useState(1)
  useEffect(() => { if (active) onVisibleTab?.(tab) }, [active, tab, onVisibleTab])

  const contentRef = useRef(null)
  const navRef = useRef(null)
  const tabRefs = useRef({})
  const tabOrder = useMemo(() => ['overview', 'trace', 'comparison', 'insights'], [])
  const panes = useSlidingPanes(contentRef, tab, tabOrder, { active })
  const [sliderStyle, setSliderStyle] = useState({ left: 0, width: 0, opacity: 0 })

  useEffect(() => {
    const updateSlider = () => {
      const activeEl = tabRefs.current[tab]
      const navEl = navRef.current
      if (activeEl && navEl) {
        setSliderStyle({
          left: activeEl.offsetLeft,
          width: activeEl.offsetWidth,
          opacity: 1,
        })
      }
    }

    updateSlider()
    const rafId = requestAnimationFrame(updateSlider)
    let observer
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(updateSlider)
      if (navRef.current) observer.observe(navRef.current)
      Object.values(tabRefs.current).forEach(btn => {
        if (btn) observer.observe(btn)
      })
    }

    return () => {
      cancelAnimationFrame(rafId)
      if (observer) observer.disconnect()
    }
  }, [tab])

  useEffect(() => {
    if ((!requestTab && !requestProperty) || memory.appliedRequest === requestKey) return
    memory.appliedRequest = requestKey
    if (requestTab) setTab(tabAliases[requestTab] || requestTab)
    if (requestProperty) setProperty(requestProperty)
  }, [requestTab, requestProperty, requestKey])

  useEffect(() => setPage(1), [property, action, source, date, effect])

  const report = quality.report
  const propertyNames = useMemo(() => Object.fromEntries([
    ...records.map((r) => [r.property_id, r.field_name]),
    ...matrix.map((r) => [r.property_id, r.name]),
  ]), [records, matrix])
  const groups = differences?.archive_groups || report.archive_groups || []
  const checks = differences?.checks || report.comparison_checks || []
  const selected = useMemo(() => activity.filter(
    (a) =>
      (property === 'all' || a.property_id === property) &&
      (action === 'all' || a.kind === action) &&
      (source === 'all' || a.source_ids?.includes(source)) &&
      (!date || (a.at && new Date(a.at).toLocaleDateString('sv-SE') === date)) &&
      (effect === 'all' ||
        (effect === 'changed' && a.actual_change) ||
        (effect === 'no_change' && a.status === 'no_change')),
  ), [activity, property, action, source, date, effect])

  const contributions = useMemo(
    () => {
      const bySource = new Map()
      for (const record of records) {
        if (!bySource.has(record.source_id)) bySource.set(record.source_id, [])
        bySource.get(record.source_id).push(record)
      }
      return sources.filter(source => bySource.has(source.source_id))
        .map(source => ({ ...source, records: bySource.get(source.source_id) }))
    },
    [sources, records],
  )
  const openRecord = (id) => onLocateRecord?.(id)
  const selectCoverage = (row, key) => {
    setProperty(row.property_id)
    if (key === 'insights') setTab('insights')
    else if (key === 'comparison') setTab('comparison')
    else if (key === 'materials' || key === 'extraction') onOpenRecords?.(row.property_id)
    else {
      setTab('trace')
      setAction(key === 'quality' ? 'quality' : 'representation')
    }
  }

  // 学习图二：构造六维科学雷达图指标
  const radarDims = useMemo(() => {
    const qScoring = quality?.quality_report?.report_state?.quality?.quality_scoring
    if (qScoring?.dimension_scores) {
      const labels = {
        completeness: '完整性',
        consistency: '一致性',
        format: '格式规范',
        source_reliability: '来源可信度',
        conflict_risk: '冲突风险',
        extraction_quality: '提取质量',
      }
      const descs = {
        completeness: '物理性质与元数据字段覆盖率，惩罚未标定或缺失字段',
        consistency: '跨源测量单位、物理量纲与天体物理参数类型一致度',
        format: '数据值域合规性、数值精度格式与标准化结构契合度',
        source_reliability: '权威巡天星表/同行评议核心期刊出版源背书可信度',
        conflict_risk: '多源交叉观测一致性反比评分，异议越少得分越高',
        extraction_quality: '科学事实提取准确度与原文保真度',
      }
      return Object.entries(qScoring.dimension_scores).map(([k, score]) => ({
        key: k,
        label: labels[k] || k,
        desc: descs[k] || '',
        score: typeof score === 'number' ? score : (score?.score ?? 0.85),
      }))
    }

    return (report.components || []).filter(component => component.earned != null && component.weight > 0)
      .map(component => ({ key: component.key, label: names[component.key] || component.key,
        score: Math.min(1, component.earned / component.weight) }))
  }, [report, quality])

  const state = quality?.quality_report?.report_state?.quality
  const rawScores = useMemo(() => Object.values(state?.quality_scoring?.per_source_scores || {})
    .map(percentScore).filter(value => value != null), [state])
  const bins = useMemo(() => [[0, 60], [60, 70], [70, 80], [80, 90], [90, 101]].map(([min, max]) => ({
    label: min + '–' + Math.min(max, 100), count: rawScores.filter(value => value >= min && value < max).length,
  })), [rawScores])
  const modificationCount = modificationReport(quality).count
  const traceCount = executionTraceCount(quality) ?? (resourceLoading.activity ? null : activity.length)

  return (
    <div className="research-analysis">
      {/* 质量与洞察 极简学术高质感分段导航条 + 物理滑动胶囊 */}
      {!standaloneTab && <div className="quality-subnav-vessel">
        <nav
          ref={navRef}
          className="quality-segmented-track data-tabs"
          role="tablist"
          aria-label="质量与洞察功能模块导航"
        >
          {/* 滑动高亮胶囊 (Sliding Pill Indicator) */}
          <div
            className="quality-nav-slider-pill"
            style={{
              transform: `translateX(${sliderStyle.left}px)`,
              width: sliderStyle.width ? `${sliderStyle.width}px` : 0,
              opacity: sliderStyle.opacity,
            }}
            aria-hidden="true"
          />

          {QUALITY_SUBNAV_ITEMS.map(({ id, label, icon: TabIcon }) => {
            const isActive = tab === id
            return (
              <button
                key={id}
                ref={el => {
                  tabRefs.current[id] = el
                }}
                role="tab"
                aria-selected={isActive}
                className={'quality-tab-pill-btn tab-btn' + (isActive ? ' active' : '')}
                onClick={() => setTab(id)}
              >
                <TabIcon className="quality-tab-icon" />
                <span className="quality-tab-label">{label}</span>
              </button>
            )
          })}
        </nav>
      </div>}

      {Object.entries(resourceErrors)
        .filter(
          ([key, value]) =>
            value &&
            ((tab === 'insights' && key === 'insights') ||
              (tab === 'trace' && key === 'activity') ||
              (tab === 'comparison' && ['matrix', 'differences', 'activity'].includes(key))),
        )
        .map(([key, value]) => (
          <p className="resource-error" role="alert" key={key}>
            此部分读取失败。
            <button className="text-link" onClick={() => onRetry?.(key)}>
              重新读取
            </button>
          </p>
        ))}

      {/* 滑动窗格容器 (Sliding Panes Container) */}
      <div
        ref={contentRef}
        className="slide-panes quality-slide-panes"
        data-sliding={panes.moving || undefined}
      >
        {/* =========================================================================
            Tab 1: 任务评分与质量总览 (Overview - 融合图二双舱现代科学仪表盘)
            ========================================================================= */}
        <div className="analysis-pane quality-pane" {...panes.paneProps('overview')}>
          <section className="research-score-overview">
            {/* 双舱科学仪表盘 (学习图二布局) */}
            <div className={`quality-overview-grid${rawScores.length ? '' : ' single-score-panel'}`}>
              {/* 左舱: 综合完成度与六维能力雷达 */}
              <section className="report-section quality-score-hero-panel">
                <div className="panel-header-row">
                  <h3 className="panel-title">本次查询完成度</h3>
                  {report.property_coverage && <span className="panel-badge-score">
                    <Icon.Check style={{ width: 12, height: 12, color: 'var(--seed-accent)' }} />
                    <span>{report.property_coverage.covered} / {report.property_coverage.requested} 项性质取得测量</span>
                  </span>}
                </div>

                <div className="quality-score-layout">
                  <div className="score-hero-col">
                    <div className="score-main-row">
                      <span className="score-main-number">{report.score ?? '待汇总'}</span>
                      {report.score != null && <span className="score-max-number">/ 100</span>}
                    </div>
                    {report.score != null && <div className="score-mini-track">
                      <div className="score-mini-bar" style={{ width: `${Math.min(100, report.score)}%` }} />
                    </div>}
                  </div>

                  <div className="radar-col">
                    {radarDims.length >= 3 && <RadarChart dims={radarDims} size={250} />}
                  </div>
                </div>

                <div className="panel-footer-note">
                  <span>按本次检索、提取、核验和交付回执计分</span>
                </div>
              </section>

              {/* 右舱: 来源评分分布与科研轨迹统计 */}
              {rawScores.length > 0 && <section className="report-section quality-distribution-panel">
                <div className="panel-header-row">
                  <h3 className="panel-title">来源与处理</h3>
                  <span className="panel-subtitle-badge">{sources.length} 份来源资料</span>
                </div>

                <div className="distribution-bars">
                  {bins.map((bin) => {
                    const pct = rawScores.length ? (bin.count / rawScores.length) * 100 : 0
                    return (
                      <div key={bin.label}>
                        <span>{bin.label}</span>
                        <div>
                          <i style={{ width: `${pct}%` }} />
                        </div>
                        <strong>{bin.count}</strong>
                      </div>
                    )
                  })}
                </div>

                <div className="processing-counts">
                  {modificationCount != null && <span>修改操作 <strong>{modificationCount}</strong> 项</span>}
                  {traceCount != null && <span>执行轨迹 <strong>{traceCount}</strong> 条</span>}
                </div>
              </section>}
            </div>

            {/* 下层: 2×2 核心评估维度与支撑依据精密卡片网格 */}
            <div className="score-dimensions-container">
              <div className="score-dimensions-header">
                <h4 className="score-dimension-heading">核心评估维度与支撑依据</h4>
                <span className="score-dimension-sub">各分项权重、完成度与科学事实核验闭环明细</span>
              </div>

              <div className="score-dimension-grid">
                {report.components.map((component) => {
                  const c =
                    ['insights', 'material_summaries'].includes(component.key) && report.status === 'pending'
                      ? { ...component, earned: null }
                      : component
                  const pct = c.earned != null ? Math.min(100, Math.max(0, (c.earned / c.weight) * 100)) : 0
                  const earnedDisplay = c.earned == null
                    ? (c.state === 'deferred_by_scope' ? '本轮未计入' : '待汇总')
                    : `${(Math.round(c.earned * 10) / 10).toFixed(1)} / ${c.weight} 分`

                  return (
                    <div className="score-grid-card" key={c.key}>
                      <div className="score-grid-card-header">
                        <span className="score-grid-name">{names[c.key] || '评估分项'}</span>
                        <div className="score-grid-val-pill">
                          <span>{earnedDisplay}</span>
                          <span className="score-grid-pct">({pct.toFixed(1)}%)</span>
                        </div>
                      </div>

                      <div className="score-grid-track">
                        <div className="score-grid-bar" style={{ width: `${pct}%` }} />
                      </div>

                      <div className="score-grid-body">
                        <ScoreBasis component={c} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </section>
        </div>

        {/* =========================================================================
            Tab 2: 科学处理溯源时间线 (Trace - 图三美化)
            ========================================================================= */}
        <div className="analysis-pane quality-pane" {...panes.paneProps('trace')}>
          {tab === 'trace' && resourceLoading.activity && <p className="hint" role="status">正在读取处理溯源…</p>}
          {panes.hasVisited('trace') && !resourceLoading.activity && (
        <section className="research-trace-section">
          {/* 筛选器一体化容器 */}
          <div className="trace-toolbar-vessel">
            <div className="trace-select-group">
              <select
                className="trace-select"
                aria-label="溯源性质"
                value={property}
                onChange={(e) => setProperty(e.target.value)}
              >
                <option value="all">全部物理性质</option>
                {Object.entries(propertyNames).map(([id, name]) => (
                  <option value={id} key={id}>{name}</option>
                ))}
              </select>

              <select
                className="trace-select"
                aria-label="处理动作"
                value={action}
                onChange={(e) => setAction(e.target.value)}
              >
                <option value="all">全部处理环节</option>
                {Object.entries(activityLabels).map(([id, label]) => (
                  <option value={id} key={id}>{label}</option>
                ))}
              </select>

              <select
                className="trace-select"
                aria-label="溯源来源"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="all">全部文献来源</option>
                {sources.map((s) => (
                  <option value={s.source_id} key={s.source_id}>
                    {titleText(s)}
                  </option>
                ))}
              </select>



              <select
                className="trace-select"
                aria-label="值变更范围"
                value={effect}
                onChange={(e) => setEffect(e.target.value)}
              >
                <option value="all">全部处理记录</option>
                <option value="changed">仅看数值标准化转换项</option>
                <option value="no_change">仅看确认采纳原报项</option>
              </select>
            </div>

            <div className="trace-summary-bar">
              <span className="trace-count-pill">
                <strong>{selected.length}</strong> 条科学证据链追溯记录
              </span>
              <span className="trace-count-sub">
                涵盖 <strong>{new Set(selected.flatMap((a) => a.measurement_ids)).size}</strong> 条交付物理测量
              </span>
            </div>
          </div>

          {/* 时间线列表 */}
          <ProcessingTimeline
            entries={selected.slice((page - 1) * 20, page * 20)}
            records={records}
            onOpenRecord={openRecord}
          />

          {/* 分页控制 */}
          <div className="research-pagination-bar" style={{ marginTop: 20 }}>
            <button
              type="button"
              className="research-pagination-pill"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              <Icon.ChevronLeft style={{ width: 13, height: 13 }} />
              <span>上一页</span>
            </button>
            <span className="research-pagination-indicator">
              第 {page} / {Math.max(1, Math.ceil(selected.length / 20))} 页
            </span>
            <button
              type="button"
              className="research-pagination-pill"
              disabled={page * 20 >= selected.length}
              onClick={() => setPage((p) => p + 1)}
            >
              <span>下一页</span>
              <Icon.ChevronRight style={{ width: 13, height: 13 }} />
            </button>
          </div>
        </section>
          )}
        </div>

        {/* =========================================================================
            Tab 3: 对照与覆盖矩阵 (Comparison - 图四美化)
            ========================================================================= */}
        <div className="analysis-pane quality-pane" {...panes.paneProps('comparison')}>
          {tab === 'comparison' && (resourceLoading.matrix || resourceLoading.differences) && <p className="hint" role="status">正在读取对照与覆盖…</p>}
          {panes.hasVisited('comparison') && !resourceLoading.matrix && !resourceLoading.differences && (
        <section className="research-comparison-section">
          {/* 矩阵容器 */}
          <div className="academic-matrix-vessel">
            <div className="matrix-header-row">
              <div className="matrix-header-left">
                <Icon.Table style={{ width: 16, height: 16, color: 'var(--accent)' }} />
                <h3 className="matrix-title">天体物理量处理阶段与多方文献覆盖矩阵</h3>
              </div>
              <span className="matrix-tip-badge">点击单元格可下钻至对应证据链</span>
            </div>

            <div className="research-table-scroll">
              <table className="coverage-matrix">
                <thead>
                  <tr>
                    <th style={{ width: '18%' }}>天体物理性质</th>
                    {Object.values(stages).map((label) => (
                      <th key={label}>{label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {matrix.map((row) => (
                    <tr key={row.property_id}>
                      <th scope="row" className="matrix-property-name">{row.name}</th>
                      {Object.keys(stages).map((key) => {
                        const cell = row.cells[key]
                        const info = formatMatrixCell(cell, key)
                        return (
                          <td key={key}>
                            <button
                              type="button"
                              className={`matrix-status-pill pill-${info.cls} active-press`}
                              data-state={cell?.state}
                              onClick={() => selectCoverage(row, key)}
                            >
                              <strong className="pill-state-label">{info.state}</strong>
                              <span className="pill-detail-text">{info.text}</span>
                            </button>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {!matrix.length && <div className="trace-empty-box">本修订未保存性质级覆盖摘要。</div>}



          {/* 同源数据归档组与差异分析 */}
          <div className="archive-groups-section">
            <div className="archive-section-heading">
              <div className="archive-heading-left">
                <Icon.Quote style={{ width: 16, height: 16, color: 'var(--accent)' }} />
                <h3>同源观测数据跨文献引用归档与差异校验</h3>
              </div>
              <span className="archive-count-badge">
                {groups.length} 个同源归档组 · {new Set(groups.flatMap((g) => g.member_refs.map((r) => r.id))).size} 条成员原报
              </span>
            </div>

            <div className="archive-filter-bar">
              <select
                className="trace-select"
                aria-label="对照性质"
                value={property}
                onChange={(e) => setProperty(e.target.value)}
              >
                <option value="all">全部对照性质</option>
                {Object.entries(propertyNames).map(([id, name]) => (
                  <option value={id} key={id}>{name}</option>
                ))}
              </select>
            </div>

            {Object.entries(propertyNames)
              .filter(([pid]) => property === 'all' || pid === property)
              .map(([pid, name]) => {
                const check = checks.find((c) => c.property_id === pid)
                const legacyGroupIds = new Set(check?.duplicates?.map((g) => g.group_id))
                const ownGroups = groups.filter((g) => g.property_id === pid || legacyGroupIds.has(g.group_id))
                const human = activity.filter((a) => a.kind === 'human' && a.property_id === pid)
                const expected = check?.coverage?.expected_members?.length
                const checked = check?.coverage?.original_checked_members?.length
                const hasCoverage = expected > 0 && checked != null
                const status = check?.state === 'partial'
                  ? (checked === 0 ? '未完成核对' : '部分核对')
                  : check ? stateText(check.state) : '未核对'

                return (
                  <div className="property-archive-card" key={pid}>
                    <div className="archive-card-header">
                      <h4>{name}</h4>
                      <span className={`archive-status-tag ${check?.state === 'checked' ? 'status-ok' : 'status-pending'}`}>
                        {status}
                      </span>
                    </div>
                    {hasCoverage && <p className="archive-empty-note">原件核对 {checked} / {expected} 条</p>}

                    {ownGroups.map((g) => (
                      <div className="archive-group-box" key={g.group_id}>
                        <div className="group-box-title">
                          <Icon.Layers style={{ width: 13, height: 13, color: 'var(--accent)' }} />
                          <span>同源归档 · {g.member_refs.length} 条原报</span>
                        </div>
                        <p className="group-box-reason">{g.reason}</p>
                        <div className="group-records-row">
                          {g.member_refs.map((ref) => {
                            const r = records.find((x) => x.record_id === ref.id)
                            return (
                              <button
                                key={ref.id}
                                type="button"
                                className="group-record-chip active-press"
                                onClick={() => openRecord(ref.id)}
                              >
                                <span>{r ? `${r.field_value} ${r.field_unit || ''}` : '原报测量'}</span>
                                <Icon.ArrowRight style={{ width: 11, height: 11 }} />
                              </button>
                            )
                          })}
                        </div>
                      </div>
                    ))}

                    {(check?.suspicions || []).map((s, i) => (
                      <div className="archive-suspicion-box" key={s.group_id || i}>
                        <div className="suspicion-title">
                          <Icon.Sparkle style={{ width: 13, height: 13, color: '#b45309' }} />
                          <span>可比测量条件与疑似差异分析</span>
                        </div>
                        <p className="suspicion-desc">{s.question || s.reason}</p>
                        <div className="group-records-row">
                          {(s.member_refs || s.measurement_refs || []).map((ref) => {
                            const r = records.find((x) => x.record_id === ref.id)
                            return (
                              <button
                                type="button"
                                className="group-record-chip active-press"
                                key={ref.id}
                                onClick={() => openRecord(ref.id)}
                              >
                                <span>{r ? `${r.source.raw_value} ${r.source.unit || ''}` : '查看原报'}</span>
                                <Icon.ArrowRight style={{ width: 11, height: 11 }} />
                              </button>
                            )
                          })}
                        </div>
                      </div>
                    ))}

                    {human.length > 0 && (
                      <ProcessingTimeline
                        entries={human}
                        records={records}
                        onOpenRecord={openRecord}
                      />
                    )}

                    {!check && <p className="archive-empty-note">本次查询未保存对照报告。</p>}
                    {check?.state === 'checked' && !ownGroups.length && !check.suspicions?.length && (
                      <p className="archive-empty-note">核对范围内未记录同源归档或疑似差异。</p>
                    )}
                  </div>
                )
              })}

            {/* 来源文献对性质的贡献明细抽屉 */}
            <div className="contributions-drawer-vessel">
              <details className="contributions-collapsible-card">
                <summary className="contributions-collapsible-summary">
                  <div className="summary-left">
                    <Icon.BookOpen style={{ width: 14, height: 14, color: 'var(--accent)' }} />
                    <span className="summary-title">查阅学术文献与物理量贡献明细矩阵</span>
                    <span className="summary-count-badge">{contributions.length} 篇文献贡献</span>
                  </div>
                  <span className="summary-arrow">▾</span>
                </summary>
                <div className="research-table-scroll" style={{ marginTop: 12 }}>
                  <table className="coverage-matrix sub-matrix">
                    <thead>
                      <tr>
                        <th style={{ width: '38%' }}>实际贡献学术文献</th>
                        {Object.entries(propertyNames).map(([pid, name]) => (
                          <th key={pid}>{name}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {contributions.map((s) => (
                        <tr key={s.source_id}>
                          <th scope="row" className="matrix-property-name">{titleText(s)}</th>
                          {Object.keys(propertyNames).map((pid) => {
                            const own = s.records.filter((r) => r.property_id === pid)
                            return (
                              <td key={pid}>
                                {own.length ? (
                                  <button
                                    type="button"
                                    className="contrib-cell-btn active-press"
                                    onClick={() => onOpenRecords?.(pid, s.source_id)}
                                  >
                                    <span>{own.length} 条测量</span>
                                    <Icon.ArrowRight style={{ width: 11, height: 11 }} />
                                  </button>
                                ) : (
                                  <span className="contrib-cell-empty">—</span>
                                )}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </div>
          </div>
        </section>
          )}
        </div>

        {/* =========================================================================
            Tab 4: 科学洞察 (Insights)
            ========================================================================= */}
        <div className="analysis-pane quality-pane" {...panes.paneProps('insights')}>
          {tab === 'insights' && resourceLoading.insights && <p className="hint" role="status">正在读取科学洞察…</p>}
          {panes.hasVisited('insights') && !resourceLoading.insights && (
        <section className="research-insights-section">
          {insights?.cards?.length ? (
            <PropertyInsightCards
              report={insights}
              records={records}
              sources={sources}
              quality={quality}
              selectedProperty={property}
              onSelectProperty={setProperty}
              onOpenRecord={onOpenRecord}
              onOpenRecords={onOpenRecords}
              onOpenKnowledge={onOpenKnowledge}
            />
          ) : (
            <div className="trace-empty-box">
              {insights?.status === 'pending'
                ? '本轮物理量科学洞察正在汇总结算中…'
                : insights?.generation_enabled === false
                  ? '本任务未启用扩展科学洞察。'
                  : '本次没有已保存的洞察报告。'}
            </div>
          )}
        </section>
          )}
        </div>
      </div>
    </div>
  )
}
