import { useEffect, useRef, useState } from 'react'
import { queryKey, sidebarIdentity } from '@/hooks/useSidebarIdentity'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Icon } from '@/components/icons'
import { StatusDot, STATUS_LABELS } from '@/components/status'

/* 左栏宽度（可拖拽 200-400px，默认 305px） */
const SIDEBAR_MIN_W = 200
const SIDEBAR_MAX_W = 400

const dateOptions = { year: 'numeric', month: '2-digit', day: '2-digit' }
const queryDate = new Intl.DateTimeFormat('zh-CN', dateOptions)
const fullQueryTime = new Intl.DateTimeFormat('zh-CN', {
  ...dateOptions, hour: '2-digit', minute: '2-digit', hour12: false,
})

function formatQueryTime(iso, now) {
  if (!iso) return null
  const date = new Date(iso)
  const timestamp = date.getTime()
  if (!Number.isFinite(timestamp)) return null

  const minutes = Math.floor((now - timestamp) / 60_000)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  let label
  if (minutes < 1) label = '刚刚'
  else if (minutes < 60) label = `${minutes} 分钟前`
  else if (hours < 24) label = `${hours} 小时前`
  else if (days < 30) label = `${days} 天前`
  else label = queryDate.format(date)

  return { label, exact: fullQueryTime.format(date) }
}

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '进行中' },
  { key: 'attention', label: '待处理' },
  { key: 'completed', label: '已完成' },
  { key: 'error', label: '失败' },
]

const MODES = [
  { key: 'user', label: '我的查询', title: '用户真实查询（含回放任务）' },
  { key: 'sample', label: '演示样例', title: '精选真实案例：即时体验或回放' },
]

export default function Sidebar({
  playbackActive,
  currentPresentation,
  demos = [],
  tasks = [],
  loadingTasks = false,
  total = 0,
  selectedId,
  onSelect,
  onNew,
  onCollapse,
  onReplay,
  onOpenHelp,
  onOpenSettings,
  onLoadMore,
  filter = 'all',
  onFilterChange,
  onDeleteTask,
  onBatchDelete,
  mode = 'user',
  onModeChange,
}) {
  const [hoveredId, setHoveredId] = useState(null)
  const [sampleSearch, setSampleSearch] = useState('')
  const [manageMode, setManageMode] = useState(false)
  const [checked, setChecked] = useState(() => new Set())
  const [width, setWidth] = useState(288)
  const [now, setNow] = useState(Date.now)
  const dragRef = useRef(null)

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000)
    return () => window.clearInterval(timer)
  }, [])

  // 拖拽宽度调节
  const startDrag = (e) => {
    e.preventDefault()
    dragRef.current = { startX: e.clientX, startW: width }
    const onMove = (ev) => {
      if (!dragRef.current) return
      const next = Math.min(
        SIDEBAR_MAX_W,
        Math.max(SIDEBAR_MIN_W, dragRef.current.startW + (ev.clientX - dragRef.current.startX))
      )
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

  // 区分用户查询与演示样例
  const sourceRows = mode === 'sample' ? demos : tasks
  const activeIdentity = !playbackActive && sidebarIdentity(currentPresentation)

  // 演示样例前端搜索过滤
  const filteredRows =
    mode === 'sample' && sampleSearch.trim()
      ? demos.filter((d) =>
          [d.title, d.name, d.query, d.summary]
            .filter(Boolean)
            .some((text) => text.toLowerCase().includes(sampleSearch.trim().toLowerCase()))
        )
      : sourceRows

  return (
    <aside
      className="glass sidebar-v1"
      aria-label="任务导航"
      style={{
        width,
        minWidth: width,
        borderRight: '1px solid var(--surface-border)',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        background: 'var(--sidebar-bg)',
      }}
    >
      {/* 拖拽手柄：右边缘 5px */}
      <div
        onMouseDown={startDrag}
        style={{
          position: 'absolute',
          right: 0,
          top: 0,
          bottom: 0,
          width: 5,
          cursor: 'col-resize',
          zIndex: 20,
          background: 'transparent',
        }}
        title="拖动调整侧栏宽度"
      />

      {/* 顶部按钮栏：新建查询 + 收起侧栏 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '14px 22px 8px 22px' }}>
        <Button
          variant="sidebar"
          className="flex-1 justify-start gap-2 text-sm active-press"
          onClick={onNew}
          title={mode === 'sample' ? '回到样例库' : '清空输入，开启新查询'}
          style={{
            background: 'var(--surface-bg)',
            color: 'var(--content-fg)',
            border: '1px solid color-mix(in srgb, var(--accent) 55%, transparent)',
            borderRadius: 10,
            fontWeight: 500,
            padding: '7px 12px',
            boxShadow:
              '0 0 0 2px color-mix(in srgb, var(--accent) 10%, transparent), 0 2px 8px color-mix(in srgb, var(--accent) 12%, transparent)',
            transition: 'all 0.18s var(--motion-ease)',
          }}
        >
          {mode === 'sample' ? (
            <Icon.Sparkle style={{ color: 'var(--accent)', width: 15, height: 15, flexShrink: 0 }} />
          ) : (
            <Icon.Plus style={{ color: 'var(--accent)', width: 15, height: 15, flexShrink: 0 }} />
          )}
          <span>{mode === 'sample' ? '全部样例' : '新建科研查询'}</span>
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onCollapse}
          title="收起侧边栏"
          style={{ borderRadius: 8, color: 'var(--content-fg-secondary)' }}
        >
          <Icon.ChevronLeft style={{ width: 16, height: 16 }} />
        </Button>
      </div>

      {/* 我的查询 / 演示样例 胶囊双模式切换栏 */}
      <div style={{ display: 'flex', gap: 3, padding: '0 22px 8px' }}>
        {MODES.map((m) => {
          const isActive = mode === m.key
          return (
            <button
              key={m.key}
              onClick={() => {
                exitManage()
                onModeChange?.(m.key)
              }}
              title={m.title}
              className="active-press"
              style={{
                flex: 1,
                padding: '6px 0',
                fontSize: 12,
                borderRadius: 8,
                border: 'none',
                cursor: 'pointer',
                background: isActive ? 'var(--accent-light)' : 'transparent',
                color: isActive ? 'var(--accent-text)' : 'var(--sidebar-text-secondary)',
                fontWeight: isActive ? 550 : 400,
                transition: 'background-color 0.18s var(--motion-ease), color 0.18s var(--motion-ease)',
              }}
            >
              {m.label}
            </button>
          )
        })}
      </div>

      {/* 状态筛选 Chips（我的查询模式下） */}
      {mode === 'user' && (
        <div style={{ display: 'flex', gap: 3, padding: '0 22px 8px', overflowX: 'auto' }}>
          {FILTERS.map((f) => {
            const isActive = filter === f.key
            return (
              <button
                key={f.key}
                onClick={() => onFilterChange?.(f.key)}
                className="active-press"
                style={{
                  flex: 1,
                  padding: '4px 2px',
                  fontSize: 11.5,
                  borderRadius: 6,
                  border: 'none',
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                  background: isActive ? 'var(--accent-light)' : 'transparent',
                  color: isActive ? 'var(--accent-text)' : 'var(--sidebar-text-secondary)',
                  fontWeight: isActive ? 550 : 400,
                  transition: 'background-color 0.15s ease, color 0.15s ease',
                }}
              >
                {f.label}
              </button>
            )
          })}
        </div>
      )}

      {/* 演示样例模式下的即时搜索框 */}
      {mode === 'sample' && (
        <div style={{ padding: '0 22px 8px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              background: 'var(--surface-bg)',
              border: '1px solid var(--surface-border)',
              borderRadius: 8,
              padding: '5px 10px',
            }}
          >
            <Icon.Search style={{ width: 13, height: 13, color: 'var(--content-fg-tertiary)' }} />
            <input
              aria-label="搜索演示样例"
              placeholder="搜索天体或性质…"
              value={sampleSearch}
              onChange={(e) => setSampleSearch(e.target.value)}
              style={{
                border: 'none',
                background: 'transparent',
                outline: 'none',
                fontSize: 12,
                color: 'var(--content-fg)',
                width: '100%',
              }}
            />
            {sampleSearch && (
              <button
                onClick={() => setSampleSearch('')}
                style={{
                  border: 'none',
                  background: 'transparent',
                  cursor: 'pointer',
                  color: 'var(--content-fg-tertiary)',
                  padding: 0,
                }}
              >
                ✕
              </button>
            )}
          </div>
        </div>
      )}

      {/* 任务区小节头与管理切换 */}
      <div
        style={{
          padding: '4px 20px 6px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid var(--surface-border-subtle)',
        }}
      >
        <span
          style={{
            color: 'var(--sidebar-text-secondary)',
            fontSize: 11,
            fontWeight: 550,
            letterSpacing: '0.04em',
          }}
        >
          {mode === 'sample' ? `标杆案例 (${filteredRows.length})` : `历史查询 (${total})`}
        </span>
        {mode === 'user' && (
          <button
            onClick={() => (manageMode ? exitManage() : setManageMode(true))}
            className="text-link"
            style={{
              fontSize: 11,
              color: manageMode ? 'var(--status-error)' : 'var(--accent-text)',
              padding: '2px 4px',
            }}
          >
            {manageMode ? '退出管理' : '批量管理'}
          </button>
        )}
      </div>

      {/* 批量管理操作面板 */}
      {manageMode && (
        <div
          style={{
            padding: '8px 14px',
            background: 'var(--surface-secondary)',
            borderBottom: '1px solid var(--surface-border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
          }}
        >
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={filteredRows.length > 0 && filteredRows.every((t) => checked.has(t.task_id))}
              onChange={(e) =>
                setChecked(new Set(e.target.checked ? filteredRows.map((t) => t.task_id) : []))
              }
              style={{ accentColor: 'var(--accent)' }}
            />
            <span>全选</span>
          </label>
          <span style={{ fontSize: 11, color: 'var(--content-fg-secondary)' }}>已选 {checked.size} 项</span>
          <Button
            variant="outline"
            size="sm"
            disabled={!checked.size}
            onClick={() => onBatchDelete?.([...checked])}
            style={{ fontSize: 11, padding: '2px 8px', height: 24 }}
          >
            删除所选
          </Button>
        </div>
      )}

      {/* 任务列表滚动区 */}
      <ScrollArea
        className="sidebar-task-scroll flex-1"
        style={{ padding: '6px 8px 12px' }}
        onScroll={(e) => {
          const el = e.currentTarget
          if (el.scrollHeight - el.scrollTop - el.clientHeight < 100) {
            onLoadMore?.()
          }
        }}
      >
        {filteredRows.length === 0 ? (
          <div
            style={{
              padding: '28px 12px',
              color: 'var(--sidebar-text-secondary)',
              fontSize: 12,
              textAlign: 'center',
              lineHeight: 1.8,
            }}
          >
            {mode === 'sample'
              ? '无匹配演示样例'
              : loadingTasks
              ? '正在读取查询列表…'
              : '当前筛选下暂无科研任务'}
          </div>        ) : (
          filteredRows.map((t) => {
            const isSelected = t.task_id === selectedId
            const isChecked = checked.has(t.task_id)
            const meta =
              mode === 'user' &&
              ((activeIdentity && t.task_id === currentPresentation?.task_id && activeIdentity) ||
                t.display_identity)
            const title =
              meta && (!meta.question || t.title === meta.question) ? meta.target : t.title || t.query
            const isSample = mode === 'sample' && !t.replay_of
            const queryTime = formatQueryTime(t.created_at, now)
            const statusLabel = !isSample && (STATUS_LABELS[t.status] || t.status)

            return (
              <div
                key={t.task_id}
                data-task-id={t.task_id}
                data-query-ref={queryKey?.(t) || undefined}
                className={`task-list-row ${isSample ? 'sample-item' : ''} ${isSelected ? 'selected' : ''}`}
                onClick={() => {
                  if (manageMode) toggleCheck(t.task_id)
                  else onSelect?.(t.task_id)
                }}
                onMouseEnter={() => setHoveredId(t.task_id)}
                onMouseLeave={() => setHoveredId(null)}
                style={{
                  position: 'relative',
                  padding: isSample ? '9px 12px' : '8px 10px 8px 12px',
                  borderRadius: 8,
                  marginBottom: 3,
                  cursor: 'pointer',
                  background: isSelected
                    ? 'var(--sidebar-active)'
                    : hoveredId === t.task_id
                    ? 'var(--sidebar-hover)'
                    : 'transparent',
                  transition: 'background 0.15s ease',
                  borderLeft: isSelected
                    ? '3px solid var(--accent)'
                    : '3px solid transparent',
                  minHeight: isSample ? 38 : 50,
                  boxSizing: 'border-box',
                }}
              >
                <div className="task-list-row-body">
                  <div className="task-list-leading">
                    {manageMode && (
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => toggleCheck(t.task_id)}
                        onClick={(e) => e.stopPropagation()}
                        style={{ accentColor: 'var(--accent)' }}
                      />
                    )}
                    <StatusDot status={t.status} size={6} />
                  </div>
                  <div className="task-list-main">
                    <div className="task-list-heading">
                      <span className="task-item-title" title={meta?.question || t.title || t.query}>
                        {isSample ? (t.name || t.title || t.query) : title}
                        {meta?.properties && (
                          <span className="task-item-properties"> · {meta.properties}</span>
                        )}
                      </span>

                      {t.replay_of && <span className="task-list-replay-tag">回放</span>}

                      {!isSample && !manageMode && hoveredId === t.task_id && (
                        <div className="task-list-actions" onClick={(e) => e.stopPropagation()}>
                          {['completed', 'cancelled', 'error', 'failed'].includes(t.status) && (
                            <button
                              type="button"
                              title="只读回放"
                              aria-label={`回放：${t.title}`}
                              onClick={() => onReplay?.(t.task_id)}
                            >
                              <Icon.Play style={{ width: 12, height: 12 }} />
                            </button>
                          )}
                          <button
                            type="button"
                            title="管理或删除"
                            aria-label={`管理：${t.title}`}
                            onClick={() => onDeleteTask?.(t)}
                          >
                            <Icon.Ellipsis style={{ width: 13, height: 13 }} />
                          </button>
                        </div>
                      )}
                    </div>

                    {(queryTime || statusLabel) && (
                      <div className="task-list-meta">
                        {queryTime && <time dateTime={t.created_at} title={queryTime.exact}>{queryTime.label}</time>}
                        {queryTime && statusLabel && <span aria-hidden="true">·</span>}
                        {statusLabel && <span className="task-list-state" title={statusLabel}>{statusLabel}</span>}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )
          })
        )}

        {/* 我的查询模式加载更多按钮 */}
        {mode === 'user' && filteredRows.length < total && (
          <div style={{ padding: '8px 4px 4px' }}>
            <Button variant="outline" size="sm" className="w-full text-xs" onClick={onLoadMore}>
              加载更多任务…
            </Button>
          </div>
        )}
      </ScrollArea>

      {/* 侧栏底部：系统设置与帮助 */}
      <div
        style={{
          borderTop: '1px solid var(--surface-border)',
          padding: '10px 18px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--sidebar-bg)',
        }}
      >
        <Button
          variant="ghost"
          size="sm"
          onClick={onOpenSettings}
          className="gap-1.5 text-xs"
          style={{ color: 'var(--content-fg-secondary)', borderRadius: 7 }}
        >
          <Icon.Settings style={{ width: 13, height: 13 }} />
          <span>系统设置</span>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onOpenHelp}
          className="gap-1.5 text-xs"
          style={{ color: 'var(--content-fg-secondary)', borderRadius: 7 }}
        >
          <Icon.HelpCircle style={{ width: 13, height: 13 }} />
          <span>使用帮助</span>
        </Button>
      </div>
    </aside>
  )
}
