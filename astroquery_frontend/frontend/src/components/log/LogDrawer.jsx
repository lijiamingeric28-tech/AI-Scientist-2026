import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { MOCK_LOGS } from '@/mock/logs'

/* 底部日志抽屉（块 7 定案）：可折叠 / 可调高度 / 级别过滤 / 实时追加
 * mock：打开后按节奏逐行追加预生成日志（模拟 WebSocket 日志流）
 */

const LEVEL_COLOR = {
  INFO: 'var(--content-fg-tertiary)',
  WARN: '#d97706',
  ERROR: 'var(--status-error)',
}

export default function LogDrawer({ open, onClose, liveLogs }) {
  const [height, setHeight] = useState(240)
  const [levelFilter, setLevelFilter] = useState('all')
  const [lines, setLines] = useState([])
  const dragRef = useRef(null)
  const scrollRef = useRef(null)

  // 真实日志流（契约 D3-3：log 事件经 SSE 传入）；无 liveLogs 时退回 mock 定时器
  useEffect(() => {
    if (!open) return
    if (liveLogs) {
      setLines(liveLogs.map((l) => ({ ...l })))
      return
    }
    setLines([])
    let i = 0
    const timer = setInterval(() => {
      if (i < MOCK_LOGS.length) {
        setLines((prev) => [...prev, { ...MOCK_LOGS[i], time: `12:0${1 + Math.floor(i / 10)}:${String(10 + i).slice(-2)}` }])
        i += 1
      } else {
        clearInterval(timer)
      }
    }, 180)
    return () => clearInterval(timer)
  }, [open, liveLogs])

  // M-03：仅渲染最近 200 行（真实流单任务 400+ 条，全量渲染 O(n²) 掉帧）
  const MAX_RENDER_LINES = 200

  // 自动滚动到底
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [lines])

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

  const filtered = lines.filter((l) => levelFilter === 'all' || l.level === levelFilter).slice(-MAX_RENDER_LINES)

  return (
    <div style={{ flexShrink: 0, borderTop: '1px solid var(--surface-border)', background: 'var(--surface-bg)', display: 'flex', flexDirection: 'column' }}>
      {/* 拖拽手柄 */}
      <div onMouseDown={startDrag} style={{ height: 4, cursor: 'ns-resize', background: 'transparent' }} />

      {/* 头部 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', borderBottom: '1px solid var(--surface-border-subtle)' }}>
        <Icon.FileText style={{ width: 13, height: 13, color: 'var(--content-fg-tertiary)' }} />
        <span style={{ fontSize: 12, fontWeight: 510, color: 'var(--content-fg)' }}>实时日志</span>
        {/* M-03：真实流（liveLogs）分母是真实行数，不用 mock 常量（曾显示 412/38 行） */}
        <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>{liveLogs ? `${lines.length} 行` : `${lines.length}/${MOCK_LOGS.length} 行`}</span>
        <div style={{ display: 'flex', gap: 4, marginLeft: 12 }}>
          {['all', 'INFO', 'WARN', 'ERROR'].map((lv) => (
            <button
              key={lv}
              onClick={() => setLevelFilter(lv)}
              style={{
                padding: '2px 8px',
                fontSize: 11,
                borderRadius: 4,
                border: '1px solid var(--surface-border)',
                cursor: 'pointer',
                background: levelFilter === lv ? 'var(--accent-light)' : 'transparent',
                color: levelFilter === lv ? 'var(--accent-text)' : 'var(--content-fg-secondary)',
              }}
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
      <div ref={scrollRef} style={{ height, overflowY: 'auto', padding: '6px 12px 10px', fontFamily: 'ui-monospace, Menlo, Consolas, monospace', fontSize: 11.5, lineHeight: 1.7 }}>
        {filtered.length === 0 && (
          <div style={{ color: 'var(--content-fg-tertiary)', padding: '20px 0', textAlign: 'center' }}>暂无日志</div>
        )}
        {filtered.map((l, i) => (
          <div key={i} style={{ display: 'flex', gap: 10, whiteSpace: 'nowrap' }}>
            <span style={{ color: 'var(--content-fg-tertiary)' }}>{l.time}</span>
            <span style={{ color: LEVEL_COLOR[l.level] || 'var(--content-fg-tertiary)', width: 44, flexShrink: 0 }}>{l.level}</span>
            <span style={{ color: 'var(--accent-text)', width: 110, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>[{l.node}]</span>
            <span style={{ color: 'var(--content-fg-secondary)', overflow: 'hidden', textOverflow: 'ellipsis' }}>{l.msg}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
