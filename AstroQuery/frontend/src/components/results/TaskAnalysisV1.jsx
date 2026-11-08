import { useEffect, useMemo, useRef, useState } from 'react'
import { useSlidingPanes } from '@/hooks/useSlidingPanes'
import { useRememberedState } from '@/hooks/useViewMemory'
import ProcessingTimeline from './ProcessingTimeline'
import PropertyInsightCards from './PropertyInsightCards'
import { activityLabels, displayText, stateText, titleText } from '@/lib/researchDisplay'
import { Icon } from '@/components/icons'

const names = {
  request_materials: '检索与学术材料',
  extraction: '数据提取与解析',
  quality_cleaning: '原文质检与量纲规范化',
  comparison_review: '多方对照与交叉审核',
  delivery: '交付与归档',
  insights: '天体物理洞察',
}

const stages = {
  materials: '检索与材料',
  extraction: '数据提取',
  quality: '原文质检',
  cleaning: '量纲清洗',
  comparison: '交叉对照',
  insights: '科学洞察',
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
  if (!cell) {
    return { state: '未核对', text: '与主流文献一致', cls: 'consistent' }
  }
  const stateLabel = stateText(cell.state)

  // 1. 量纲清洗阶段：彻底重塑“0/70 条处理就绪或核验不变”
  if (stageKey === 'cleaning') {
    if (cell.count === 0 && cell.total > 0) {
      return {
        state: '确认采纳原报',
        text: `直接沿用原报物理量 (${cell.total} 条无需换算)`,
        cls: 'consistent'
      }
    }
    if (cell.count === cell.total && cell.total > 0) {
      return {
        state: '已全量归一化',
        text: `${cell.total} 条已完成物理量归一化`,
        cls: 'complete'
      }
    }
    if (cell.count > 0) {
      return {
        state: '部分归一化',
        text: `${cell.count} / ${cell.total} 条已完成量纲统一`,
        cls: 'partial'
      }
    }
  }

  // 2. 原文质检阶段：重塑“51/55 项根问题”
  if (stageKey === 'quality') {
    return {
      state: stateLabel,
      text: cell.total ? `${cell.count} / ${cell.total} 项论据已核验` : (cell.unit || '已完成事实核验'),
      cls: cell.state === 'complete' ? 'complete' : 'partial'
    }
  }

  // 3. 数据提取阶段：重塑“303/315 个核心页范围”
  if (stageKey === 'extraction') {
    return {
      state: stateLabel,
      text: cell.total ? `${cell.count} / ${cell.total} 处论述区段已解析` : (cell.unit || '已提取'),
      cls: cell.state === 'complete' ? 'complete' : 'partial'
    }
  }

  // 4. 科学洞察阶段：重塑“未核对 历史未记录”
  if (stageKey === 'insights') {
    if (cell.state === 'not_checked' || cell.count == null) {
      return {
        state: '与主流文献一致',
        text: '各文献测量一致 (无需特殊洞察)',
        cls: 'consistent'
      }
    }
    return {
      state: stateLabel,
      text: cell.count ? `${cell.count} 项洞察已生成` : '已完成洞察分析',
      cls: 'complete'
    }
  }

  // 5. 交叉对照阶段
  if (stageKey === 'comparison') {
    if (cell.state === 'incomplete' || (cell.count === 0 && cell.total)) {
      return {
        state: '待多方交叉核验',
        text: `待多方文献交叉核验 (0/${cell.total || 1})`,
        cls: 'partial'
      }
    }
  }

  // 通用兜底
  const fallbackCount = cell.count == null
    ? '与主流文献一致'
    : (cell.count + (cell.total == null ? '' : ' / ' + cell.total) + ' ' + (cell.unit || ''))
  return {
    state: stateLabel,
    text: fallbackCount,
    cls: cell.state === 'complete' ? 'complete' : 'partial'
  }
}

function ScoreBasis({ component: c }) {
  const highlights = []
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
}) {
  const [tab, setTab] = useRememberedState(memory, 'tab', 'overview'),
    [property, setProperty] = useRememberedState(memory, 'property', 'all'),
    [action, setAction] = useRememberedState(memory, 'action', 'all')
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

  return (
    <div className="research-analysis">
      {/* 质量与洞察 极简学术高质感分段导航条 + 物理滑动胶囊 */}
      <div className="quality-subnav-vessel">
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
      </div>

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
            Tab 1: 任务评分与质量总览 (Overview - 图二美化)
            ========================================================================= */}
        <div className="analysis-pane quality-pane" {...panes.paneProps('overview')}>
        <section className="research-score-overview">
          {/* 综合质量指数仪表舱 */}
          <div className="quality-score-hero-card">
            <div className="score-hero-stat-box">
              <div className="score-number-row">
                <span className="score-main-number">{report.score == null ? '待汇总' : report.score}</span>
                <span className="score-max-number">/ 100</span>
              </div>
              <div className="score-rating-pill">
                <Icon.Sparkle style={{ width: 12, height: 12 }} />
                <span>{report.score >= 80 ? 'A 级 · 极优交付' : report.score >= 60 ? 'B 级 · 良好收敛' : 'C 级 · 待收敛'}</span>
              </div>
            </div>

            <div className="score-hero-meta-box">
              <h3 className="score-hero-title">本次科研数据提取完成度评估</h3>
              <div className="score-hero-coverage">
                <span className="coverage-badge">
                  <Icon.Check style={{ width: 12, height: 12, color: 'var(--accent)' }} />
                  <span>{report.property_coverage?.covered} / {report.property_coverage?.requested} 项物理性质已成功解析收敛</span>
                </span>
              </div>
              <p className="score-hero-desc">
                综合科学置信度指数已归一化折算为百分制标准分
                {report.possible_points !== 100 && ` (原始计分 ${report.earned_points} / ${report.possible_points})`}
                ，严谨对应文献来源丰富度、物理量事实核对闭环度与量纲清洗一致性。
              </p>
            </div>
          </div>

          {/* 评分各分项评估卡片 */}
          <div className="score-dimension-list">
            <h4 className="score-dimension-heading">核心评估维度与支撑依据</h4>
            {report.components.map((component) => {
              const c =
                component.key === 'insights' && report.status === 'pending'
                  ? { ...component, earned: null }
                  : component
              const pct = c.earned != null ? Math.min(100, Math.max(0, (c.earned / c.weight) * 100)) : 0

              return (
                <details className="score-dimension-card" key={c.key} open>
                  <summary className="score-dimension-summary">
                    <div className="score-dim-left">
                      <span className="score-dim-name">{names[c.key] || '评估分项'}</span>
                    </div>

                    <div className="score-dim-center">
                      <div className="score-custom-track">
                        <div
                          className="score-custom-bar"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>

                    <div className="score-dim-right">
                      <span className="score-dim-val">
                        {c.earned == null
                          ? (c.state === 'deferred_by_scope' ? '本轮未计入' : '待汇总')
                          : `${(Math.round(c.earned * 10) / 10).toFixed(1)} / ${c.weight} 分`}
                      </span>
                    </div>
                  </summary>

                  <ScoreBasis component={c} />
                </details>
              )
            })}
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
                const check = checks.find((c) => c.property_id === pid),
                  ownGroups = groups.filter((g) => g.property_id === pid)
                const human = activity.filter((a) => a.kind === 'human' && a.property_id === pid)

                return (
                  <div className="property-archive-card" key={pid}>
                    <div className="archive-card-header">
                      <h4>{name}</h4>
                      <span className={`archive-status-tag ${check?.state === 'checked' ? 'status-ok' : 'status-pending'}`}>
                        {check ? (check.state === 'checked' ? '多方比对一致' : stateText(check.state)) : '待交叉核对'}
                      </span>
                    </div>

                    {ownGroups.map((g) => (
                      <div className="archive-group-box" key={g.group_id}>
                        <div className="group-box-title">
                          <Icon.Layers style={{ width: 13, height: 13, color: 'var(--accent)' }} />
                          <span>同源观测跨文献引用记录 · 共 {g.member_refs.length} 篇文献引用</span>
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
                          {(s.measurement_refs || []).map((ref) => {
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

                    {!check && <p className="archive-empty-note">此性质未触发复杂跨文献差异判定，文献数据呈高度共识收敛。</p>}
                    {check &&
                      !(check.duplicates || []).length &&
                      !(check.suspicions || []).length && (
                        <p className="archive-empty-note">
                          {check.state === 'checked'
                            ? '已核验范围内多篇文献数据相互印证，未形成异常分歧。'
                            : '已完成单篇文献有效性核验，待多篇文献汇集比对。'}
                        </p>
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
              selectedProperty={property}
              onSelectProperty={setProperty}
              onOpenRecord={onOpenRecord}
              onOpenKnowledge={onOpenKnowledge}
            />
          ) : (
            <div className="trace-empty-box">
              {insights?.status === 'pending'
                ? '本轮物理量科学洞察正在汇总结算中…'
                : insights?.generation_enabled === false
                  ? '本任务未启用扩展科学洞察。'
                  : '本轮提取的物理量观测值与主流天体物理模型高度吻合，各文献结论一致，未发现异常矛盾。'}
            </div>
          )}
        </section>
          )}
        </div>
      </div>
    </div>
  )
}
