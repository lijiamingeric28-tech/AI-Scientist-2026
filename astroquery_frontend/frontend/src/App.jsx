import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { StatusBadge } from '@/components/status'
import { ToastProvider, useToast } from '@/components/ui/toast'
import Sidebar from '@/components/layout/Sidebar'
import DetailPanel from '@/components/layout/DetailPanel'
import ChatView from '@/components/chat/ChatView'
import SettingsDialog from '@/components/settings/SettingsDialog'
import { listTasks as apiListTasks, retryTask as apiRetryTask } from '@/services/api'

/* ===== 主应用：三栏布局（块 1 定案）
 * 侧边栏 240px（可折叠） + 主区（工具栏 + 对话视图） + 右侧详情面板 380px（可折叠）
 * 当前进度：布局骨架 + 侧边栏；对话视图为占位（逐卡填充中）
 */

function AppInner() {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [detailOpen, setDetailOpen] = useState(true)
  const [selectedId, setSelectedId] = useState(null)
  const [filter, setFilter] = useState('all')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [logOpen, setLogOpen] = useState(false)
  // 任务列表（契约 D8-4：GET /api/tasks 分页，无限滚动）
  const [tasks, setTasks] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const { toast } = useToast()

  const selected = tasks.find((t) => t.task_id === selectedId) || null  // CR-03: 契约 D8-4 键名 task_id

  const loadTasks = async (o = 0, append = false) => {
    try {
      const data = await apiListTasks(50, o, filter === 'all' ? undefined : filter)
      setTasks((prev) => (append ? [...prev, ...data.items] : data.items))
      setTotal(data.total)
      setOffset(o + data.items.length)
    } catch (err) {
      toast(`任务列表加载失败：${err.message}`, 'error')
    }
  }

  useEffect(() => {
    loadTasks(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter])

  const handleLoadMore = async () => {
    if (loadingMore || offset >= total) return
    setLoadingMore(true)
    await loadTasks(offset, true)
    setLoadingMore(false)
  }

  const handleTaskDone = async () => {
    // 任务完成 → 刷新列表（状态徽标联动）
    await loadTasks(0)
  }

  const handleNew = () => {
    setSelectedId(null)
  }

  const handleSelect = (id) => {
    setSelectedId(id)
    if (!detailOpen) setDetailOpen(true)
  }

  // 新任务创建成功（ChatView submitQuery 回调）
  const handleNewTask = async (taskId) => {
    await loadTasks(0)
    setSelectedId(taskId)
  }

  // 失败任务重试（契约 D2-4：POST retry 重建任务）
  const handleRetry = async (id) => {
    try {
      const r = await apiRetryTask(id)
      toast('正在重试任务', 'info')
      await loadTasks(0)
      setSelectedId(r.task_id)
    } catch (err) {
      toast(`重试失败：${err.message}`, 'error')
    }
  }

  // task_title_ready（契约 D8-2）：SSE 补发标题 → 按 ev.task_id 归属更新列表
  // L-01: 接收完整 payload 而非只透传 title——切换竞态下标题不串台/不丢失
  const handleTaskTitle = (ev) => {
    setTasks((prev) => prev.map((t) => (t.task_id === ev.task_id ? { ...t, title: ev.title } : t)))
  }

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100%', overflow: 'hidden' }}>
      {/* 设置对话框 */}
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      {/* ===== 侧边栏 ===== */}
      {sidebarOpen && (
        <Sidebar
          tasks={tasks}
          total={total}
          selectedId={selectedId}
          onSelect={handleSelect}
          onNew={handleNew}
          onCollapse={() => setSidebarOpen(false)}
          onRetry={handleRetry}
          onOpenSettings={() => setSettingsOpen(true)}
          onLoadMore={handleLoadMore}
          filter={filter}
          onFilterChange={setFilter}
        />
      )}

      {/* ===== 主内容区 ===== */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, background: 'var(--content-bg)' }}>
        {/* 工具栏：任务标题 + 状态徽标（块 1 B2） */}
        <header
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '10px 20px',
            background: 'var(--surface-bg)',
            borderBottom: '1px solid var(--surface-border)',
            gap: 12,
            flexShrink: 0,
          }}
        >
          {!sidebarOpen && (
            <Button variant="ghost" size="icon" onClick={() => setSidebarOpen(true)}>
              <Icon.Menu />
            </Button>
          )}
          <h1 style={{ fontSize: 15, fontWeight: 510, color: 'var(--content-fg)', flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {selected ? selected.title : '新建任务'}
          </h1>
          {selected && <StatusBadge status={selected.status} />}
          <Button variant="ghost" size="icon" onClick={() => setLogOpen(!logOpen)} title={logOpen ? '收起日志' : '查看日志'}>
            <Icon.FileText style={{ color: logOpen ? 'var(--accent-text)' : undefined }} />
          </Button>
          <Button variant="ghost" size="icon" onClick={() => setDetailOpen(!detailOpen)}>
            <Icon.PanelRight />
          </Button>
        </header>

        {/* 主区内容：对话视图 */}
        <ChatView
          task={selected}
          onTaskDone={handleTaskDone}
          onNewTask={handleNewTask}
          onTaskTitle={handleTaskTitle}
          logOpen={logOpen}
          onToggleLog={() => setLogOpen(!logOpen)}
        />
      </main>

      {/* ===== 右侧详情面板 ===== */}
      <DetailPanel open={detailOpen} onClose={() => setDetailOpen(false)} task={selected} />
    </div>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <AppInner />
    </ToastProvider>
  )
}
