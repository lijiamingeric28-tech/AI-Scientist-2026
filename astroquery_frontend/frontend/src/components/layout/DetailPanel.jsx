import { useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Icon } from '@/components/icons'
import { useEffect } from 'react'
import * as api from '@/services/api'
import { STATUS_LABELS, STATUS_COLORS } from '@/components/status'
import { SourcesList, OutputFiles } from '@/components/results/ResultTabs'
import { useToast } from '@/components/ui/toast'

/* 右侧详情面板（块 5 定案）：
 * - 宽度 560 默认，可拖拽调宽（400-680）
 * - 分区 Tab：概览 / 图证（缩略图+灯箱）/ 修改轨迹 / 洞察 / 下载
 */

const MIN_W = 400
const MAX_W = 680

/* 图证缩略图：有 image_url 走真实图（契约 D7-3），否则 SVG 占位 */
function FigureThumb({ fig, size = 'thumb' }) {
  const w = size === 'thumb' ? 200 : 560
  const h = size === 'thumb' ? 130 : 364
  const b = fig.bbox || fig.bbox_2d
  if (fig.image_url) {
    return (
      <div style={{ position: 'relative', width: w, height: h, background: 'var(--surface-secondary)', borderRadius: 6, overflow: 'hidden' }}>
        <img src={fig.image_url} alt={fig.caption || ''} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
        {b && (
          <div style={{
            position: 'absolute',
            left: `${b[0] * 100}%`, top: `${b[1] * 100}%`,
            width: `${(b[2] - b[0]) * 100}%`, height: `${(b[3] - b[1]) * 100}%`,
            border: '1.5px solid #ef4444', borderRadius: 2, pointerEvents: 'none',
          }} />
        )}
      </div>
    )
  }
  return (
    <svg width={w} height={h} viewBox={`0 0 200 130`} style={{ display: 'block', borderRadius: 6 }}>
      <defs>
        <linearGradient id={`bg-${fig.id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={`hsl(${fig.hue}, 45%, 88%)`} />
          <stop offset="100%" stopColor={`hsl(${fig.hue}, 55%, 72%)`} />
        </linearGradient>
      </defs>
      {/* 假图内容 */}
      <rect width="200" height="130" fill={`url(#bg-${fig.id})`} />
      <polyline points="20,100 60,80 100,88 140,52 180,60" fill="none" stroke="hsl(0,0%,40%)" strokeWidth="1.5" />
      <circle cx="100" cy="88" r="3" fill="hsl(0,0%,25%)" />
      <rect x="30" y="20" width="40" height="25" fill="hsl(0,0%,92%)" opacity="0.7" />
      {/* bbox 标注 */}
      <rect x={b[0] * 200} y={b[1] * 130} width={(b[2] - b[0]) * 200} height={(b[3] - b[1]) * 130} fill="none" stroke="#ef4444" strokeWidth="1.5" strokeDasharray="4 3" />
      <circle cx={b[0] * 200 + 3} cy={b[1] * 130 + 3} r="3" fill="#ef4444" />
    </svg>
  )
}

export default function DetailPanel({ open, onClose, task }) {
  const [width, setWidth] = useState(560)
  const [section, setSection] = useState('overview')
  const [lightbox, setLightbox] = useState(null)
  const dragRef = useRef(null)
  const { toast } = useToast()

  // 真实数据（契约 D1-3/D7-3/D9-2：重度数据走 HTTP 接口；概览统计全部来自真实接口）
  const [sources, setSources] = useState([])
  const [exports, setExports] = useState([])
  const [figures, setFigures] = useState([])
  const [quality, setQuality] = useState(null)
  const [traces, setTraces] = useState([])
  const [insights, setInsights] = useState([])
  const [recordCount, setRecordCount] = useState(null)

  useEffect(() => {
    if (!task?.task_id) {
      // M-02: task 为 null（点击"新建"）→ 清空旧任务数据（概览/来源/图证/质量不再残留）
      setSources([]); setExports([]); setFigures([]); setQuality(null)
      setTraces([]); setInsights([]); setRecordCount(null)
      return
    }
    let alive = true
    setSources([]); setExports([]); setFigures([]); setQuality(null)
    setTraces([]); setInsights([]); setRecordCount(null)
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
      setTraces(q?.quality_report?.data_trace || [])
      setInsights(q?.insights || [])
      setRecordCount(Array.isArray(recs) ? recs.length : null)
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

  if (!open) return null

  const sections = [
    { key: 'overview', label: '概览' },
    { key: 'sources', label: `来源 (${sources.length})` },
    { key: 'figures', label: `图证 (${figures.length})` },
    { key: 'traces', label: '轨迹' },
    { key: 'insights', label: `洞察 (${insights.length})` },
    { key: 'downloads', label: '下载' },
  ]

  return (
    <aside
      style={{
        width,
        minWidth: width,
        background: 'var(--surface-bg)',
        borderLeft: '1px solid var(--surface-border)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      {/* 拖拽手柄 */}
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
            style={{
              padding: '7px 10px',
              fontSize: 12,
              border: 'none',
              cursor: 'pointer',
              background: 'transparent',
              whiteSpace: 'nowrap',
              color: section === s.key ? 'var(--accent-text)' : 'var(--content-fg-secondary)',
              fontWeight: section === s.key ? 510 : 400,
              borderBottom: section === s.key ? '2px solid var(--accent)' : '2px solid transparent',
            }}
          >
            {s.label}
          </button>
        ))}
      </div>

      <ScrollArea className="flex-1 p-4">
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
                <div key={label} style={{ padding: '10px 12px', background: 'var(--surface-secondary)', borderRadius: 6 }}>
                  <div style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginBottom: 4, fontWeight: 510 }}>{label}</div>
                  <div className="font-mono" style={{ fontSize: 16, fontWeight: 510, color }}>{value}</div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 11, fontWeight: 510, color: 'var(--content-fg-tertiary)', marginBottom: 8, letterSpacing: '0.05em' }}>质量评分</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {(quality?.quality_report?.scores || []).map((s) => (
                <div key={s.dim}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 3 }}>
                    <span style={{ color: 'var(--content-fg-secondary)' }}>{s.dim}</span>
                    <span className="font-mono" style={{ color: s.value >= 90 ? 'var(--status-success)' : 'var(--status-progress)' }}>{s.value}</span>
                  </div>
                  <div style={{ height: 4, background: 'var(--surface-border)', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${s.value}%`, background: s.value >= 90 ? 'var(--status-success)' : 'var(--status-progress)', borderRadius: 2 }} />
                  </div>
                </div>
              ))}
            </div>
            {quality?.quality_report?.routing && (
              <div style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginTop: 12, lineHeight: 1.6 }}>{quality.quality_report.routing}</div>
            )}
          </div>
        )}

        {/* ── 来源（契约 D7-6 新增） ── */}
        {section === 'sources' && <SourcesList sources={sources} />}

        {/* ── 图证（缩略图 + 灯箱 + 本地路径，契约 D9-4） ── */}
        {section === 'figures' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {figures.map((fig) => (
              <div key={fig.id} style={{ border: '1px solid var(--surface-border-subtle)', borderRadius: 8, padding: 10 }}>
                <div onClick={() => setLightbox(fig)} style={{ cursor: 'zoom-in' }}>
                  <FigureThumb fig={fig} />
                </div>
                <div style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginTop: 6, lineHeight: 1.5 }}>
                  {fig.caption} · 第 {fig.page} 页 <span style={{ color: 'var(--status-error)' }}>■ bbox</span>
                </div>
                <div className="font-mono" style={{ fontSize: 10.5, color: 'var(--content-fg-tertiary)', marginTop: 4, wordBreak: 'break-all', lineHeight: 1.5 }}>
                  {fig.image_url}
                </div>
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  <Button variant="outline" size="sm" onClick={() => { setLightbox(fig) }}>预览</Button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── 修改轨迹 ── */}
        {section === 'traces' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {traces.map((t, i) => (
              <div key={i} style={{ border: '1px solid var(--surface-border-subtle)', borderRadius: 8, padding: '10px 12px' }}>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                  <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>{t.field}</span>
                  <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>{t.before} → {t.after}</span>
                  <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--accent-text)' }}>{t.tool}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginTop: 4 }}>{t.reason} · 置信度 {t.confidence}</div>
              </div>
            ))}
          </div>
        )}

        {/* ── 洞察 ── */}
        {section === 'insights' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {insights.map((ins, i) => (
              <div key={i} style={{ border: '1px solid var(--surface-border-subtle)', borderRadius: 8, padding: '10px 12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{ fontSize: 11, padding: '1px 8px', borderRadius: 4, background: 'var(--accent-light)', color: 'var(--accent-text)', flexShrink: 0 }}>
                    {ins.type === 'field' ? '字段' : ins.type === 'relationship' ? '关联' : '建议'}
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>{ins.title}</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--content-fg-secondary)', lineHeight: 1.6 }}>{ins.content}</div>
              </div>
            ))}
          </div>
        )}

        {/* ── 输出文件（契约 D9：本地路径 + 复制/打开） ── */}
        {section === 'downloads' && <OutputFiles files={exports} taskId={task.task_id} />}
      </ScrollArea>

      {/* 灯箱 */}
      {lightbox && (
        <div
          onClick={() => setLightbox(null)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.65)',
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
  )
}
