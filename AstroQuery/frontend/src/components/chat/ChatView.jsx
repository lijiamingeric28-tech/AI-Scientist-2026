import AstroQueryLogo from '@/components/icons/AstroQueryLogo'
import { Fragment, Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { chatStageState } from '@/lib/chatStageState'
import { useToast } from '@/components/ui/toast'
import SampleGallery from './SampleGallery'
import RetrievalPreferences from '@/components/settings/RetrievalPreferences'
import { ADS_SORTS, papersValue, preferencesFromConfig } from '@/lib/retrievalPreferences'
import { artifactUrl, newOperationId } from '@/services/api'
import QueryComposer from './QueryComposer'
import { useFollowup } from './useFollowup'
import { savedAnswerSelection } from './followupState'
const ReadOnlyInteractions = lazy(() => import('./ReadOnlyInteractions'))
const StageCard = lazy(() => import('./StageCard'))
const ClarificationCard = lazy(() => import('./ClarificationCard'))
const AggregatedReviewCard = lazy(() => import('./AggregatedReviewCard'))
const Markdown = lazy(() => import('@/lib/markdown'))
const CompletionOutcome = lazy(() => import('@/components/results/DataView').then(m => ({ default: m.CompletionOutcome })))
const AgentCopilot = lazy(() => import('./AgentCopilot'))
// 精选目录由产品的只读发布清单提供；初始为空。


/* 对话视图（块 3 定案）：
 * - 消息流 / 阶段卡片 / HITL 澄清 / 输入栏（块 6）
 * 数据源：App 层上提的 usePipeline（SSE 事件流 + REST，契约 API_CONTRACT.md），
 * 与工作流视图共享同一份实时状态。
 */

/* AI 消息（文档流）：Sparkle 图标 + markdown —— 用于对话消息与卡片下方总结 */
function AiMessage({ content }) {
  return (
    <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: 6,
          background: 'var(--surface-secondary)',
          border: '1px solid var(--surface-border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          color: 'var(--content-fg-secondary)',
        }}
      >
        <Icon.Sparkle />
      </div>
      <div style={{ paddingTop: 3, flex: 1, minWidth: 0 }}>
        <Markdown>{typeof content === 'string' ? content.replaceAll('图证', '研究图像') : content}</Markdown>
      </div>
    </div>
  )
}

function Message({ msg }) {
  if (msg.role === 'user') {
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 24 }}>
        <div className="msg-bubble">{msg.content}</div>
      </div>
    )
  }
  return <AiMessage content={msg.content} />
}

/* 空状态示例提问（引导新用户，点击填入输入框） */
const EXAMPLE_PROMPTS = [
  '查询 M13 的距离、年龄与金属丰度',
  '提取蟹状星云中心脉冲星的自转参数',
  '收集 M31 球状星团系统的金属丰度数据',
]

function getStageNarrative(stageId, stages, targetName) {
  const understandStage = stages.find((s) => s.id === 'understand')
  const actualTarget = understandStage?.target?.main_id || understandStage?.target?.name || (targetName && targetName.length <= 16 ? targetName : null)
  const retrievalStage = stages.find((s) => s.id === 'retrieval')
  const extractionStage = stages.find((s) => s.id === 'extraction')
  const qualityStage = stages.find((s) => s.id === 'quality_check')
  const cleanStage = stages.find((s) => s.id === 'clean')

  switch (stageId) {
    case 'understand':
      return '好的，我先开始「任务理解」——确认目标天体与要提取的标准性质。'
    case 'retrieval':
      return `已完成「任务理解${actualTarget ? `（已确认目标 ${actualTarget}）` : ''}」，下面开始「数据检索」。`
    case 'extraction': {
      const u = retrievalStage?.uniqueReadable
      const dataStr = u ? `${u} 篇不同可读作品` : '星表与文献检索'
      return `已完成「数据检索（${dataStr}）」，下面开始「数据提取」。`
    }
    case 'quality_check': {
      const cand = extractionStage?.activity?.candidates?.total
      const dataStr = cand ? `提取 ${cand} 项候选记录` : null
      return `已完成「数据提取${dataStr ? `（${dataStr}）` : ''}」，下面开始「质量检查」。`
    }
    case 'clean': {
      const roots = qualityStage?.activity?.quality?.roots
      const dataStr = roots ? `${roots} 项候选通过质检` : null
      return `已完成「质量检查${dataStr ? `（${dataStr}）` : ''}」，下面开始「数据清洗」。`
    }
    case 'comparison': {
      const changed = cleanStage?.activity?.cleaning?.states?.changed
      const dataStr = Number.isFinite(changed) ? `${changed} 项表示变更` : null
      return `已完成「数据清洗${dataStr ? `（${dataStr}）` : ''}」，下面开始「数据对照」。`
    }
    case 'deliver':
      return '已完成多源数据对照与核验，下面整理交付数据集。'
    case 'insight':
      return '已完成数据集交付，下面生成天体物理学洞察报告。'
    default:
      return null
  }
}

export default function ChatView({ memory = {}, active = true, task, pipeline, data, config, onNewTask, beforeCreate, focusStage, onOpenInsights, onOpenData, onOpenDetail,
  mode = 'user', isReplaying = false, theme, samplesExpanded = false, samples = [], onOpenSample, onOpenSampleChat, onReplaySample, onSwitchToUser }) {
  const { messages, stages, timeline, pending, started, taskDone, sourceScores, submitQuery, submitAnswer } = pipeline
  const [input, setInput] = useState(memory.input || '')
  const [queryPreferences, setQueryPreferences] = useState(memory.retrievalPreferences || null)
  const [preferencesOpen, setPreferencesOpen] = useState(false)
  const effectivePreferences = queryPreferences || preferencesFromConfig(config)
  const changePreferences = value => { setQueryPreferences(value); memory.retrievalPreferences = value }
  useEffect(() => { memory.input = input }, [input, memory])
  const [submitting, setSubmitting] = useState(false)
  const isEmptyState = mode === 'user' && !task && !started && timeline.length === 0
  const followupEnabled = !isReplaying && !!(task?.task_id && data.deliveryId && data.deliveryRevision)
  const scope = useMemo(() => ({ delivery_id: data.deliveryId, delivery_revision: data.deliveryRevision }), [data.deliveryId, data.deliveryRevision])
  const followup = useFollowup(task?.task_id, data.deliveryId, data.deliveryRevision, followupEnabled)
  const [composeMode, setComposeMode] = useState('followup')
  const [context, setContext] = useState(null)
  const textarea = useRef(null)
  const activeDraft = followupEnabled && composeMode === 'followup' && !pending
  const draftKey = 'astroquery.followup.draft.' + task?.task_id + '.' + data.deliveryId + '.' + data.deliveryRevision
  const [draft, setDraft] = useState({ key: '', text: '' })
  const followupText = draft.key === draftKey ? draft.text : ''
  const draftRef = useRef(followupText)
  draftRef.current = followupText
  const submissionRef = useRef({})
  const readSubmission = useCallback(() => {
    if (submissionRef.current.key !== draftKey) {
      let value = null
      try { value = JSON.parse(sessionStorage.getItem(draftKey + '.submission')) } catch { /* keep draft usable */ }
      submissionRef.current = { key: draftKey, value }
    }
    return submissionRef.current.value
  }, [draftKey])
  const writeSubmission = useCallback(value => {
    submissionRef.current = { key: draftKey, value }
    try {
      if (value) sessionStorage.setItem(draftKey + '.submission', JSON.stringify(value))
      else sessionStorage.removeItem(draftKey + '.submission')
    } catch { /* this page can still resume */ }
  }, [draftKey])
  const saveFollowupText = useCallback(text => {
    draftRef.current = text
    setDraft({ key: draftKey, text })
    try { localStorage.setItem(draftKey, text) } catch { /* session still works */ }
  }, [draftKey])
  useEffect(() => {
    if (!followupEnabled) return
    try { setDraft({ key: draftKey, text: localStorage.getItem(draftKey) || '' }) } catch { /* session still works */ }
    setContext(null)
    setComposeMode('followup')
  }, [draftKey, followupEnabled])
  useEffect(() => {
    if (!followupEnabled || draft.key !== draftKey) return
    const sent = readSubmission()
    if (!sent || !followup.rows.some(row => row.request_id === sent.id)) return
    writeSubmission(null)
    if (draftRef.current === sent.raw && (!context || JSON.stringify(context) === JSON.stringify(sent.selection))) {
      saveFollowupText('')
      setContext(null)
    }
  }, [followupEnabled, draft.key, draftKey, followup.rows, context, readSubmission, writeSubmission, saveFollowupText])
  const askContext = useCallback(selection => {
    setComposeMode('followup')
    setContext(selection)
    if (selection.prompt && !followupText.trim()) saveFollowupText(selection.prompt)
    requestAnimationFrame(() => textarea.current?.focus())
  }, [followupText, saveFollowupText])
  const { toast } = useToast()
  // 历史阶段默认折叠；当前阶段自动展开，用户手动操作优先。
  const [expandedByUser, setExpandedByUser] = useState(memory.expanded || {})
  // P1-2：Agent 侧抽屉下钻（对话卡点击 Agent 行 → StageDetailPanel L3）
  const [readingHistory, setReadingHistory] = useState(memory.follow === false)
  const [autoExpandedStage, setAutoExpandedStage] = useState(memory.autoExpandedStage || null)
  useEffect(() => {
    if (!active || readingHistory) return
    const current = stages.find(s=>s.id===pipeline.presentation?.active_stage && ['running','waiting'].includes(chatStageState(s))) || [...stages].reverse().find(stage => stage.id !== 'done' && (stage.business ? chatStageState(stage) : stage.status) === 'running')
    setAutoExpandedStage(current?.id || null)
  }, [stages, active, readingHistory])
  useEffect(() => { memory.autoExpandedStage = autoExpandedStage }, [autoExpandedStage])
  const initialScrollTop = useRef(memory.scrollTop || 0)
  useEffect(() => { stickToBottomRef.current = memory.follow ?? (pipeline.readOnly || (!!task && !['completed', 'cancelled', 'failed', 'error'].includes(task.status))); setReadingHistory(!stickToBottomRef.current); if (scrollRef.current && !initialScrollTop.current) scrollRef.current.scrollTop = 0 }, [task?.task_id,pipeline.readOnly])
  useEffect(() => { memory.expanded = expandedByUser }, [expandedByUser])
  const submitRef = useRef(false)
  const scrollRef = useRef(null)
  // 贴底跟随：用户在底部附近才自动滚动，向上翻阅时不被拽回
  const stickToBottomRef = useRef(memory.follow ?? (!!task && !['completed', 'cancelled', 'failed', 'error'].includes(task.status)))
  const restoredRef = useRef(false)
  useEffect(() => { if (!active || !timeline.length || restoredRef.current || !initialScrollTop.current) return; restoredRef.current = true; requestAnimationFrame(() => { if (scrollRef.current) scrollRef.current.scrollTop = initialScrollTop.current }) }, [active, timeline.length])

  // 顶部信息带统计（任务完成时一次性拉取并缓存；taskId 键防重复请求）
  // 2026-08-27：useCallback 稳定引用——StageCard 已 memo，onToggle/onOpenAgent/
  // onOpenInsights 若不稳定（每次 render 新函数），memo 恒失效，高频 setStages
  // 场景全量重渲（主区滚动卡顿的元凶）
  const toggleStage = useCallback((id) => {
    setExpandedByUser(prev => ({ ...prev, [id]: !(prev[id] ?? (id === 'done' || id === autoExpandedStage)) }))
  }, [autoExpandedStage])

  // 稳定引用（StageCard memo 依赖）：Agent 行点击 → L3 下钻抽屉
  const handleOpenAgent = useCallback((agent, stage) => {
    if (stage) onOpenDetail?.({ type: 'stage', stageId: stage.id, agentKey: agent.id || agent.agent })
  }, [onOpenDetail])

  // 工作流视图"在对话中查看" → 展开目标卡并滚动定位
  useEffect(() => {
    if (!focusStage?.id) return
    setExpandedByUser(prev => ({ ...prev, [focusStage.id]: true }))
    // 等卡片展开渲染后再滚动
    const timer = setTimeout(() => {
      const review = focusStage.reviewId && scrollRef.current?.querySelector(`[data-review-id="${CSS.escape(focusStage.reviewId)}"]`)
      if (review) review.open = true
      const el = review || scrollRef.current?.querySelector(`[data-stage-id="${focusStage.id}"]`)
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 60)
    return () => clearTimeout(timer)
  }, [focusStage])

  const userScroll=useRef(0)
  const handleScroll = () => {
    const el = scrollRef.current
    if (!el || !active || (initialScrollTop.current && !restoredRef.current)) return
    if(pipeline.readOnly && performance.now()>userScroll.current)return
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    memory.scrollTop = el.scrollTop; memory.follow = stickToBottomRef.current
    setReadingHistory(!stickToBottomRef.current)
  }

  /* 运行中 = 任务已启动且未完成；澄清期 = 澄清卡挂起（寒暄除外，寒暄走主栏对话） */
  const running = started && !taskDone
  const clarifying = !!pending && pending.type !== 'greeting'

  // 贴底跟随滚动：仅在用户位于底部附近时自动滚到底
  // 2026-08-27：滚动性能——每 event 同步写 scrollTop 会强制浏览器同步 layout
  // 完整子树（卡顿来源）。改为 rAF 合并：一个动画帧内至多一次 scrollTop 赋值，
  // 且只有内容高度变化（增量 >0）才滚（避免用户上拉回看时被拽回）。
  // 用户阅读历史时停止跟随，任务完成和晚到结果不抢夺阅读位置。
  useEffect(() => {
    const el = scrollRef.current
    if (!task || !active || (!running && !isReplaying && !followup.rows.length && !followup.busy) || !el || !el.getClientRects().length || !stickToBottomRef.current) return
    const frame = requestAnimationFrame(() => { if (stickToBottomRef.current) el.scrollTop = el.scrollHeight })
    return () => cancelAnimationFrame(frame)
  }, [messages, stages, pending, taskDone, active, autoExpandedStage, readingHistory, followup.rows, followup.busy, isReplaying])

  const handleSubmit = async () => {
    const text = (activeDraft ? followupText : input).trim()
    if (!text || isReplaying || clarifying || submitRef.current || (running && !pending)) return
    if (activeDraft) {
      if (followup.busy) return
      const visible = followup.rows.filter(row => !row.question_id ||
        (followup.selectedAnswers[row.question_id] || followup.rows.findLast(item => item.question_id === row.question_id)?.id) === row.id)
      const previous = readSubmission()
      const reuse = previous?.text === text &&
        (!context || JSON.stringify(context) === JSON.stringify(previous.selection))
      const selected = reuse ? previous.selection : context || savedAnswerSelection(visible)
      const requestId = reuse ? previous.id : newOperationId()
      // Keep the draft and its operation until the server acknowledges this exact request.
      writeSubmission({ id: requestId, text, raw: followupText, selection: selected })
      stickToBottomRef.current = true
      setReadingHistory(false)
      await followup.ask({ ...selected, text, requestId })
      return
    }
    const count = papersValue(effectivePreferences.papers_per_property)
    if (count === null) return
    submitRef.current = true
    setSubmitting(true)
    try {
      if (pending) {
        await submitAnswer(text)
      } else {
        if (beforeCreate && !(await beforeCreate())) return
        const taskId = await submitQuery(text, { ...effectivePreferences, papers_per_property: count })
        changePreferences(null)
        setPreferencesOpen(false)
        onNewTask?.(taskId)
      }
      setInput('')
    } catch (err) {
      toast('提交失败：' + err.message, 'error')
    } finally {
      submitRef.current = false
      setSubmitting(false)
    }
  }

  const composer = <QueryComposer textarea={textarea} mode={activeDraft ? 'followup' : 'new'}
    value={activeDraft ? followupText : input} onChange={activeDraft ? saveFollowupText : setInput}
    canSwitch={followupEnabled && !running && !pending}
    onSwitch={value => { setComposeMode(value); requestAnimationFrame(() => textarea.current?.focus()) }}
    onStop={followup.stop} busy={activeDraft && followup.busy}
    disabled={(running && !pending) || clarifying || submitting}
    onSubmit={handleSubmit} selectionCount={context?.recordIds?.length || context?.markers?.length || context?.selections?.length || (context?.prompt ? 1 : 0)}
    onClearSelection={() => setContext({})}
    placeholder={clarifying ? '请在上方回答问题…' : (running && !pending) ? '查询正在运行…' : undefined}
    preferenceControls={!task && mode === 'user' || followupEnabled && !activeDraft && !pending ?
      <><button type="button" className="research-action" aria-expanded={preferencesOpen} onClick={() => setPreferencesOpen(value => !value)}>
        每项 {effectivePreferences.papers_per_property} 篇 · {ADS_SORTS.find(([key]) => key === effectivePreferences.ads_sort)?.[1] || '相关度'}
      </button>
      {preferencesOpen && <RetrievalPreferences id="query-retrieval" value={effectivePreferences} onChange={changePreferences} disabled={submitting} />}</> : null}
  />

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {/* 内容区：统一时间线 —— 消息与卡片按产生顺序交错排列 */}
      <div ref={scrollRef} onScroll={handleScroll} onWheel={()=>{userScroll.current=performance.now()+900}} onTouchMove={()=>{userScroll.current=performance.now()+900}} onPointerDown={()=>{userScroll.current=performance.now()+1200}} onKeyDown={()=>{userScroll.current=performance.now()+900}} className="chat-gutter" style={{ flex: 1, overflowY: 'auto', padding: '24px 24px 16px' }}>
        <div className="chat-column">
          {pipeline.snapshot?.legacy_version === 1 && <p className="hint">旧版历史，只读展示，未按新规则复检。原任务状态：{pipeline.snapshot.legacy?.original_status}。<a href={artifactUrl(pipeline.snapshot.task_id, pipeline.snapshot.legacy_archive_artifact_id)} download>下载原始结果归档</a></p>}
          {/* 顶部信息带（用户重设计）：耗时 · 数据源 · 记录数 + 质量总结 */}
          {(() => {
            let reviewRendered = false
            const rawReviews = (pipeline.readOnly ? pipeline.presentation?.reviews : pipeline.snapshot?.reviews) || []
            return timeline.map((entry) => {
              if (entry.kind === 'msg') {
                const msg = messages.find((m) => m.id === entry.id)
                return msg && msg.phase !== 'completion' ? <Message key={`m-${entry.id}`} msg={msg} /> : null
              }
              if (entry.kind === 'visit') return <div className="chat-return" key={entry.id}>
                <span>返回{stages.find(s=>s.id===entry.stageId)?.name}</span>
                <button className="text-link" onClick={()=>{setExpandedByUser(v=>({...v,[entry.stageId]:true}));
                  scrollRef.current?.querySelector(`[data-stage-id="${entry.stageId}"]`)?.scrollIntoView({behavior:'smooth',block:'center'})}}>查看本阶段</button>
              </div>
              if (entry.kind === 'review') {
                if (reviewRendered) return null
                reviewRendered = true
                const reviewCount = rawReviews.length || 1
                return (
                  <Fragment key={`aggregated-review-${entry.id}`}>
                    <AiMessage content={`已完成「数据对照」，发现 ${reviewCount} 项文献记录存在分歧，需进行人工决策或核对。`} />
                    <div className="stage-indent" style={{ marginLeft: 38, marginBottom: 24 }}>
                      <AggregatedReviewCard
                        reviews={rawReviews}
                        taskId={task?.task_id}
                        readOnly={pipeline.readOnly}
                        gate={pipeline.playback?.gate}
                        onSubmit={submitAnswer}
                        onReplaySubmit={pipeline.playback?.submitGate}
                        receipts={pipeline.presentation?.review_receipts}
                      />
                    </div>
                  </Fragment>
                )
              }
              const stage = stages.find((s) => s.id === entry.id)
              if (!stage || pipeline.snapshot?.legacy_version || (stage.id === 'done' && !pipeline.presentation)) return null
              const narrative = getStageNarrative(stage.id, stages, pipeline.presentation?.target_name || task?.title)
              return (
                <Fragment key={`s-${entry.id}`}>
                  {narrative && <AiMessage content={narrative} />}
                  <div className="stage-indent" data-stage-id={stage.id} style={{ marginLeft: 38, marginBottom: 24 }}>
                    <StageCard stage={stage} expanded={expandedByUser[stage.id] ?? (stage.id === 'done' || stage.id === autoExpandedStage)} onToggle={toggleStage} onOpenInsights={onOpenInsights} onOpenAgent={handleOpenAgent} sourceScores={sourceScores} data={data} onOpenData={onOpenData}
                      historyContent={pipeline.readOnly && stage.id==='understand'
                        ? <ReadOnlyInteractions presentation={pipeline.presentation} taskId={task?.task_id} stageId={stage.id}/>
                        : null}
                      onReplay={stage.id==='done' && !pipeline.readOnly && onReplaySample ? ()=>onReplaySample(task.task_id) : undefined} />
                  </div>
                  {pending && pending.stageId === stage.id && pending.type !== 'greeting' && <ClarificationCard payload={pending} onSubmit={submitAnswer} />}
                </Fragment>
              )
            })
          })()}

          {pipeline.snapshot?.legacy_version && pipeline.snapshot.delivery_ref && <Button variant="outline" onClick={()=>onOpenData?.('records')}>查看归档结果</Button>}
          {!pipeline.presentation && pipeline.snapshot?.kind !== 'replay' && data.availability === 'ready' && <CompletionOutcome data={data} onOpenData={onOpenData} />}
          {followupEnabled && (followup.rows.length > 0 || followup.busy || followup.error) && <Suspense fallback={null}>
            <AgentCopilot followup={followup} taskId={task.task_id} scope={scope} dark={theme === 'dark'}
              onOpenDetail={onOpenDetail} onAsk={askContext} />
          </Suspense>}

          {/* 兜底：澄清卡 stageId 未匹配时渲染在时间线末尾 */}
          {pending && pending.type !== 'greeting' && !timeline.some((t) => t.kind === 'stage' && t.id === pending.stageId) && (
            <ClarificationCard payload={pending} onSubmit={submitAnswer} />
          )}

          {/* 空状态：无任务或时间线为空 → 演示样例画廊 / 引导 + 示例提问 */}
          {!started && timeline.length === 0 && (
            task ? (
              /* 有选中任务但时间线未起（排队/事件未流到）→ 准备中 */
              <div className="empty-state" style={{ paddingTop: 72, gap: 10 }}>
                <div style={{ width: 44, height: 44, borderRadius: 12, background: 'var(--surface-bg)', border: '1px solid var(--surface-border)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-text)', marginBottom: 4 }}>
                  <Icon.Sparkle style={{ width: 18, height: 18 }} />
                </div>
                <div style={{ fontSize: 'var(--text-body)', fontWeight: 510, color: 'var(--content-fg)' }}>{pipeline.readOnly?'正在读取查询记录…':'任务准备中…'}</div>
              </div>
            ) : mode === 'sample' ? (
              /* 演示入口直接展示案例，侧栏折叠不隐藏主区内容。 */
              (
                <div style={{ padding: '24px 4px 8px' }}>
                  <SampleGallery
                    samples={samples}
                    onOpen={onOpenSample}
                    onOpenChat={onOpenSampleChat}
                    onReplay={onReplaySample}
                    onSwitchToUser={onSwitchToUser}
                    onOpenData={onOpenData}
                    onOpenDetail={onOpenDetail}
                  />
                </div>
              )
            ) : (
              <div className="empty-state" style={{ paddingTop: 96, display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 14 }}>
                <AstroQueryLogo width={124} height={91} style={{ marginBottom: 4 }} />
                <div
                  style={{
                    fontFamily: 'var(--font-display)',
                    fontSize: 21,
                    fontWeight: 650,
                    color: 'var(--title-strong, var(--seed-accent))',
                    letterSpacing: '-0.015em',
                    lineHeight: 1.35,
                  }}
                >
                  开始一次天文数据提取
                </div>
                <div
                  style={{
                    maxWidth: 480,
                    lineHeight: 1.72,
                    fontSize: 13.5,
                    color: 'var(--content-fg-secondary)',
                    padding: '0 16px',
                    margin: '-4px 0 4px',
                  }}
                >
                  描述目标天体与想查询的物理性质，智能体将自动完成意图确认、文献检索、数据提取与质检。
                </div>

                <div className="research-hero-composer">{composer}</div>

                {/* 居中 Prompt 示例药丸 */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12, width: '100%', maxWidth: 440, padding: '0 12px' }}>
                  {EXAMPLE_PROMPTS.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => {
                        setInput(prompt)
                        textarea.current?.focus()
                      }}
                      className="filter-chip active-press"
                      style={{
                        borderRadius: 8,
                        padding: '9px 16px',
                        border: '1px solid var(--surface-border)',
                        background: 'var(--surface-bg)',
                        color: 'var(--content-fg)',
                        fontSize: 13,
                        cursor: 'pointer',
                        textAlign: 'center',
                        transition: 'all 0.15s ease',
                      }}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            )
          )}
        </div>
      </div>

      {readingHistory && (running || followup.busy) && !clarifying &&
        <div className="latest-progress"><Button variant="outline" size="sm" onClick={() => {
          stickToBottomRef.current = true
          setReadingHistory(false)
          if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
        }}>查看最新进展 ↓</Button></div>}
      {!isReplaying && task && !isEmptyState && (!pipeline.readOnly || followupEnabled) &&
        <div className="research-composer-area">{composer}</div>}
    </div>
  )
}
