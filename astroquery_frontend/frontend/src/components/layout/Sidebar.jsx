import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Icon } from '@/components/icons'
import { StatusDot } from '@/components/status'
// 演示样例清单（置顶 3 条与画廊顺序同源；scripts/rebuild_sample_pack.py 生成）
import SAMPLE_MANIFEST from '@/data/samples.json'

/* 左栏宽度（可拖拽 200-400px，默认 240；2026-08-27 布局减负） */
const SIDEBAR_MIN_W = 200
const SIDEBAR_MAX_W = 400

/* 标题字符串截断（2026-09-02）：默认宽度 305px 下纯 flex ellipsis 要等到 ~19 字
 * 才折叠，右侧「回放」徽标/控件被挤出裁切。更早截断到 16 字（含省略号），
 * 徽标有完整空间；CSS ellipsis 仍作兜底（窄屏/拖宽时双保险）。 */
function fitTitle(t) {
  if (!t) return ''
  return t.length > 16 ? `${t.slice(0, 16)}…` : t
}

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

// 2026-09-02：我的查询 / 演示样例 双模式（侧栏顶部切换条）
const MODES = [
  { key: 'user', label: '我的查询', title: '用户真实查询（含回放产生的任务）' },
  { key: 'sample', label: '演示样例', title: '内嵌精选样例：浏览真实过程或回放' },
]

export default function Sidebar({ tasks, total, selectedId, onSelect, onNew, onCollapse, onRetry, onReplay, onOpenSettings, onLoadMore, filter, onFilterChange, onDeleteTask, onBatchDelete, mode = 'user', onModeChange, samplesExpanded = false, onToggleSamples }) {
  const [hoveredId, setHoveredId] = useState(null)
  // 2026-08-24: 批量删除管理模式
  const [manageMode, setManageMode] = useState(false)
  const [checked, setChecked] = useState(() => new Set())
  // 2026-08-27: 左栏可拖拽调宽（200-400px）；默认 320（用户反馈 300 仍略窄，再宽一点点）
  // 2026-09-02: 默认宽 305（345 → 325 → 305，用户要求主内容区再宽 20px；拖拽手柄可再调）
  const [width, setWidth] = useState(305)
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
  // 2026-09-02：演示样例模式忽略状态筛选（全部 completed；筛选值是『我的查询』残留）
  const filtered = mode === 'sample'
    ? tasks
    : filter === 'all'
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

  /* ── 演示样例列表结构（2026-09-02 用户定稿）─────────────────────
   * 折叠默认：置顶 3 条（M45 09-01 旗舰 / 参宿四 / M87，与画廊名一一对应）
   * 展开后：17 条本体按画廊定稿序；回放副本独立小节常驻底部（可选中可删）
   * 本体行 = manifest 顺序对齐（不再按 created_at 混排） */
  const SAMPLE_PINS = ['昴星团 M45（09-01 版）', '参宿四', 'M87']
  const manifestMeta = new Map()   // task_id → {index, name}
  ;(SAMPLE_MANIFEST.samples || []).forEach((s, i) => manifestMeta.set(s.task_id, { index: i, name: s.name }))
  const pinRanks = new Map()
  SAMPLE_PINS.forEach((nm, i) => {
    for (const [id, meta] of manifestMeta) {
      if (meta.name === nm && !pinRanks.has(id)) { pinRanks.set(id, i); break }
    }
  })
  const byManifest = (a, b) => (manifestMeta.get(a.task_id)?.index ?? 999) - (manifestMeta.get(b.task_id)?.index ?? 999)
  const byPin = (a, b) => (pinRanks.get(a.task_id) ?? 99) - (pinRanks.get(b.task_id) ?? 99)

  /* 2026-09-02 v2（用户重设计）：左侧恒为「置顶 3 条 + 展开/收起按钮 + 回放副本」，
   * 展开只作用右侧主区画廊——左侧不列出全部 17 条 */
  const displayRows = []
  if (mode === 'sample') {
    const bodies = []
    const copies = []
    filtered.forEach((t) => (t.replay_of ? copies : bodies).push(t))
    bodies.sort(byManifest)
    copies.sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
    const visible = bodies.filter((t) => pinRanks.has(t.task_id)).sort(byPin)
    if (visible.length) {
      displayRows.push({ hdr: '置顶样例' })
      visible.forEach((t) => displayRows.push({ task: t }))
    }
    displayRows.push({ expand: true })  // 「展开全部 / 收起画廊」（原提示语位置）
    if (copies.length) {
      displayRows.push({ hdr: `回放副本 (${copies.length})` })
      copies.forEach((t) => displayRows.push({ task: t }))
    }
  } else {
    filtered.forEach((t) => displayRows.push({ task: t }))
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
      {/* 新建任务 + 收起（演示样例模式：按钮变“回到全部样例”，点按清空选中回画廊） */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '16px 12px 8px 16px' }}>
        {/* 2026-09-02 用户截图样式：白底卡片 + 外围绿色描边悬浮（光晕阴影）效果 */}
        <Button
          variant="sidebar"
          className="flex-1 justify-start gap-2 text-sm"
          onClick={onNew}
          title={mode === 'sample' ? '回到样例画廊' : '清空选中、聚焦输入框，开始新查询'}
          style={{
            background: 'var(--glass-bg)',
            color: 'var(--content-fg)',
            border: '1px solid color-mix(in srgb, var(--accent) 55%, transparent)',
            borderRadius: 10,
            fontWeight: 450,
            boxShadow:
              '0 0 0 3px color-mix(in srgb, var(--accent) 10%, transparent), 0 2px 8px color-mix(in srgb, var(--accent) 16%, transparent)',
          }}
        >
          {mode === 'sample' ? (
            <Icon.Sparkle style={{ color: 'var(--accent)', width: 14, height: 14 }} />
          ) : (
            <Icon.Plus style={{ color: 'var(--accent)' }} />
          )}
          <span>{mode === 'sample' ? '回到全部样例' : '新建提取任务'}</span>
        </Button>
        <Button variant="ghost" size="icon" onClick={onCollapse} title="收起侧边栏">
          <Icon.ChevronLeft />
        </Button>
      </div>

      {/* 2026-09-02：我的查询 / 演示样例 分段切换条 */}
      <div style={{ display: 'flex', gap: 2, padding: '0 12px 8px' }}>
        {MODES.map((m) => (
          <button
            key={m.key}
            onClick={() => onModeChange?.(m.key)}
            title={m.title}
            style={{
              flex: 1,
              padding: '5px 0',
              fontSize: 12,
              borderRadius: 6,
              border: 'none',
              cursor: 'pointer',
              background: mode === m.key ? 'var(--accent-light)' : 'transparent',
              color: mode === m.key ? 'var(--accent-text)' : 'var(--sidebar-text-secondary)',
              fontWeight: mode === m.key ? 510 : 400,
            }}
          >
            {m.label}
          </button>
        ))}
      </div>

      {/* 状态筛选（仅我的查询模式；样例全部为已完成任务，筛选无意义） */}
      {mode === 'user' && (
        <div style={{ display: 'flex', gap: 2, padding: '0 12px 8px' }}>
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => onFilterChange(f.key)}
              style={{
                flex: 1,
                padding: '5px 0',
                fontSize: 12,
                borderRadius: 6,
                border: 'none',
                cursor: 'pointer',
                // 用户重设计：选中筛选 chip 淡绿底绿字
                background: filter === f.key ? 'var(--accent-light)' : 'transparent',
                color: filter === f.key ? 'var(--accent-text)' : 'var(--sidebar-text-secondary)',
                fontWeight: filter === f.key ? 510 : 400,
              }}
            >
              {f.label}
            </button>
          ))}
        </div>
      )}

      {/* 任务区标题（演示样例模式：标题+说明，无管理模式） */}
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
          {mode === 'sample' ? '演示样例' : '历史任务'}
        </span>
        {mode === 'user' && (
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
        )}
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
        {displayRows.length === 0 ? (
          <div style={{ padding: '16px 10px', color: 'var(--sidebar-text-secondary)', fontSize: 12, textAlign: 'center', lineHeight: 1.7 }}>
            {mode === 'sample'
              ? '暂无演示样例\n（启动服务时自动从 sample_pack/ 导入）'
              : '无符合条件的任务'}
          </div>
        ) : (
          displayRows.map((item) => {
            // 小节头（置顶样例 / 回放副本 (N)）
            if (item.hdr) {
              return (
                <div
                  key={`h-${item.hdr}`}
                  style={{
                    padding: '9px 10px 3px',
                    fontSize: 10.5,
                    color: 'var(--content-fg-tertiary)',
                    letterSpacing: '0.05em',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {item.hdr}
                </div>
              )
            }
            // 展开/收起按钮（置顶 3 条之后；只控制右侧主区画廊）
            if (item.expand) {
              return (
                <button
                  key="expand-samples"
                  onClick={onToggleSamples}
                  title={samplesExpanded ? '收起画廊' : '展开全部 17 条样例（主区显示画廊）'}
                  style={{
                    display: 'block',
                    width: '100%',
                    margin: '6px 0 2px',
                    padding: '7px 12px',
                    fontSize: 11,
                    fontWeight: 510,
                    borderRadius: 8,
                    border: '1px solid color-mix(in srgb, var(--accent) 45%, transparent)',
                    background: samplesExpanded ? 'var(--accent-light)' : 'transparent',
                    color: samplesExpanded ? 'var(--accent-text)' : 'var(--sidebar-text-secondary)',
                    cursor: 'pointer',
                    textAlign: 'center',
                  }}
                >
                  {samplesExpanded ? '收起画廊' : '展开全部'}
                </button>
              )
            }
            const task = item.task
            const isActive = task.task_id === selectedId  // CR-03: 契约 D8-4 键名 task_id
            const isChecked = checked.has(task.task_id)
            const active_ = task.status === 'running' || task.status === 'queued'
            // 2026-09-02：样例本体（source=sample 且非回放副本）只读——隐藏清理/删除入口；
            // 回放副本（replay_of 非空）是派生演示产物，保留全部管理能力
            const lockedSample = task.source === 'sample' && !task.replay_of
            return (
              <div
                key={task.task_id}
                onClick={() => (manageMode ? (active_ ? null : toggleCheck(task.task_id)) : onSelect(task.task_id))}
                onMouseEnter={() => setHoveredId(task.task_id)}
                onMouseLeave={() => setHoveredId(null)}
                style={{
                  padding: '8px 10px',
                  borderRadius: 8,
                  marginBottom: 2,
                  cursor: manageMode ? (active_ ? 'not-allowed' : 'pointer') : 'pointer',
                  opacity: manageMode && active_ ? 0.5 : 1,
                  // 用户重设计：选中/勾选条目淡绿底 + 左侧绿色圆角竖条
                  background: (isChecked || isActive)
                    ? 'var(--accent-light)'
                    : hoveredId === task.task_id
                      ? 'var(--sidebar-hover)'
                      : 'transparent',
                  boxShadow: (isChecked || isActive)
                    ? 'inset 3px 0 0 0 var(--accent)'
                    : undefined,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {manageMode && (
                    <input
                      type="checkbox"
                      checked={isChecked}
                      disabled={active_}
                      onChange={() => toggleCheck(task.task_id)}
                      onClick={(e) => e.stopPropagation()}  // 阻止冒泡到行 onClick——否则两次翻转抵消，勾选无反应
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
                      minWidth: 0,
                    }}
                  >
                    {fitTitle(task.title)}
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
                {/* 2026-09-01 用户重设计：任务条目「N 条记录 · M 个来源」（完成任务；列表接口轻量统计列） */}
                {task.status === 'completed' && (Number(task.record_count) > 0 || Number(task.source_count) > 0) && (
                  <div style={{ fontSize: 11, color: 'var(--sidebar-text-secondary)', marginTop: 4, paddingLeft: 14 }}>
                    {Number(task.record_count) > 0 && <>{task.record_count} 条记录 · </>}
                    {task.source_count} 个来源
                  </div>
                )}
                {/* 2026-08-27：操作按钮（重试/重放/清理）统一移到此行、紧挨时间——
                    「时间 + 操作」一组视觉，第一行只保留标题（用户反馈：旧版
                    按钮散在标题行/行末，根本看不见） */}
                <div style={{ color: 'var(--sidebar-text-secondary)', fontSize: 11, marginTop: 4, paddingLeft: 14, display: 'flex', alignItems: 'center', gap: 6 }}>
                  {formatRelativeTime(task.created_at)}
                  <span style={{ flex: 1 }} />
                  {/* 清理/删除入口（样例本体只读，不渲染） */}
                  {!manageMode && !active_ && !lockedSample && (
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
