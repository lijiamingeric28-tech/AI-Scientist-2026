import { useEffect, useMemo, useState } from 'react'
import { Icon } from '@/components/icons'
import StageDetailPanel from './StageDetailPanel'

/* 工作流视图（第二界面）：KPI 概览带 + 纵向执行时间线
 * 每个阶段一行：编号轨道 + 状态徽标 + 卡头摘要 + 按比例耗时条 + Agent/流程计数，
 * 点击阶段行 → StageDetailPanel 三级下钻（阶段执行明细 → Agent 明细）。
 * 数据源：usePipeline 的 stages（SSE 事件流驱动，契约 API_CONTRACT.md）。
 * 与对话视图共享同一份 pipeline 状态（状态上提到 App），切换视图不丢进度。
 *
 * 阶段状态（stage.status）：waiting | running | completed | error | skipped | cancelled
 */

/* 阶段状态 → 颜色 / 底色 / 文案 */
const STAGE_COLORS = {
  completed: 'var(--status-success)',
  running: 'var(--status-progress)',
  error: 'var(--status-error)',
  waiting: 'var(--content-fg-tertiary)',
  skipped: 'var(--content-fg-tertiary)',
  cancelled: 'var(--content-fg-tertiary)',
}
const STAGE_PILL_BG = {
  completed: 'var(--status-success-bg)',
  running: 'var(--status-progress-bg)',
  error: 'var(--status-error-bg)',
  waiting: 'var(--surface-secondary)',
  skipped: 'var(--surface-secondary)',
  cancelled: 'var(--surface-secondary)',
}
const STAGE_LABELS = {
  completed: '已完成', running: '执行中', error: '失败',
  waiting: '等待中', skipped: '已跳过', cancelled: '已取消',
}

/* 解析 stage.duration（形如 "3.2s"）为秒；无数据返回 null */
function parseSec(stage) {
  if (!stage.duration) return null
  const n = parseFloat(stage.duration)
  return Number.isFinite(n) && n > 0 ? n : null
}

/* KPI 概览带：总耗时 / 阶段进度 / 当前阶段 / 耗时最长（瓶颈） */
function StatsStrip({ stages }) {
  const stats = useMemo(() => {
    const done = stages.filter((s) => s.status === 'completed')
    const timed = stages.map((s) => ({ s, sec: parseSec(s) })).filter((r) => r.sec != null)
    const totalSec = timed.reduce((acc, r) => acc + r.sec, 0)
    const running = stages.find((s) => s.status === 'running')
    const lastDone = [...stages].reverse().find((s) => s.status === 'completed')
    const slowest = timed.length ? timed.reduce((a, b) => (b.sec > a.sec ? b : a)) : null
    return {
      total: totalSec > 0 ? `${totalSec.toFixed(1)}s` : '—',
      progress: `${done.length} / ${stages.length}`,
      current: running ? running.name : (lastDone ? `${lastDone.name} 已完成` : '未开始'),
      currentColor: running ? 'var(--status-progress)' : 'var(--content-fg)',
      slowest: slowest ? `${slowest.s.name} · ${slowest.sec.toFixed(0)}s` : '—',
    }
  }, [stages])

  const items = [
    { label: '总耗时', value: stats.total, color: 'var(--content-fg)' },
    { label: '阶段进度', value: stats.progress, color: 'var(--status-success)' },
    { label: '当前阶段', value: stats.current, color: stats.currentColor },
    { label: '耗时最长', value: stats.slowest, color: 'var(--content-fg-secondary)' },
  ]
  return (
    <div data-component="stats-strip" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12 }}>
      {items.map((it) => (
        <div key={it.label} className="kpi-card">
          <div className="kpi-label">{it.label}</div>
          <div className="kpi-value" style={{ color: it.color, fontSize: 'var(--fs-lg)' }}>{it.value}</div>
        </div>
      ))}
    </div>
  )
}

/* 阶段行脚注：Agent 数 / 流程轮次 / 子步骤进度（有则显示） */
function stageMeta(stage) {
  const parts = []
  if (Array.isArray(stage.agents) && stage.agents.length) {
    parts.push(`${stage.agents.length} 个 Agent`)
  }
  if (Array.isArray(stage.flows) && stage.flows.length) {
    parts.push(`${stage.flows.length} 轮子流程`)
  }
  if (Array.isArray(stage.substeps) && stage.substeps.length) {
    const doneCount = stage.substeps.filter((st) => st.status === 'completed').length
    parts.push(`子步骤 ${doneCount}/${stage.substeps.length}`)
  }
  return parts.join(' · ')
}

/* 纵向时间线中的单个阶段行 */
function StageRow({ stage, index, isLast, maxSec, totalSec, selected, onClick }) {
  const color = STAGE_COLORS[stage.status] || STAGE_COLORS.waiting
  const pillBg = STAGE_PILL_BG[stage.status] || STAGE_PILL_BG.waiting
  const sec = parseSec(stage)
  const pct = maxSec > 0 && sec != null ? Math.max(1.5, (sec / maxSec) * 100) : 0
  const share = totalSec > 0 && sec != null ? Math.round((sec / totalSec) * 100) : null
  const meta = stageMeta(stage)

  return (
    <div data-component="stage-row" style={{ display: 'flex', gap: 14 }}>
      {/* 左侧轨道：编号圆 + 连接线 */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 26, flexShrink: 0 }}>
        <div
          style={{
            width: 26, height: 26, borderRadius: '50%', flexShrink: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: `1.5px solid ${color}`,
            background: stage.status === 'running' ? pillBg : 'var(--surface-bg)',
            color: stage.status === 'waiting' || stage.status === 'skipped' ? 'var(--content-fg-tertiary)' : color,
            fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            boxShadow: stage.status === 'running' ? `0 0 0 4px ${pillBg}` : 'none',
            transition: 'box-shadow .2s ease, border-color .2s ease',
          }}
        >
          {index + 1}
        </div>
        {!isLast && (
          <div style={{ width: 1.5, flex: 1, minHeight: 14, background: 'var(--surface-border)', marginTop: 4 }} />
        )}
      </div>

      {/* 右侧阶段卡片 */}
      <div
        className={`stage-row${selected ? ' selected' : ''}`}
        onClick={onClick}
        style={{ flex: 1, minWidth: 0, padding: '12px 16px', marginBottom: isLast ? 0 : 14 }}
      >
        {/* 卡头：名称 + 状态徽标 + 耗时 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--content-fg)', whiteSpace: 'nowrap' }}>{stage.name}</span>
          <span
            style={{
              fontSize: 11, fontWeight: 500, padding: '2px 9px', borderRadius: 'var(--radius-pill)',
              color, background: pillBg, whiteSpace: 'nowrap',
              ...(stage.status === 'running' ? { animation: 'pulse-dot 2s ease-in-out infinite' } : {}),
            }}
          >
            {STAGE_LABELS[stage.status] || '—'}
          </span>
          <span style={{ flex: 1 }} />
          {sec != null ? (
            <span className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg-tertiary)' }}>{sec.toFixed(1)}s</span>
          ) : stage.status === 'completed' ? (
            <span style={{ fontSize: 12, color: 'var(--content-fg-tertiary)' }}>未计时</span>
          ) : null}
        </div>

        {/* 摘要 */}
        {stage.summary && (
          <div style={{
            marginTop: 6, fontSize: 13, color: 'var(--content-fg-secondary)', lineHeight: 1.55,
            display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
          }}>
            {stage.summary}
          </div>
        )}

        {/* 按比例耗时条（与最长阶段归一化）+ 占比 */}
        {sec != null && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10 }}>
            <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'var(--surface-secondary)', overflow: 'hidden' }}>
              <div style={{
                width: `${pct}%`, height: '100%', borderRadius: 3, background: color,
                opacity: stage.status === 'waiting' ? 0.35 : 0.8, transition: 'width .3s cubic-bezier(0.16, 1, 0.3, 1)',
              }}
              />
            </div>
            {share != null && (
              <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', flexShrink: 0 }}>
                占比 {share}%
              </span>
            )}
          </div>
        )}

        {/* 脚注：Agent / 子流程 / 子步骤计数 */}
        {meta && (
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--content-fg-tertiary)' }}>{meta}</div>
        )}
      </div>
    </div>
  )
}

export default function WorkflowView({ task, pipeline, onGoChat, onShowStageInChat }) {
  const { stages = [], started = false, pending = null } = pipeline || {}
  const [selectedId, setSelectedId] = useState(null)

  // 切换任务时重置选中阶段
  useEffect(() => { setSelectedId(null) }, [task?.task_id])

  const selected = stages.find((s) => s.id === selectedId) || null
  const clarifying = !!pending && pending.type !== 'greeting'

  const { maxSec, totalSec } = useMemo(() => {
    const secs = stages.map(parseSec).filter((n) => n != null)
    return {
      maxSec: secs.length ? Math.max(...secs) : 0,
      totalSec: secs.reduce((a, b) => a + b, 0),
    }
  }, [stages])

  return (
    <div data-component="workflow-view" style={{ flex: 1, overflowY: 'auto', padding: '24px 24px 32px' }}>
      <div style={{ maxWidth: 860, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 18 }}>
        {/* HITL 澄清挂起提示：回答入口在对话视图 */}
        {clarifying && (
          <div data-component="clarify-banner" className="glass" style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', borderRadius: 'var(--radius-lg)',
          }}>
            <Icon.MessageSquare style={{ color: 'var(--accent-text)', flexShrink: 0 }} />
            <span style={{ fontSize: 13, color: 'var(--content-fg)', flex: 1 }}>
              智能体有问题需要您确认：{pending.title || '请回到对话视图回答'}
            </span>
            <button
              onClick={onGoChat}
              style={{
                border: 'none', borderRadius: 'var(--radius-pill)', padding: '5px 14px', fontSize: 12, cursor: 'pointer',
                background: 'var(--accent)', color: 'var(--accent-on)', flexShrink: 0, fontWeight: 500,
              }}
            >去回答</button>
          </div>
        )}

        {/* 顶部标题 + 状态说明 */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <span style={{ fontSize: 16, fontWeight: 600, color: 'var(--content-fg)', letterSpacing: '-0.01em' }}>执行工作流</span>
          <span style={{ fontSize: 12, color: 'var(--content-fg-tertiary)' }}>
            {task ? (started ? '实时同步后端事件流 · 点击阶段查看执行明细' : '等待任务启动…') : '选择或新建一个任务以查看流程'}
          </span>
        </div>

        {/* KPI 概览带 */}
        <StatsStrip stages={stages} />

        {/* 纵向执行时间线（耗时条已按最长阶段归一化整合进行内） */}
        <div data-component="stage-timeline" className="card" style={{ padding: '18px 18px 16px' }}>
          {stages.map((stage, i) => (
            <StageRow
              key={stage.id}
              stage={stage}
              index={i}
              isLast={i === stages.length - 1}
              maxSec={maxSec}
              totalSec={totalSec}
              selected={selectedId === stage.id}
              onClick={() => setSelectedId(stage.id)}
            />
          ))}
        </div>
      </div>

      {/* 三级下钻面板：阶段执行明细 → Agent 明细 */}
      {selected && (
        <StageDetailPanel
          stage={selected}
          onClose={() => setSelectedId(null)}
          onShowStageInChat={onShowStageInChat}
        />
      )}
    </div>
  )
}
