import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Icon } from '@/components/icons'
import { StatusDot } from '@/components/status'

/* 左栏宽度（可拖拽 200-400px，默认 240；2026-08-27 布局减负） */
const SIDEBAR_MIN_W = 200
const SIDEBAR_MAX_W = 400

/* 相对时间格式化（契约 D7：created_at → "10 分钟前"） */
function formatRelativeTime(iso) {
  const diff = Date.now() - new Date(iso).getTime()
  const min = Math.floor(diff / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  if (day < 30) return `${day} 天前`
  return new Date(iso).toLocaleDateString('zh-CN')
}

/* 侧边栏（块 2 定案）：
 * - 顶部：新建提取任务按钮（点击清空主区、聚焦输入框）
 * - 状态筛选：全部 / 运行中 / 已完成 / 失败
 * - 任务列表：标题 + 相对时间 + 状态圆点，新→旧，选中高亮
 * - 底部：设置入口（内容块 7 再定）
 */

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'running', label: '运行中' },
  { key: 'completed', label: '已完成' },
  { key: 'error', label: '失败' },
]

export default function Sidebar({ tasks, total, selectedId, onSelect, onNew, onCollapse, onRetry, onReplay, onOpenSettings, onLoadMore, filter, onFilterChange, onDeleteTask, onBatchDelete }) {
  const [hoveredId, setHoveredId] = useState(null)
  // 2026-08-24: 批量删除管理模式
  const [manageMode, setManageMode] = useState(false)
  const [checked, setChecked] = useState(() => new Set())
  // 2026-08-27: 左栏可拖拽调宽（200-400px）；默认 320（用户反馈 300 仍略窄，再宽一点点）
  const [width, setWidth] = useState(320)
  const dragRef = useRef(null)

  const startDrag = (e) => {
    dragRef.current = { startX: e.clientX, startW: width }
    const onMove = (ev) => {
      if (!dragRef.current) return
      const next = Math.min(SIDEBAR_MAX_W, Math.max(SIDEBAR_MIN_W, dragRef.current.startW + (ev.clientX - dragRef.current.startX)))
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

  // 契约 D8-1：queued 归入"运行中"筛选档
  // H-01: 失败档按 error 匹配，同时兼容旧词表 failed（存量记录防御）
  const filtered = filter === 'all'
    ? tasks
    : filter === 'running'
      ? tasks.filter((t) => t.status === 'running' || t.status === 'queued')
      : tasks.filter((t) => t.status === filter || (filter === 'error' && t.status === 'failed'))

  const toggleCheck = (id) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const exitManage = () => {
    setManageMode(false)
    setChecked(new Set())
  }

  return (
    <aside
      className="glass"
      style={{
        width,
        minWidth: width,
        borderRight: '1px solid var(--glass-border)',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
      }}
    >
      {/* 拖拽手柄：右缘 5px（宽屏才需要；窄屏 <1024 已由 App 自动折叠） */}
      <div
        onMouseDown={startDrag}
        style={{
          position: 'absolute', right: 0, top: 0, bottom: 0, width: 5,
          cursor: 'col-resize', zIndex: 10, background: 'transparent',
        }}
        title="拖动调整宽度"
      />
      {/* 新建任务 + 收起 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '16px 12px 12px 16px' }}>
        <Button variant="sidebar" className="flex-1 justify-start gap-2 text-sm font-normal" onClick={onNew}>
          <Icon.Plus />
          <span>新建提取任务</span>
        </Button>
        <Button variant="ghost" size="icon" onClick={onCollapse} title="收起侧边栏">
          <Icon.ChevronLeft />
        </Button>
      </div>

      {/* 状态筛选 */}
      <div style={{ display: 'flex', gap: 2, padding: '0 12px 8px' }}>
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => onFilterChange(f.key)}
            style={{
              flex: 1,
              padding: '4px 0',
              fontSize: 12,
              borderRadius: 5,
              border: 'none',
              cursor: 'pointer',
              background: filter === f.key ? 'var(--sidebar-active)' : 'transparent',
              color: filter === f.key ? 'var(--sidebar-text)' : 'var(--sidebar-text-secondary)',
              fontWeight: filter === f.key ? 510 : 400,
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* 历史任务（管理模式入口） */}
      <div
        style={{
          padding: '4px 8px 8px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <span
          style={{
            color: 'var(--sidebar-text-secondary)',
            fontSize: 11,
            fontWeight: 510,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
          }}
        >
          历史任务
        </span>
        <button
          onClick={() => (manageMode ? exitManage() : setManageMode(true))}
          style={{
            border: 'none', background: 'transparent', cursor: 'pointer',
            color: manageMode ? 'var(--status-error)' : 'var(--sidebar-text-secondary)',
            fontSize: 11, padding: '2px 6px', borderRadius: 4,
          }}
        >
          {manageMode ? '退出管理' : '管理'}
        </button>
      </div>
      <ScrollArea
        className="flex-1 px-2 pb-2"
        onScroll={(e) => {
          // 无限滚动（契约 D8-4）：接近底部触发加载更多
          const el = e.currentTarget
          if (el.scrollHeight - el.scrollTop - el.clientHeight < 120) {
            onLoadMore?.()
          }
        }}
      >
        {filtered.length === 0 ? (
          <div style={{ padding: '16px 10px', color: 'var(--sidebar-text-secondary)', fontSize: 12, textAlign: 'center' }}>
            无符合条件的任务
          </div>
        ) : (
          filtered.map((task) => {
            const isActive = task.task_id === selectedId  // CR-03: 契约 D8-4 键名 task_id
            const isChecked = checked.has(task.task_id)
            const active_ = task.status === 'running' || task.status === 'queued'
            return (
              <div
                key={task.task_id}
                onClick={() => (manageMode ? (active_ ? null : toggleCheck(task.task_id)) : onSelect(task.task_id))}
                onMouseEnter={() => setHoveredId(task.task_id)}
                onMouseLeave={() => setHoveredId(null)}
                style={{
                  padding: '8px 10px',
                  borderRadius: 6,
                  marginBottom: 2,
                  cursor: manageMode ? (active_ ? 'not-allowed' : 'pointer') : 'pointer',
                  opacity: manageMode && active_ ? 0.5 : 1,
                  background: isChecked
                    ? 'var(--sidebar-active)'
                    : isActive
                      ? 'var(--sidebar-active)'
                      : hoveredId === task.task_id
                        ? 'var(--sidebar-hover)'
                        : 'transparent',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {manageMode && (
                    <input
                      type="checkbox"
                      checked={isChecked}
                      disabled={active_}
                      onChange={() => toggleCheck(task.task_id)}
                      style={{ accentColor: 'var(--accent)', flexShrink: 0 }}
                    />
                  )}
                  <StatusDot status={task.status} size={6} />
                  <span
                    style={{
                      color: isActive ? 'var(--sidebar-text)' : 'var(--content-fg-secondary)',
                      fontSize: 13,
                      fontWeight: isActive ? 510 : 400,
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      flex: 1,
                    }}
                  >
                    {task.title}
                  </span>
                  {/* 2026-08-27：回放任务徽标（replay_of 指向源任务） */}
                  {task.replay_of && (
                    <span
                      style={{
                        fontSize: 10, padding: '0 6px', borderRadius: 'var(--radius-pill)',
                        background: 'var(--accent-light)', color: 'var(--accent-text)',
                        flexShrink: 0, fontWeight: 510,
                      }}
                    >
                      回放
                    </span>
                  )}
                </div>
                {/* 2026-08-27：操作按钮（重试/重放/清理）统一移到此行、紧挨时间——
                    「时间 + 操作」一组视觉，第一行只保留标题（用户反馈：旧版
                    按钮散在标题行/行末，根本看不见） */}
                <div style={{ color: 'var(--sidebar-text-secondary)', fontSize: 11, marginTop: 4, paddingLeft: 14, display: 'flex', alignItems: 'center', gap: 6 }}>
                  {formatRelativeTime(task.created_at)}
                  <span style={{ flex: 1 }} />
                  {/* 清理/删除入口 */}
                  {!manageMode && !active_ && (
                    <button
                      title="清理/删除任务"
                      onClick={(e) => {
                        e.stopPropagation()
                        onDeleteTask?.(task)
                      }}
                      style={{
                        border: 'none', background: 'transparent', cursor: 'pointer',
                        color: 'var(--content-fg-tertiary)', padding: 2, flexShrink: 0,
                        display: 'flex', alignItems: 'center',
                      }}
                    >
                      <Icon.Wrench style={{ width: 13, height: 13 }} />
                    </button>
                  )}
                  {/* 失败任务：重试（块 7 定案；H-01 兼容旧词表 failed） */}
                  {(task.status === 'error' || task.status === 'failed') && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        onRetry(task.task_id)
                      }}
                      style={{
                        border: 'none',
                        background: 'var(--status-error-bg)',
                        color: 'var(--status-error)',
                        fontSize: 11,
                        padding: '1px 8px',
                        borderRadius: 4,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                      }}
                    >
                      <Icon.Refresh style={{ width: 10, height: 10 }} />重试
                    </button>
                  )}
                  {/* 已完成任务：重放（2026-08-27 事件级回放；与重试互斥不共存） */}
                  {task.status === 'completed' && (
                    <button
                      title="重放此任务（按压缩节奏重演历史事件）"
                      onClick={(e) => {
                        e.stopPropagation()
                        onReplay?.(task.task_id)
                      }}
                      style={{
                        border: 'none',
                        background: 'var(--accent)',
                        color: 'var(--accent-on)',
                        fontSize: 11,
                        padding: '1px 8px',
                        borderRadius: 4,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                        whiteSpace: 'nowrap',
                      }}
                    >
                      <Icon.Play style={{ width: 9, height: 9 }} />重放
                    </button>
                  )}
                </div>
              </div>
            )
          })
        )}
        {/* 无限滚动底部指示（契约 D8-4） */}
        {filtered.length > 0 && !manageMode && (
          <div style={{ padding: '10px 0 14px', textAlign: 'center', fontSize: 11, color: 'var(--sidebar-text-secondary)' }}>
            {tasks.length < total ? '加载中…' : `共 ${total} 个任务`}
          </div>
        )}
      </ScrollArea>

      {/* 批量删除操作条（管理模式） */}
      {manageMode && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '10px 12px', borderTop: '1px solid var(--sidebar-border)',
        }}>
          <span style={{ fontSize: 12, color: 'var(--sidebar-text-secondary)', flex: 1 }}>
            已选 {checked.size} 个
          </span>
          <Button variant="ghost" size="sm" onClick={exitManage}>取消</Button>
          <Button
            variant="destructive"
            size="sm"
            disabled={checked.size === 0}
            onClick={() => onBatchDelete?.([...checked])}
          >
            删除所选
          </Button>
        </div>
      )}

      {/* 设置入口 */}
      <div style={{ padding: '12px 16px', borderTop: '1px solid var(--sidebar-border)' }}>
        <div
          onClick={onOpenSettings}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            color: 'var(--sidebar-text-secondary)',
            fontSize: 13,
            cursor: 'pointer',
          }}
        >
          <Icon.Settings />
          <span>设置</span>
        </div>
      </div>
    </aside>
  )
}
