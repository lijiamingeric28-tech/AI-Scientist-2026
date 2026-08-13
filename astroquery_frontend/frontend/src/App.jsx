import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { StatusBadge } from '@/components/status'
import { ToastProvider, useToast } from '@/components/ui/toast'
import Sidebar from '@/components/layout/Sidebar'
import DetailPanel from '@/components/layout/DetailPanel'
import ChatView from '@/components/chat/ChatView'
import WorkflowView from '@/components/workflow/WorkflowView'
import SettingsDialog from '@/components/settings/SettingsDialog'
import { listTasks as apiListTasks, retryTask as apiRetryTask, cancelTask as apiCancelTask } from '@/services/api'
import { usePipeline } from '@/hooks/usePipeline'
import { useTheme } from '@/hooks/useTheme'
import { useMediaQuery } from '@/hooks/useMediaQuery'

/* ===== 主应用：三栏布局（块 1 定案）
 * 侧边栏 240px（可折叠） + 主区（工具栏 + 对话/工作流视图） + 右侧详情面板（可折叠）
 * pipeline 状态（SSE 事件流）上提到本层：对话/工作流两个视图共享同一份实时状态，
 * 切换视图不丢进度、不重建事件流连接。
 *
 * 响应式：<1024px 侧边栏自动折叠；<1280px 详情面板改覆盖式抽屉（DetailPanel 内处理）。
 * 主题：useTheme 切 html[data-theme]，工具栏提供明暗切换。
 */

function AppInner() {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [detailOpen, setDetailOpen] = useState(true)
  const [selectedId, setSelectedId] = useState(null)
  const [filter, setFilter] = useState('all')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [logOpen, setLogOpen] = useState(false)
  const [view, setView] = useState('chat')  // 主区视图：chat 对话 | workflow 工作流
  // 工作流 → 对话联动：{id, seq}，seq 递增保证重复点击同阶段也触发定位
  const [focusStage, setFocusStage] = useState(null)
  // 洞察报告入口 → 右侧详情面板洞察 tab：{tab, seq}
  const [detailTabReq, setDetailTabReq] = useState(null)
  // 任务列表（契约 D8-4：GET /api/tasks 分页，无限滚动）
  const [tasks, setTasks] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [cancelling, setCancelling] = useState(false)  // 取消任务请求进行中
  const { toast } = useToast()
  const { theme, toggleTheme } = useTheme()
  const isNarrow = useMediaQuery('(max-width: 1023px)')

  const selected = tasks.find((t) => t.task_id === selectedId) || null  // CR-03: 契约 D8-4 键名 task_id

  // 窄屏自动折叠侧边栏（回到宽屏不强制展开，尊重用户手动收起）
  useEffect(() => {
    if (isNarrow) setSidebarOpen(false)
    else setSidebarOpen(true)
  }, [isNarrow])

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

  // 取消运行中任务（契约 D2-3：POST /tasks/{id}/cancel）
  const handleCancel = async () => {
    if (!selected || cancelling) return
    setCancelling(true)
    try {
      await apiCancelTask(selected.task_id)
      toast('已发送取消请求', 'info')
      await loadTasks(0)
    } catch (err) {
      toast(`取消失败：${err.message}`, 'error')
    } finally {
      setCancelling(false)
    }
  }

  // task_title_ready（契约 D8-2）：SSE 补发标题 → 按 ev.task_id 归属更新列表
  // L-01: 接收完整 payload 而非只透传 title——切换竞态下标题不串台/不丢失
  const handleTaskTitle = (ev) => {
    setTasks((prev) => prev.map((t) => (t.task_id === ev.task_id ? { ...t, title: ev.title } : t)))
  }

  // 工作流视图"在对话中查看" → 切对话视图并定位到对应阶段卡
  const handleShowStageInChat = (stageId) => {
    setView('chat')
    setFocusStage((prev) => ({ id: stageId, seq: (prev?.seq || 0) + 1 }))
  }

  // 洞察卡"查看完整报告" → 打开右侧详情面板并切到洞察 tab
  const handleOpenInsights = () => {
    setDetailOpen(true)
    setDetailTabReq((prev) => ({ tab: 'insights', seq: (prev?.seq || 0) + 1 }))
  }

  // pipeline 状态上提：SSE 事件流驱动的实时阶段状态，对话/工作流视图共享。
  // （放在各 handler 定义之后，避免 const 暂时性死区）
  const pipeline = usePipeline(selected, { onTaskDone: handleTaskDone, onTaskTitle: handleTaskTitle })

  return (
    <div className="theme-transition" style={{ display: 'flex', height: '100vh', width: '100%', overflow: 'hidden' }}>
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
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, background: 'var(--bg-ambient), var(--content-bg)' }}>
        {/* 工具栏：任务标题 + 状态徽标（块 1 B2）——玻璃顶栏 */}
        <header
          className="glass"
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '10px 20px',
            borderBottom: '1px solid var(--glass-border)',
            gap: 12,
            flexShrink: 0,
            zIndex: 20,
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
          {/* 取消任务：仅活跃任务（排队/运行/挂起）显示 */}
          {selected && ['queued', 'running', 'pending'].includes(selected.status) && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleCancel}
              disabled={cancelling}
              style={{ color: 'var(--status-error)', borderColor: 'color-mix(in srgb, var(--status-error) 35%, transparent)' }}
            >
              <Icon.Stop />
              {cancelling ? '取消中…' : '取消任务'}
            </Button>
          )}
          {/* 视图切换：对话 / 工作流（pill 分段控件，选中 = 墨色填充） */}
          <div className="glass-pill" style={{ display: 'flex', gap: 2, padding: 3 }}>
            {[
              { key: 'chat', label: '对话', icon: <Icon.MessageSquare /> },
              { key: 'workflow', label: '工作流', icon: <Icon.Network /> },
            ].map((v) => (
              <button
                key={v.key}
                onClick={() => setView(v.key)}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  border: 'none', cursor: 'pointer',
                  padding: '5px 14px', fontSize: 12, fontWeight: 510,
                  borderRadius: 'var(--radius-pill)',
                  background: view === v.key ? 'var(--accent)' : 'transparent',
                  color: view === v.key ? 'var(--accent-on)' : 'var(--content-fg-secondary)',
                  transition: 'background .15s, color .15s',
                }}
              >
                {v.icon}{v.label}
              </button>
            ))}
          </div>
          <Button variant="ghost" size="icon" onClick={toggleTheme} title={theme === 'dark' ? '切换到浅色模式' : '切换到深色模式'}>
            {theme === 'dark' ? <Icon.Sun /> : <Icon.Moon />}
          </Button>
          <Button variant="ghost" size="icon" onClick={() => setLogOpen(!logOpen)} title={logOpen ? '收起日志' : '查看日志'}>
            <Icon.FileText style={{ color: logOpen ? 'var(--accent-text)' : undefined }} />
          </Button>
          <Button variant="ghost" size="icon" onClick={() => setDetailOpen(!detailOpen)}>
            <Icon.PanelRight />
          </Button>
        </header>

        {/* 主区内容：对话视图 / 工作流视图（共享同一份 pipeline 实时状态）
            key 触发进场淡入，弱化视图切换的瞬切感 */}
        {view === 'chat' ? (
          <div key="chat" className="animate-fade-in" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            <ChatView
              task={selected}
              pipeline={pipeline}
              onNewTask={handleNewTask}
              logOpen={logOpen}
              onToggleLog={() => setLogOpen(!logOpen)}
              focusStage={focusStage}
              onOpenInsights={handleOpenInsights}
            />
          </div>
        ) : (
          <div key="workflow" className="animate-fade-in" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            <WorkflowView task={selected} pipeline={pipeline} onGoChat={() => setView('chat')} onShowStageInChat={handleShowStageInChat} />
          </div>
        )}
      </main>

      {/* ===== 右侧详情面板 ===== */}
      <DetailPanel open={detailOpen} onClose={() => setDetailOpen(false)} task={selected} pipeline={pipeline} requestedTab={detailTabReq} />
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
