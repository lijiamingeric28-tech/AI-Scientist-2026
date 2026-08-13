import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'

/* 底部日志抽屉（块 7 定案）：可折叠 / 可调高度 / 级别过滤 / 实时追加
 * 数据源：usePipeline logs（SSE log 事件，契约 D3-3）。
 * 性能：上游已做 500 条环形截断；本组件仅渲染最近 200 行（防全量重渲染掉帧）。
 */

const LEVEL_COLOR = {
  INFO: 'var(--content-fg-tertiary)',
  WARN: 'var(--status-warn)',
  ERROR: 'var(--status-error)',
}

const MAX_RENDER_LINES = 200

export default function LogDrawer({ open, onClose, liveLogs }) {
  const [height, setHeight] = useState(240)
  const [levelFilter, setLevelFilter] = useState('all')
  const scrollRef = useRef(null)
  const dragRef = useRef(null)

  const lines = liveLogs || []

  // 自动滚动到底（仅在已接近底部时，避免用户回看被拽走）
  const stickRef = useRef(true)
  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
  }
  useEffect(() => {
    if (stickRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [lines.length, open])

  // 高度拖拽
  const startDrag = (e) => {
    dragRef.current = { startY: e.clientY, startH: height }
    const onMove = (ev) => {
      if (!dragRef.current) return
      const next = Math.min(420, Math.max(160, dragRef.current.startH + (dragRef.current.startY - ev.clientY)))
      setHeight(next)
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

  const total = lines.length
  const filtered = lines.filter((l) => levelFilter === 'all' || l.level === levelFilter).slice(-MAX_RENDER_LINES)
  const truncated = filtered.length < (levelFilter === 'all' ? total : lines.filter((l) => l.level === levelFilter).length)

  return (
    <div data-component="log-drawer" className="glass" style={{ flexShrink: 0, borderTop: '1px solid var(--surface-border)', borderLeft: 'none', borderRight: 'none', borderBottom: 'none', display: 'flex', flexDirection: 'column' }}>
      {/* 拖拽手柄 */}
      <div onMouseDown={startDrag} style={{ height: 4, cursor: 'ns-resize', background: 'transparent' }} />

      {/* 头部 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', borderBottom: '1px solid var(--surface-border-subtle)' }}>
        <Icon.FileText style={{ width: 13, height: 13, color: 'var(--content-fg-tertiary)' }} />
        <span style={{ fontSize: 'var(--fs-sm)', fontWeight: 510, color: 'var(--content-fg)' }}>实时日志</span>
        <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--content-fg-tertiary)' }}>
          {total} 行{truncated ? ` · 仅显示最近 ${MAX_RENDER_LINES} 行` : ''}
        </span>
        <div style={{ display: 'flex', gap: 4, marginLeft: 12 }}>
          {['all', 'INFO', 'WARN', 'ERROR'].map((lv) => (
            <button
              key={lv}
              onClick={() => setLevelFilter(lv)}
              className={`log-chip${levelFilter === lv ? ' active' : ''}`}
            >
              {lv}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <Button variant="ghost" size="icon" onClick={onClose}>
          <Icon.ChevronDown />
        </Button>
      </div>

      {/* 日志区 */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{ height, overflowY: 'auto', padding: '6px 12px 10px', fontFamily: 'ui-monospace, Menlo, Consolas, monospace', fontSize: 11.5, lineHeight: 1.7 }}
      >
        {filtered.length === 0 && (
          <div style={{ color: 'var(--content-fg-tertiary)', padding: '20px 0', textAlign: 'center' }}>暂无日志</div>
        )}
        {filtered.map((l) => (
          <div key={l.id} style={{ display: 'flex', gap: 10, whiteSpace: 'nowrap' }}>
            <span style={{ color: 'var(--content-fg-tertiary)', flexShrink: 0 }}>{l.time || '--:--:--'}</span>
            <span style={{ color: LEVEL_COLOR[l.level] || 'var(--content-fg-tertiary)', width: 44, flexShrink: 0 }}>{l.level}</span>
            <span style={{ color: 'var(--accent-text)', width: 110, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>[{l.node}]</span>
            <span style={{ color: 'var(--content-fg-secondary)', overflow: 'hidden', textOverflow: 'ellipsis' }}>{l.message || l.msg}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
