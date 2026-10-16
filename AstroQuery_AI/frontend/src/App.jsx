import { PropertyNamesProvider } from '@/lib/propertyLabel'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { StatusBadge } from '@/components/status'
import { ToastProvider, useToast } from '@/components/ui/toast'
import HelpPage from '@/components/help/HelpPage'
import Sidebar from '@/components/layout/Sidebar'
import ContextDrawer from '@/components/layout/ContextDrawer'
import DataView from '@/components/results/DataView'
import { useTaskData } from '@/hooks/useTaskData'
import { getConfig } from '@/services/api'
import ChatView from '@/components/chat/ChatView'
import WorkflowView from '@/components/workflow/WorkflowView'
import SettingsDialog, { loadReplaySpeed } from '@/components/settings/SettingsDialog'
import DeleteTaskDialog from '@/components/layout/DeleteTaskDialog'
import { listTasks as apiListTasks, retryTask as apiRetryTask, cancelTask as apiCancelTask, deleteTask as apiDeleteTask, deleteTaskData as apiDeleteTaskData, batchDeleteTasks as apiBatchDeleteTasks, replayTask as apiReplayTask, updateTaskTitle as apiUpdateTaskTitle } from '@/services/api'
import { usePipeline } from '@/hooks/usePipeline'
import { useTheme } from '@/hooks/useTheme'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { useSlidingPanes } from '@/hooks/useSlidingPanes'
import { useSlidingUnderline } from '@/hooks/useSlidingUnderline'
import { useContentTransition } from '@/hooks/useContentTransition'
import { useClickFeedback } from '@/hooks/useClickFeedback'

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
  // 2026-08-27：右侧详情面板默认收起（用户反馈初始三栏拥挤）；点击工具栏按钮展开
  const [detail, setDetail] = useState(null)
  const [dataRequest, setDataRequest] = useState(null)
  const viewMemory = useRef({})
  const uiMemory = useRef({})
  const [helpOpen, setHelpOpen] = useState(false)
  const taskMenuRef = useRef(null)
  const [config, setConfig] = useState(null)
  const [configError, setConfigError] = useState('')
  const [onboarding, setOnboarding] = useState(false)
  const guideShown = useRef(false)
  const [selectedId, setSelectedId] = useState(null)
  const [filter, setFilter] = useState('all')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [view, setView] = useState('chat')  // 主区视图：chat 对话 | workflow 工作流
  // 工作流 → 对话联动：{id, seq}，seq 递增保证重复点击同阶段也触发定位
  const [focusStage, setFocusStage] = useState(null)
  // 洞察报告入口 → 右侧详情面板洞察 tab：{tab, seq}
  // 任务列表（契约 D8-4：GET /api/tasks 分页，无限滚动）
  const [tasks, setTasks] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [taskListLoading, setTaskListLoading] = useState(false)
  const [cancelling, setCancelling] = useState(false)  // 取消任务请求进行中
  // 2026-09-02：侧栏双模式 —— user=我的查询（真实任务）/ sample=演示样例（内嵌样例）
  const [mode, setMode] = useState('user')
  // 演示样例折叠态：默认置顶 3 条（主区空白）；展开 → 全部 17 + 主区画廊
  const [samplesExpanded, setSamplesExpanded] = useState(false)
  const { toast } = useToast()
  const { theme, toggleTheme } = useTheme()
  const isNarrow = useMediaQuery('(max-width: 1023px)')

  const selected = tasks.find((t) => t.task_id === selectedId) || null  // CR-03: 契约 D8-4 键名 task_id
  useEffect(() => { if (taskMenuRef.current) taskMenuRef.current.open = false }, [selectedId, view])
  useEffect(() => {
    const dismiss = event => {
      const menu = taskMenuRef.current
      if (!menu?.open) return
      if (event.type === 'pointerdown' && !menu.contains(event.target)) menu.open = false
      if (event.type === 'keydown' && event.key === 'Escape') {
        const hadFocus = menu.contains(document.activeElement)
        menu.open = false
        if (hadFocus) menu.querySelector('summary')?.focus()
      }
    }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', dismiss)
    return () => { document.removeEventListener('pointerdown', dismiss); document.removeEventListener('keydown', dismiss) }
  }, [])

  // 窄屏自动折叠侧边栏（回到宽屏不强制展开，尊重用户手动收起）
  useEffect(() => {
    if (isNarrow) setSidebarOpen(false)
    else setSidebarOpen(true)
  }, [isNarrow])

  // 2026-09-02：模式/筛选切换竞态（"切换后记录混在一起，刷新才好"根因）——
  // 序号守卫：仅最新一次请求可写列表/统计，过期响应（旧模式后到）静默丢弃
  const loadSeqRef = useRef(0)
  const listingContextRef = useRef({ mode, filter })
  listingContextRef.current = { mode, filter }
  const loadTasks = async (o = 0, append = false) => {
    const seq = ++loadSeqRef.current
    if (!append) setTaskListLoading(true)
    const context = listingContextRef.current
    // 演示样例模式忽略『我的查询』遗留的状态筛选（服务端同样不带 status）
    const status = context.mode === 'user' && context.filter !== 'all' ? context.filter : undefined
    try {
      const data = await apiListTasks(50, o, status, context.mode)
      if (seq !== loadSeqRef.current || context.mode !== listingContextRef.current.mode || context.filter !== listingContextRef.current.filter) return
      setTasks((prev) => (append ? [...prev, ...data.items] : data.items))
      setTotal(data.total)
      setOffset(o + data.items.length)
    } catch (err) {
      if (seq !== loadSeqRef.current) return
      toast(`任务列表加载失败：${err.message}`, 'error')
    } finally {
      if (seq === loadSeqRef.current) setTaskListLoading(false)
    }
  }

  useEffect(() => {
    loadTasks(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, mode])

  // 2026-09-02：模式切换（我的查询 ↔ 演示样例）——清空选中，回各模式空态
  const handleModeChange = (m) => {
    if (m === mode) return
    ++loadSeqRef.current
    listingContextRef.current = { ...listingContextRef.current, mode: m }
    setTasks([]); setTotal(0); setOffset(0)
    setHelpOpen(false)
    setMode(m)
    setSelectedId(null)
    setDetail(null)
    setView('chat')
  }

  const handleLoadMore = async () => {
    if (loadingMore || offset >= total) return
    setLoadingMore(true)
    await loadTasks(offset, true)
    setLoadingMore(false)
  }

  const handleTaskDone = async () => {
    // 任务完成 → 刷新列表（状态徽标联动）
    await loadTasks(0)
    // P0-1/P0-2：task_completed 在 status 落库后发出，但网络/落库仍有微小窗口——
    // 兜底最多 3 次 × 500ms 延迟重拉（不读闭包 tasks，固定重试直到大概率稳定），
    // 保证选中任务 status 最终为 completed（DetailPanel 依赖其触发重拉）
    for (let i = 0; i < 3; i++) {
      await new Promise((r) => setTimeout(r, 500))
      await loadTasks(0)
    }
  }

  const handleNew = () => {
    setHelpOpen(false)
    setSelectedId(null); setDetail(null); setView('chat')
    if (mode === 'sample') setSamplesExpanded(true)
  }

  const handleSelect = (id) => {
    setHelpOpen(false)
    setSelectedId(id); setDetail(null); setDataRequest(null); setFocusStage(null)
    const target = tasks.find(task => task.task_id === id)
    setView(viewMemory.current[id] || (target?.status === 'completed' ? 'data' : 'chat'))
  }

  // 新任务创建成功（ChatView submitQuery 回调）
  const handleNewTask = async (taskId) => {
    await loadTasks(0)
    viewMemory.current[taskId] = 'chat'
    setSelectedId(taskId); setView('chat'); setDetail(null)
  }

  // 失败任务重试（契约 D2-4：POST retry 重建任务）
  const handleRetry = async (id) => {
    if (!await ensureLiveReady()) return
    try {
      const r = await apiRetryTask(id)
      toast('正在重试任务', 'info')
      await loadTasks(0)
      viewMemory.current[r.task_id] = 'chat'
      setSelectedId(r.task_id); setView('chat'); setDetail(null)
    } catch (err) {
      toast(`重试失败：${err.message}`, 'error')
    }
  }

  // 2026-08-27: 修改任务名（工具栏内联编辑）
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const titleInputRef = useRef(null)
  const startEditTitle = () => {
    if (!selected) return
    setTitleDraft(selected.title || selected.query || '')
    setEditingTitle(true)
  }
  const commitTitle = async () => {
    const draft = titleDraft.trim()
    setEditingTitle(false)
    if (!selected || !draft || draft === selected.title) return
    try {
      const r = await apiUpdateTaskTitle(selected.task_id, draft)
      setTasks((prev) => prev.map((t) => (t.task_id === r.task_id ? { ...t, title: r.title } : t)))
      toast('任务名已更新', 'success')
    } catch (err) {
      toast(`改名失败：${err.message}`, 'error')
    }
  }

  // 2026-08-27: 事件级重放（演示）——创建回放任务并选中；in-flight 防重（双击不排队两个）。
  // 速度取自设置页滑块（localStorage，默认 10x）
  const replayingRef = useRef(new Set())
  const handleReplay = async (id) => {
    if (replayingRef.current.has(id)) return
    replayingRef.current.add(id)
    try {
      const r = await apiReplayTask(id, loadReplaySpeed())
      toast('已创建回放任务', 'info')
      await loadTasks(0)
      viewMemory.current[r.task_id] = 'chat'
      setSelectedId(r.task_id); setView('chat'); setDetail(null)
    } catch (err) {
      toast(`重放失败：${err.message}`, 'error')
    } finally {
      replayingRef.current.delete(id)
    }
  }

  // 2026-08-24: 任务删除（单个内容级 + 批量整删）
  const [deleteTarget, setDeleteTarget] = useState(null)  // { mode: 'single'|'batch', task?, taskIds? }

  const handleDeleteRequest = (task) => {
    setDeleteTarget({ mode: 'single', task })
  }

  const handleBatchDeleteRequest = (taskIds) => {
    setDeleteTarget({ mode: 'batch', taskIds, count: taskIds.length })
  }

  const handleDeleteConfirm = async ({ whole, parts }) => {
    const target = deleteTarget
    if (!target) return
    setDeleteTarget(null)
    try {
      if (target.mode === 'batch') {
        const r = await apiBatchDeleteTasks(target.taskIds)
        const ok = (r.results || []).filter((x) => x.deleted).length
        toast(`已删除 ${ok} 个任务`, 'info')
      } else if (whole) {
        await apiDeleteTask(target.task.task_id)
        if (selectedId === target.task.task_id) setSelectedId(null)
        toast('任务已删除', 'info')
      } else {
        await apiDeleteTaskData(target.task.task_id, parts)
        toast('已清理所选内容', 'info')
      }
      await loadTasks(0)
    } catch (err) {
      toast(`删除失败：${err.message}`, 'error')
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
    setDetail(null)
    setView('chat')
    setFocusStage((prev) => ({ id: stageId, seq: (prev?.seq || 0) + 1 }))
  }

  // 洞察卡"查看完整报告" → 打开右侧详情面板并切到洞察 tab
  const openData = (section = 'records', extra = {}) => {
    setView('data'); setDetail(null)
    setDataRequest(prev => ({ section, ...extra, seq: (prev?.seq || 0) + 1 }))
  }
  const handleOpenInsights = () => openData('analysis')
  const acceptConfig = next => { setConfig(next); setConfigError('') }
  const refreshConfig = async (guide = false) => {
    try {
      const next = await getConfig(); acceptConfig(next)
      if (guide && !guideShown.current && !next.setup_complete) {
        guideShown.current = true; setOnboarding(true); setSettingsOpen(true)
      }
      return next
    } catch (err) { setConfigError(err.message); return null }
  }
  useEffect(() => { refreshConfig(true) }, [])
  useEffect(() => { if (selectedId) viewMemory.current[selectedId] = view }, [selectedId, view])
  const ensureLiveReady = async () => {
    const next = await refreshConfig()
    if (!next) { toast('无法读取科研连接状态，请检查服务连接', 'error'); return false }
    if (!next.setup_complete || next.restart_required || !Object.values(next.runtime_configured || {}).every(Boolean)) {
      setOnboarding(false); setSettingsOpen(true)
      toast(next.restart_required ? '请重启服务加载已保存的连接后再发起新查询' : '请先填写四项科研连接', 'info')
      return false
    }
    return true
  }

  // pipeline 状态上提：SSE 事件流驱动的实时阶段状态，对话/工作流视图共享。
  // （放在各 handler 定义之后，避免 const 暂时性死区）
  const pipelineState = usePipeline(selected, { onTaskDone: handleTaskDone, onTaskTitle: handleTaskTitle })
  // Terminal tasks keep clarification history, but no longer offer a live reply.
  const ended = ['completed', 'cancelled', 'failed', 'error'].includes(selected?.status) || (pipelineState.taskId === selected?.task_id && pipelineState.taskDone)
  const pipeline = ended ? { ...pipelineState, pending: null } : pipelineState

  const data = useTaskData(selected, pipeline.taskDone && pipeline.taskId === selected?.task_id, pipeline.stages.some(stage => stage.id === 'done' && stage.status === 'completed'))
  const pending = pipeline.pending
  const changeView = next => { setHelpOpen(false); setView(next); setDetail(null) }
  const memoryKey = selectedId || mode
  const taskMemory = uiMemory.current[memoryKey] ||= { chat: {}, data: {}, workflow: {} }
  const openHelp = () => { setDetail(null); setHelpOpen(true) }
  const viewsRef = useRef(null), primaryNavRef = useRef(null), pageRef = useRef(null)
  const pageMoving = useContentTransition(pageRef, `${memoryKey}:${helpOpen}`, { distance: 8, duration: 220 })
  const views = useSlidingPanes(viewsRef, view, ['chat', 'data', 'workflow'], { active: !helpOpen, identity: memoryKey })
  useSlidingUnderline(primaryNavRef, `${memoryKey}:${view}:${helpOpen}`)
  useClickFeedback()
  return (
    <PropertyNamesProvider properties={pipeline.stages.find(stage => stage.id === 'understand')?.output?.properties}><div className="theme-transition app-shell">
      <SettingsDialog open={settingsOpen} onboarding={onboarding} onClose={() => setSettingsOpen(false)} onConfigChange={acceptConfig} theme={theme} onToggleTheme={toggleTheme} />
      {deleteTarget && <DeleteTaskDialog mode={deleteTarget.mode} task={deleteTarget.task} count={deleteTarget.count} onClose={() => setDeleteTarget(null)} onConfirm={handleDeleteConfirm} />}
      {sidebarOpen && <Sidebar tasks={tasks} loadingTasks={taskListLoading} total={total} selectedId={selectedId} onSelect={handleSelect} onNew={handleNew} onCollapse={() => setSidebarOpen(false)} onRetry={handleRetry} onReplay={handleReplay} onOpenHelp={openHelp} onOpenSettings={() => { setOnboarding(false); setSettingsOpen(true) }} onLoadMore={handleLoadMore} filter={filter} onFilterChange={setFilter} onDeleteTask={handleDeleteRequest} onBatchDelete={handleBatchDeleteRequest} mode={mode} onModeChange={handleModeChange} samplesExpanded={samplesExpanded} onToggleSamples={handleNew} />}
      <div className="task-workspace">
        <main className="app-main">
          <header className="app-toolbar glass">
            <div className="task-title-row">
              {!sidebarOpen && <Button variant="ghost" size="icon" aria-label="展开侧栏" onClick={() => setSidebarOpen(true)}><Icon.Menu /></Button>}
              <div className="task-title">
                {editingTitle && !helpOpen ? <input aria-label="任务名称" autoFocus ref={titleInputRef} value={titleDraft} onChange={event => setTitleDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing) commitTitle(); if (event.key === 'Escape') setEditingTitle(false) }} onBlur={() => setEditingTitle(false)} /> : <h1 title={selected?.title}>{helpOpen ? '使用帮助' : selected?.title || selected?.query || (mode === 'sample' ? '演示样例' : '新建科研查询')}</h1>}
              </div>
              {selected && !helpOpen && <StatusBadge status={selected.status} />}
              {selected && !helpOpen && ['queued', 'running', 'pending'].includes(selected.status) && <Button variant="outline" size="sm" disabled={cancelling} onClick={handleCancel}>{cancelling ? '取消中…' : '取消任务'}</Button>}
              {selected && !helpOpen && <details ref={taskMenuRef} className="task-menu" onClick={event => { if (event.target.closest('button')) taskMenuRef.current.open = false }}><summary aria-label="任务操作"><Icon.Ellipsis /></summary><div className="task-menu-items"><button onClick={startEditTitle}>修改任务名</button>{selected.status === 'completed' && <button onClick={() => handleReplay(selected.task_id)}>回放任务</button>}{selected.status === 'error' && <button onClick={() => handleRetry(selected.task_id)}>重试任务</button>}{!(selected.source === 'sample' && !selected.replay_of) && <button onClick={() => handleDeleteRequest(selected)}>删除／清理任务</button>}</div></details>}
            </div>
            {!helpOpen && selected && <nav ref={primaryNavRef} className="primary-nav" aria-label="任务主页面">
              {[['chat', '对话', Icon.MessageSquare], ['data', '数据结果', Icon.Table], ['workflow', '工作流', Icon.Network]].map(([key, label, Glyph]) => <button key={key} aria-current={view === key ? 'page' : undefined} className={`primary-tab${view === key ? ' active' : ''}`} onClick={() => changeView(key)}>{Glyph && <Glyph />}{label}</button>)}
              {pending && <Button variant="outline" size="sm" onClick={() => handleShowStageInChat(pending.stageId || 'understand')}>{pending.type === 'human_review_batch' ? '待复核' : '待确认'} · 去处理</Button>}
            </nav>}
          </header>
          {configError ? <div className="app-notice error">服务配置读取失败：{configError}<button onClick={() => refreshConfig(true)}>重试读取</button></div> : config?.restart_required && <div className="app-notice">连接配置已保存，请重启服务后发起新的实操任务。<button onClick={() => { setOnboarding(false); setSettingsOpen(true) }}>查看配置</button></div>}
          {pipeline.stages.some(stage => stage.errors?.some(error => /401|403|auth|api.?key|token|鉴权|密钥/i.test(error.message || ''))) && <div className="app-notice error">任务报告连接或鉴权错误，请核对科研连接。<button onClick={() => { setOnboarding(false); setSettingsOpen(true) }}>打开设置</button></div>}
          {selected && !pipeline.taskDone && ['reconnecting', 'disconnected'].includes(pipeline.connectionStatus) && <div className="app-notice error">{pipeline.connectionStatus === 'reconnecting' ? '进度连接中断，正在重新连接。' : '进度连接中断，已有执行内容已保留。'}{pipeline.connectionStatus === 'disconnected' && <button onClick={pipeline.reconnect}>重新连接</button>}</div>}
          <div ref={pageRef} className="app-reading" data-context-moving={pageMoving || undefined}>
          {helpOpen && <HelpPage onReturn={() => setHelpOpen(false)} onSamples={() => { handleModeChange('sample'); handleNew() }} onQuery={() => { handleModeChange('user'); handleNew() }} onSettings={() => { setOnboarding(false); setSettingsOpen(true) }} pending={pending} onPending={() => { setHelpOpen(false); handleShowStageInChat(pending?.stageId || 'understand') }} />}
          <div ref={viewsRef} data-sliding={views.moving || undefined} style={{ display: helpOpen ? 'none' : 'flex' }} key={selectedId || mode} className="task-views slide-panes">
            <div className="task-view" {...views.paneProps('chat', 'flex')}>
              <ChatView memory={taskMemory.chat} active={!helpOpen && view === 'chat'} task={selected} pipeline={pipeline} data={data} onNewTask={handleNewTask} beforeCreate={ensureLiveReady} focusStage={focusStage} onOpenInsights={handleOpenInsights} onOpenData={openData} onOpenDetail={setDetail} mode={mode} samplesExpanded={samplesExpanded} onOpenSample={handleSelect} onReplaySample={handleReplay} onSwitchToUser={() => handleModeChange('user')} />
            </div>
            <div className="task-view" {...views.paneProps('data', 'flex')}><DataView memory={taskMemory.data} task={selected} data={data} pipeline={pipeline} request={dataRequest} onOpenDetail={setDetail} active={!helpOpen && view === 'data'} /></div>
            <div className="task-view" {...views.paneProps('workflow', 'flex')}><WorkflowView memory={taskMemory.workflow} active={!helpOpen && view === 'workflow'} onOpenData={openData} task={selected} pipeline={pipeline} data={data} onGoChat={() => handleShowStageInChat(pending?.stageId || 'understand')} onShowStageInChat={handleShowStageInChat} onOpenDetail={setDetail} /></div>
          </div>
          </div>
        </main>
        <ContextDrawer detail={detail} data={data} pipeline={pipeline} onClose={() => setDetail(null)} onChange={setDetail} onShowStageInChat={handleShowStageInChat} />
      </div>
    </div></PropertyNamesProvider>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <AppInner />
    </ToastProvider>
  )
}
