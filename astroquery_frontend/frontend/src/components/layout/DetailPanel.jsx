import { useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Icon } from '@/components/icons'
import * as api from '@/services/api'
import { STATUS_LABELS, STATUS_COLORS } from '@/components/status'
import { SourcesList, OutputFiles } from '@/components/results/ResultTabs'
import { useMediaQuery } from '@/hooks/useMediaQuery'

/* 右侧详情面板（块 5 定案）：
 * - 宽度 560 默认，可拖拽调宽（400-680）
 * - 分区 Tab：概览 / 质量 / 运行 / 来源 / 图证 / 轨迹 / 洞察 / 下载
 * - <1280px：改覆盖式抽屉（fixed + 遮罩，CSS .detail-panel 媒体查询）
 * - 数据加载期显示骨架屏；各分区空数据有空状态提示
 */

const MIN_W = 400
const MAX_W = 680

/* 图证缩略图：有 image_url 走真实图（契约 D7-3），否则 SVG 占位 */
function FigureThumb({ fig, size = 'thumb' }) {
  const w = size === 'thumb' ? '100%' : 560
  const h = size === 'thumb' ? 120 : 364
  const b = fig.bbox || fig.bbox_2d
  if (fig.image_url) {
    return (
      <div style={{ position: 'relative', width: w, height: h, background: 'var(--surface-secondary)', borderRadius: 6, overflow: 'hidden' }}>
        <img src={fig.image_url} alt={fig.caption || ''} loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
        {b && (
          <div style={{
            position: 'absolute',
            left: `${b[0] * 100}%`, top: `${b[1] * 100}%`,
            width: `${(b[2] - b[0]) * 100}%`, height: `${(b[3] - b[1]) * 100}%`,
            border: '1.5px solid var(--status-error)', borderRadius: 2, pointerEvents: 'none',
          }} />
        )}
      </div>
    )
  }
  return (
    <svg width="100%" height={h} viewBox="0 0 200 130" preserveAspectRatio="none" style={{ display: 'block', borderRadius: 6 }}>
      <defs>
        <linearGradient id={`bg-${fig.id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={`hsl(${fig.hue}, 45%, 88%)`} />
          <stop offset="100%" stopColor={`hsl(${fig.hue}, 55%, 72%)`} />
        </linearGradient>
      </defs>
      <rect width="200" height="130" fill={`url(#bg-${fig.id})`} />
      <polyline points="20,100 60,80 100,88 140,52 180,60" fill="none" stroke="hsl(0,0%,40%)" strokeWidth="1.5" />
      <circle cx="100" cy="88" r="3" fill="hsl(0,0%,25%)" />
      <rect x="30" y="20" width="40" height="25" fill="hsl(0,0%,92%)" opacity="0.7" />
      {b && (
        <>
          <rect x={b[0] * 200} y={b[1] * 130} width={(b[2] - b[0]) * 200} height={(b[3] - b[1]) * 130} fill="none" stroke="var(--status-error)" strokeWidth="1.5" strokeDasharray="4 3" />
          <circle cx={b[0] * 200 + 3} cy={b[1] * 130 + 3} r="3" fill="var(--status-error)" />
        </>
      )}
    </svg>
  )
}

/* 骨架屏（加载期占位） */
function PanelSkeleton() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 58 }} />)}
      </div>
      <div className="skeleton" style={{ height: 14, width: '40%' }} />
      {[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: 34 }} />)}
    </div>
  )
}

/* 分区空状态 */
function TabEmpty({ text }) {
  return (
    <div className="empty-state">
      <Icon.FileText style={{ width: 18, height: 18, opacity: 0.6 }} />
      <span style={{ fontSize: 'var(--fs-sm)' }}>{text}</span>
    </div>
  )
}

/* 洞察报告（契约：final_output.quality_report.output_state.insights，
 * 由 SynthesisAgent 组装：research_domain / field_insights / cross_field_relationships /
 * usage_recommendations / overall_narrative / insufficient_context_fields） */
const REL_LABELS = {
  physical_law: '物理定律', correlation: '相关性', conditional: '条件依赖', no_relationship: '无显著关系',
}
const SOURCE_LABELS = { database: '星表', paper: '论文', supplementary: '补充材料' }
function gradeColor(grade) {
  if (!grade) return 'var(--content-fg-tertiary)'
  const g = String(grade).toLowerCase()
  if (/excellent|good|^a$|^a[-_]|优/.test(g)) return 'var(--status-success)'
  if (/poor|bad|fail|^c$|^d$|^c[-_]|^d[-_]|差/.test(g)) return 'var(--status-error)'
  return 'var(--status-progress)'   // fair / medium / b / 其他 → 中性进度色
}
/* 置信度：0-1 小数 → 百分比；>1 原样 */
const fmtConf = (c) => (typeof c === 'number' && c <= 1 ? `${Math.round(c * 100)}%` : String(c))
function InsightsReport({ insights }) {
  const fi = Array.isArray(insights.field_insights) ? insights.field_insights : []
  const rel = Array.isArray(insights.cross_field_relationships) ? insights.cross_field_relationships : []
  const rec = insights.usage_recommendations || {}
  const lists = [
    ['适用场景', rec.suitable_use_cases],
    ['局限性', rec.limitations],
    ['使用注意事项', rec.recommended_caveats],
    ['低置信度记录', rec.low_confidence_records],
    ['覆盖缺口', rec.coverage_gaps],
  ].filter(([, arr]) => Array.isArray(arr) && arr.length > 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {/* 元信息 */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {insights.research_domain && (
          <span style={{ fontSize: 11, padding: '2px 10px', borderRadius: 'var(--radius-pill)', background: 'var(--surface-secondary)', border: '1px solid var(--surface-border-subtle)', color: 'var(--content-fg-secondary)' }}>
            {insights.research_domain}
          </span>
        )}
        {rec.overall_grade && (
          <span style={{ fontSize: 11, padding: '2px 10px', borderRadius: 'var(--radius-pill)', background: 'var(--surface-secondary)', color: gradeColor(rec.overall_grade), fontWeight: 510 }}>
            可用等级 {rec.overall_grade}
          </span>
        )}
        {insights.generated_at && (
          <span className="hint-dim" style={{ marginLeft: 'auto' }}>
            {new Date(insights.generated_at).toLocaleString('zh-CN', { hour12: false })}
          </span>
        )}
      </div>

      {/* 综合叙述 */}
      {insights.overall_narrative && (
        <div>
          <div className="section-label" style={{ marginBottom: 6 }}>综合叙述</div>
          <div style={{ fontSize: 13, color: 'var(--content-fg)', lineHeight: 1.7, padding: '10px 12px', background: 'var(--surface-secondary)', borderRadius: 'var(--radius-md)' }}>
            {insights.overall_narrative}
          </div>
        </div>
      )}

      {/* 字段洞察 */}
      {fi.length > 0 && (
        <div>
          <div className="section-label" style={{ marginBottom: 6 }}>字段洞察 · {fi.length}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {fi.map((f, i) => (
              <div key={i} className="row-item">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
                  <span className="font-mono" style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>{f.field_name || '未知字段'}</span>
                  {f.source_type && (
                    <span style={{ fontSize: 11, padding: '1px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--surface-secondary)', border: '1px solid var(--surface-border-subtle)', color: 'var(--content-fg-secondary)' }}>
                      {SOURCE_LABELS[f.source_type] || f.source_type}
                    </span>
                  )}
                  {f.confidence != null && (
                    <span style={{ marginLeft: 'auto', fontSize: 11, padding: '1px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--status-progress-bg)', color: 'var(--status-progress)' }}>
                      置信度 {fmtConf(f.confidence)}
                    </span>
                  )}
                </div>
                {f.observation && <div className="hint">{f.observation}</div>}
                {f.interpretation && <div className="hint-dim" style={{ marginTop: 4 }}>解读：{f.interpretation}</div>}
                {f.typical_range != null && (
                  <div className="hint-dim" style={{ marginTop: 2 }}>典型范围：{String(f.typical_range)}</div>
                )}
                {Array.isArray(f.cause_hypotheses) && f.cause_hypotheses.length > 0 && (
                  <div className="hint-dim" style={{ marginTop: 2 }}>成因假设：{f.cause_hypotheses.join('；')}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 跨字段关系 */}
      {rel.length > 0 && (
        <div>
          <div className="section-label" style={{ marginBottom: 6 }}>跨字段关系 · {rel.length}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {rel.map((r, i) => (
              <div key={i} className="row-item">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
                  <span className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg)' }}>{r.field_a} ↔ {r.field_b}</span>
                  <span style={{ fontSize: 11, padding: '1px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--accent-light)', color: 'var(--accent-text)' }}>
                    {REL_LABELS[r.relationship_type] || r.relationship_type || '关系'}
                  </span>
                  {r.confidence != null && (
                    <span className="font-mono" style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--content-fg-tertiary)' }}>置信度 {fmtConf(r.confidence)}</span>
                  )}
                </div>
                {r.description && <div className="hint">{r.description}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 使用建议 */}
      {lists.length > 0 && (
        <div>
          <div className="section-label" style={{ marginBottom: 6 }}>使用建议</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {lists.map(([label, arr]) => (
              <div key={label}>
                <div style={{ fontSize: 12, fontWeight: 510, color: 'var(--content-fg-secondary)', marginBottom: 4 }}>{label}</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {arr.map((item, i) => (
                    <div key={i} className="hint" style={{ display: 'flex', gap: 8 }}>
                      <span style={{ color: 'var(--content-fg-tertiary)', flexShrink: 0 }}>·</span>
                      <span>{typeof item === 'string' ? item : JSON.stringify(item)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/* ── 质量报告（质量 tab）：report_state.quality 真实数据 ───────────────
 * quality_scoring: { overall_score: 0-1, overall_score_ci: [lo, hi],
 *   quality_level, per_source_scores: {sid: 0-1}, per_source_routes: {sid: 路由},
 *   route_counts: {路由: n}, per_source_reasons?: {sid: 原因} }
 * qState.sources: { sid: { title, record_count, extraction_quality: {score} } }
 */
const ROUTE_LABELS = {
  Normalization: '归一化', Conflict: '冲突消解', DirectExport: '直接导出',
  Export: '导出', Quarantine: '隔离', Skip: '跳过',
}
function routeColor(route) {
  if (route === 'Conflict' || route === 'Quarantine') return route === 'Conflict' ? 'var(--status-warn)' : 'var(--status-error)'
  return 'var(--status-success)'
}
function scoreColor(v) {
  if (typeof v !== 'number') return 'var(--content-fg-tertiary)'
  if (v >= 0.9) return 'var(--status-success)'
  if (v >= 0.75) return 'var(--status-progress)'
  return 'var(--status-warn)'
}

function QualityReport({ qState }) {
  const scoring = qState?.quality_scoring || {}
  const srcMap = qState?.sources || {}
  const perScores = scoring.per_source_scores || {}
  const routes = qState?.per_source_routes || {}
  const reasons = qState?.per_source_reasons || {}
  const routeCounts = qState?.route_counts || {}
  const ci = Array.isArray(scoring.overall_score_ci) && scoring.overall_score_ci.length >= 2 ? scoring.overall_score_ci : null
  // 逐源按分数升序（最差的排前面，便于审视问题源）
  const rows = Object.keys(perScores)
    .sort((a, b) => (perScores[a] ?? 0) - (perScores[b] ?? 0))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {/* 综合评分头部 */}
      <div className="kpi-card" style={{ padding: '14px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <span className="font-mono" style={{ fontSize: 30, fontWeight: 590, letterSpacing: '-0.02em', color: scoreColor(scoring.overall_score) }}>
            {typeof scoring.overall_score === 'number' ? (scoring.overall_score * 100).toFixed(1) : '—'}
          </span>
          <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--content-fg-tertiary)' }}>/ 100 综合质量分</span>
          {scoring.quality_level && (
            <span style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 10px', borderRadius: 'var(--radius-pill)', fontWeight: 510, color: gradeColor(scoring.quality_level), background: 'var(--surface-secondary)', border: '1px solid var(--surface-border-subtle)' }}>
              等级 {String(scoring.quality_level).toUpperCase()}
            </span>
          )}
        </div>
        {ci && (
          <div className="hint-dim" style={{ marginTop: 6 }}>
            95% 置信区间 {ci[0].toFixed(3)} – {ci[1].toFixed(3)} · 来源 {rows.length} 个
          </div>
        )}
      </div>

      {/* 路由分布 */}
      {Object.keys(routeCounts).length > 0 && (
        <div>
          <div className="section-label" style={{ marginBottom: 6 }}>清洗路由分布</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {Object.entries(routeCounts).map(([route, n]) => (
              <span key={route} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 'var(--fs-sm)', padding: '4px 12px', borderRadius: 'var(--radius-pill)', background: 'var(--surface-bg)', border: '1px solid var(--surface-border)' }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: routeColor(route) }} />
                {ROUTE_LABELS[route] || route}
                <span className="font-mono" style={{ color: 'var(--content-fg-tertiary)' }}>{n}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 逐源评分 */}
      {rows.length > 0 && (
        <div>
          <div className="section-label" style={{ marginBottom: 6 }}>逐源评分（低分在前）</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {rows.map((sid) => {
              const score = perScores[sid]
              const route = routes[sid]
              const src = srcMap[sid] || {}
              return (
                <div key={sid} className="row-item">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
                    <span className="font-mono" style={{ fontSize: 12, fontWeight: 510, color: 'var(--content-fg)' }}>{sid}</span>
                    {src.title && (
                      <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--content-fg-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '46%' }}>{src.title}</span>
                    )}
                    <span className="font-mono" style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 510, color: scoreColor(score) }}>
                      {typeof score === 'number' ? score.toFixed(3) : '—'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ flex: 1, height: 4, background: 'var(--surface-border)', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${Math.max(0, Math.min(1, score ?? 0)) * 100}%`, background: scoreColor(score), borderRadius: 2 }} />
                    </div>
                    {route && (
                      <span style={{ flexShrink: 0, fontSize: 10.5, padding: '1px 8px', borderRadius: 'var(--radius-pill)', color: routeColor(route), background: 'var(--surface-secondary)', border: '1px solid var(--surface-border-subtle)' }}>
                        {ROUTE_LABELS[route] || route}
                      </span>
                    )}
                  </div>
                  {reasons[sid] && <div className="hint-dim" style={{ marginTop: 5 }}>{reasons[sid]}</div>}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

/* ── 运行统计（运行 tab）：workflow_state + processing_statistics ──────
 * workflow_state: { llm_call_count, tool_call_count, iteration_counter,
 *   workflow_history: [{ agent, stage, status, timestamp, duration, reason }] }
 * processing_statistics: { total_llm_calls, total_tool_calls,
 *   total_elapsed_seconds, b_c_loop_iterations }
 */
function fmtElapsed(sec) {
  if (typeof sec !== 'number' || !isFinite(sec)) return '—'
  if (sec < 60) return `${sec.toFixed(1)}s`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}m ${s}s`
}
function fmtTime(ts) {
  try {
    return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false })
  } catch { return '—' }
}
function ExecutionReport({ workflowState, procStats }) {
  const ws = workflowState || {}
  const ps = procStats || {}
  const llm = ws.llm_call_count ?? ps.total_llm_calls ?? null
  const tools = ws.tool_call_count ?? ps.total_tool_calls ?? null
  const elapsed = ps.total_elapsed_seconds ?? null
  const loops = ps.b_c_loop_iterations ?? ws.iteration_counter ?? null
  const history = Array.isArray(ws.workflow_history)
    ? [...ws.workflow_history].sort((a, b) => String(a.timestamp || '').localeCompare(String(b.timestamp || '')))
    : []
  const stats = [
    ['LLM 调用', llm, 'var(--content-fg)'],
    ['工具调用', tools, 'var(--content-fg)'],
    ['总耗时', fmtElapsed(elapsed), 'var(--content-fg)'],
    ['B⇄C 循环', loops, loops > 1 ? 'var(--status-warn)' : 'var(--content-fg)'],
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {/* 计数卡 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {stats.map(([label, value, color]) => (
          <div key={label} className="kpi-card" style={{ padding: '10px 12px' }}>
            <div className="kpi-label" style={{ marginBottom: 4 }}>{label}</div>
            <div className="font-mono kpi-value-sm" style={{ color }}>{value ?? '—'}</div>
          </div>
        ))}
      </div>

      {/* 审计时间线 */}
      {history.length > 0 ? (
        <div>
          <div className="section-label" style={{ marginBottom: 6 }}>执行审计 · {history.length} 步</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {history.map((h, i) => (
              <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'baseline', padding: '6px 10px', background: i % 2 ? 'var(--surface-secondary)' : 'transparent', borderRadius: 'var(--radius-sm)' }}>
                <span className="font-mono" style={{ flexShrink: 0, fontSize: 11, color: 'var(--content-fg-tertiary)' }}>{fmtTime(h.timestamp)}</span>
                <span className="font-mono" style={{ flexShrink: 0, fontSize: 12, fontWeight: 510, color: 'var(--content-fg)' }}>{h.agent || '—'}</span>
                {h.stage && (
                  <span style={{ flexShrink: 0, fontSize: 10.5, padding: '1px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--surface-secondary)', border: '1px solid var(--surface-border-subtle)', color: 'var(--content-fg-secondary)' }}>
                    {h.stage}
                  </span>
                )}
                <span style={{ flex: 1, fontSize: 11, color: 'var(--content-fg-tertiary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.reason || ''}</span>
                {typeof h.duration === 'number' && (
                  <span className="font-mono" style={{ flexShrink: 0, fontSize: 11, color: 'var(--content-fg-secondary)' }}>{fmtElapsed(h.duration)}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <TabEmpty text="暂无执行审计记录" />
      )}
    </div>
  )
}

export default function DetailPanel({ open, onClose, task, pipeline, requestedTab }) {
  const [width, setWidth] = useState(560)
  const [section, setSection] = useState('overview')
  const [lightbox, setLightbox] = useState(null)
  const dragRef = useRef(null)
  const isDrawer = useMediaQuery('(max-width: 1279px)')

  // 真实数据（契约 D1-3/D7-3/D9-2：重度数据走 HTTP 接口；概览统计全部来自真实接口）
  const [sources, setSources] = useState([])
  const [exports, setExports] = useState([])
  const [figures, setFigures] = useState([])
  const [quality, setQuality] = useState(null)
  const [traces, setTraces] = useState([])
  const [recordCount, setRecordCount] = useState(null)
  const [loading, setLoading] = useState(false)
  // 洞察报告来自 pipeline（usePipeline 从 /state 快照 hydrate；
  // 后端 GET /quality 的 insights 字段恒为 null，不再消费）
  const insights = pipeline?.insights || null

  // 外部请求切 tab（洞察卡"查看完整报告"，seq 递增重复触发）
  useEffect(() => {
    if (requestedTab?.tab) setSection(requestedTab.tab)
  }, [requestedTab])

  useEffect(() => {
    if (!task?.task_id) {
      // M-02: task 为 null（点击"新建"）→ 清空旧任务数据（概览/来源/图证/质量不再残留）
      setSources([]); setExports([]); setFigures([]); setQuality(null)
      setTraces([]); setRecordCount(null)
      setLoading(false)
      return
    }
    let alive = true
    setSources([]); setExports([]); setFigures([]); setQuality(null)
    setTraces([]); setRecordCount(null)
    setLoading(true)
    Promise.all([
      api.getSources(task.task_id).catch(() => []),
      api.getExports(task.task_id).catch(() => []),
      api.getFigures(task.task_id).catch(() => []),
      api.getQuality(task.task_id).catch(() => null),
      api.getRecords(task.task_id).catch(() => []),
    ]).then(([src, ex, fig, q, recs]) => {
      if (!alive) return
      setSources(src)
      setExports(ex)
      setFigures(fig)
      setQuality(q)
      setTraces(q?.quality_report?.data_state?.data_trace || [])
      setRecordCount(Array.isArray(recs) ? recs.length : null)
      setLoading(false)
    })
    return () => { alive = false }
    // task.status 变化（running→completed）时重拉：任务进行中 final_output 未生成，
    // 完成后必须刷新右侧栏（修复"右侧栏永远 0"）
  }, [task?.task_id, task?.status])

  /* 拖拽调宽 */
  const startDrag = (e) => {
    dragRef.current = { startX: e.clientX, startW: width }
    const onMove = (ev) => {
      if (!dragRef.current) return
      const next = Math.min(MAX_W, Math.max(MIN_W, dragRef.current.startW + (dragRef.current.startX - ev.clientX)))
      setWidth(next)
    }
    const onUp = () => {
      dragRef.current = null
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  /* 质量报告真实结构（契约：GET /quality → { quality_report: QualityGraphState }）：
   * - report_state.quality.quality_scoring：综合分/等级/逐源评分/路由
   * - workflow_state：LLM/工具调用计数 + workflow_history 审计轨迹
   * - output_state.quality_summary.processing_statistics：总耗时/B⇄C 轮次
   */
  const qState = useMemo(() => quality?.quality_report?.report_state?.quality || null, [quality])
  const qScoring = useMemo(() => qState?.quality_scoring || null, [qState])
  const workflowState = useMemo(() => quality?.quality_report?.workflow_state || null, [quality])
  const procStats = useMemo(
    () => quality?.quality_report?.output_state?.quality_summary?.processing_statistics || null,
    [quality],
  )
  const overallScore = useMemo(() => {
    const v = qScoring?.overall_score
    if (typeof v !== 'number') return null
    return Math.round(v * 100)
  }, [qScoring])

  if (!open) return null

  const insightCount = insights
    ? ((Array.isArray(insights.field_insights) ? insights.field_insights.length : 0)
      + (Array.isArray(insights.cross_field_relationships) ? insights.cross_field_relationships.length : 0))
    : 0

  const sections = [
    { key: 'overview', label: '概览' },
    { key: 'quality', label: '质量' },
    { key: 'run', label: '运行' },
    { key: 'sources', label: `来源 (${sources.length})` },
    { key: 'figures', label: `图证 (${figures.length})` },
    { key: 'traces', label: `轨迹 (${traces.length})` },
    { key: 'insights', label: `洞察 (${insightCount})` },
    { key: 'downloads', label: '下载' },
  ]

  const taskRunning = task && (task.status === 'running' || task.status === 'queued')

  return (
    <>
      {/* 窄屏覆盖式抽屉的遮罩 */}
      {isDrawer && (
        <div
          onClick={onClose}
          className="animate-fade-in"
          style={{ position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 55 }}
        />
      )}
      <aside
        data-component="detail-panel"
        className={`detail-panel glass${isDrawer ? ' animate-drawer-in' : ''}`}
        style={{
          width: isDrawer ? Math.min(width, Math.max(320, window.innerWidth - 48)) : width,
          minWidth: isDrawer ? Math.min(width, Math.max(320, window.innerWidth - 48)) : width,
          borderLeft: '1px solid var(--glass-border)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          position: 'relative',
          flexShrink: 0,
        }}
      >
        {/* 拖拽手柄（宽屏才有意义） */}
        {!isDrawer && (
          <div
            onMouseDown={startDrag}
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              bottom: 0,
              width: 5,
              cursor: 'col-resize',
              zIndex: 10,
              background: 'transparent',
            }}
          />
        )}

        {/* 头部 */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '12px 16px 0', flexShrink: 0 }}>
          <h2 style={{ fontSize: 14, fontWeight: 510, flex: 1 }}>执行详情</h2>
          <Button variant="ghost" size="icon" onClick={onClose}>
            <Icon.Close />
          </Button>
        </div>

        {/* 分区 Tab */}
        <div style={{ display: 'flex', gap: 2, padding: '6px 10px 0', borderBottom: '1px solid var(--surface-border)', flexShrink: 0, overflowX: 'auto' }}>
          {sections.map((s) => (
            <button
              key={s.key}
              onClick={() => setSection(s.key)}
              className={`tab-btn${section === s.key ? ' active' : ''}`}
            >
              {s.label}
            </button>
          ))}
        </div>

        <ScrollArea className="flex-1 p-4">
          {loading ? (
            <PanelSkeleton />
          ) : (
            <div key={section} className="animate-tab-in">
              {/* ── 概览 ── */}
              {section === 'overview' && (
                <div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 16 }}>
                    {[
                      ['数据源', sources.length, 'var(--content-fg)'],
                      ['记录', recordCount ?? '—', 'var(--content-fg)'],
                      ['图证', figures.length, 'var(--content-fg)'],
                      ['状态', STATUS_LABELS[task?.status] || '—', STATUS_COLORS[task?.status] || 'var(--content-fg)'],
                    ].map(([label, value, color]) => (
                      <div key={label} className="kpi-card" style={{ padding: '10px 12px' }}>
                        <div className="kpi-label" style={{ marginBottom: 4 }}>{label}</div>
                        <div className="font-mono kpi-value-sm" style={{ color }}>{value}</div>
                      </div>
                    ))}
                  </div>

                  {/* 质量评分摘要（真实数据：report_state.quality.quality_scoring） */}
                  {qScoring ? (
                    <>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                        <span className="section-label">质量评分</span>
                        <span
                          className="font-mono"
                          style={{
                            marginLeft: 'auto', fontSize: 'var(--fs-md)', fontWeight: 510,
                            color: scoreColor(qScoring.overall_score),
                          }}
                        >
                          {overallScore} 分
                        </span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                        {qScoring.quality_level && (
                          <span style={{ fontSize: 11, padding: '2px 10px', borderRadius: 'var(--radius-pill)', fontWeight: 510, color: gradeColor(qScoring.quality_level), background: 'var(--surface-secondary)', border: '1px solid var(--surface-border-subtle)' }}>
                            等级 {String(qScoring.quality_level).toUpperCase()}
                          </span>
                        )}
                        <span className="hint-dim">
                          {Object.entries(qState?.route_counts || {})
                            .map(([r, n]) => `${ROUTE_LABELS[r] || r} ${n}`).join(' · ') || '—'}
                        </span>
                      </div>
                      <Button variant="outline" size="sm" onClick={() => setSection('quality')}>
                        查看质量报告
                      </Button>
                    </>
                  ) : (
                    <TabEmpty text={taskRunning ? '任务进行中，质检完成后展示评分' : '暂无质量报告'} />
                  )}
                </div>
              )}

              {/* ── 质量报告（report_state.quality 完整评分/路由） ── */}
              {section === 'quality' && (
                qState ? <QualityReport qState={qState} /> : <TabEmpty text={taskRunning ? '任务进行中，质检完成后生成质量报告' : '暂无质量报告'} />
              )}

              {/* ── 运行统计（workflow_state + processing_statistics） ── */}
              {section === 'run' && (
                (workflowState || procStats)
                  ? <ExecutionReport workflowState={workflowState} procStats={procStats} />
                  : <TabEmpty text={taskRunning ? '任务进行中，统计数据随执行累积' : '暂无运行统计'} />
              )}

              {/* ── 来源（契约 D7-6） ── */}
              {section === 'sources' && (
                sources.length ? <SourcesList sources={sources} /> : <TabEmpty text="暂无数据源" />
              )}

              {/* ── 图证（双列缩略图 + 灯箱，契约 D9-4） ── */}
              {section === 'figures' && (
                figures.length ? (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    {figures.map((fig) => (
                      <div key={fig.id} className="row-item" style={{ padding: 8 }}>
                        <div onClick={() => setLightbox(fig)} style={{ cursor: 'zoom-in' }}>
                          <FigureThumb fig={fig} />
                        </div>
                        <div className="hint-dim" style={{ marginTop: 6 }}>
                          {fig.caption} · 第 {fig.page} 页
                        </div>
                      </div>
                    ))}
                  </div>
                ) : <TabEmpty text="暂无图证" />
              )}

              {/* ── 修改轨迹（data_state.data_trace：{source_id, tool, reason, timestamp}） ── */}
              {section === 'traces' && (
                traces.length ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {traces.map((t, i) => (
                      <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'baseline', padding: '7px 10px', background: i % 2 ? 'var(--surface-secondary)' : 'transparent', borderRadius: 'var(--radius-sm)' }}>
                        <span className="font-mono" style={{ flexShrink: 0, fontSize: 11, color: 'var(--content-fg-tertiary)' }}>{fmtTime(t.timestamp)}</span>
                        <span className="font-mono" style={{ fontSize: 12, fontWeight: 510, color: 'var(--content-fg)' }}>{t.source_id || '—'}</span>
                        {t.tool && (
                          <span style={{ flexShrink: 0, fontSize: 10.5, padding: '1px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--surface-secondary)', border: '1px solid var(--surface-border-subtle)', color: 'var(--content-fg-secondary)' }}>
                            {t.tool}
                          </span>
                        )}
                        <span style={{ flex: 1, fontSize: 11, color: 'var(--content-fg-tertiary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.reason || ''}</span>
                      </div>
                    ))}
                  </div>
                ) : <TabEmpty text="本次任务未产生数据修改轨迹" />
              )}

              {/* ── 洞察（完整 DataInsightsReport，来自 /state） ── */}
              {section === 'insights' && (
                insights ? <InsightsReport insights={insights} /> : <TabEmpty text={taskRunning ? '任务进行中，交付阶段生成洞察' : '暂无洞察报告'} />
              )}

              {/* ── 输出文件（契约 D9：本地路径 + 复制/打开） ── */}
              {section === 'downloads' && (
                exports.length ? <OutputFiles files={exports} taskId={task?.task_id} /> : <TabEmpty text={taskRunning ? '任务进行中，交付阶段生成导出文件' : '暂无导出文件'} />
              )}
            </div>
          )}
        </ScrollArea>

        {/* 灯箱 */}
        {lightbox && (
          <div
            onClick={() => setLightbox(null)}
            style={{
              position: 'fixed',
              inset: 0,
              background: 'var(--overlay)',
              zIndex: 100,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'zoom-out',
            }}
          >
            <div style={{ background: 'var(--surface-bg)', borderRadius: 10, padding: 16, maxWidth: '90vw', maxHeight: '90vh', overflow: 'auto' }}>
              <FigureThumb fig={lightbox} size="large" />
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                <span style={{ fontSize: 13, color: 'var(--content-fg)' }}>{lightbox.caption}</span>
                <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--content-fg-tertiary)' }}>点击任意处关闭</span>
              </div>
            </div>
          </div>
        )}
      </aside>
    </>
  )
}
