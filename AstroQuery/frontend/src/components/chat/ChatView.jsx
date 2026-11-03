import ReadOnlyInteractions from './ReadOnlyInteractions'
import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import Markdown from '@/lib/markdown'
import StageCard from './StageCard'
import { chatStageState } from '@/lib/chatStageState'
import ClarificationCard from './ClarificationCard'
import { useToast } from '@/components/ui/toast'
import SampleGallery from './SampleGallery'
import ReviewInteraction from './ReviewInteraction'
import ReviewReceipts from './ReviewReceipts'
import RetrievalPreferences from '@/components/settings/RetrievalPreferences'
import { ADS_SORTS, papersValue, preferencesFromConfig } from '@/lib/retrievalPreferences'
import { artifactUrl } from '@/services/api'
import { CompletionOutcome } from '@/components/results/DataView'
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
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 20 }}>
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

export default function ChatView({ memory = {}, active = true, task, pipeline, data, config, onNewTask, beforeCreate, focusStage, onOpenInsights, onOpenData, onOpenDetail,
  mode = 'user', samplesExpanded = false, samples = [], onOpenSample, onReplaySample, onSwitchToUser }) {
  const { messages, stages, timeline, pending, started, taskDone, sourceScores, submitQuery, submitAnswer } = pipeline
  const [input, setInput] = useState(memory.input || '')
  const [queryPreferences, setQueryPreferences] = useState(memory.retrievalPreferences || null)
  const [preferencesOpen, setPreferencesOpen] = useState(false)
  const effectivePreferences = queryPreferences || preferencesFromConfig(config)
  const changePreferences = value => { setQueryPreferences(value); memory.retrievalPreferences = value }
  useEffect(() => { memory.input = input }, [input, memory])
  const [submitting, setSubmitting] = useState(false)
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
    if (!task || !active || (!running && !pipeline.readOnly) || !el || !el.getClientRects().length || !stickToBottomRef.current) return
    const frame = requestAnimationFrame(() => { if (stickToBottomRef.current) el.scrollTop = el.scrollHeight })
    return () => cancelAnimationFrame(frame)
  }, [messages, stages, pending, taskDone, active, autoExpandedStage, readingHistory])

  const handleSubmit = async () => {
    const text = input.trim()
    if (!text || (running && !pending) || clarifying || submitRef.current || papersValue(effectivePreferences.papers_per_property) === null) return
    submitRef.current = true
    setSubmitting(true)
    try {
      if (pending) {
        // greeting 等澄清期：主栏输入即回答
        await submitAnswer(text)
        setInput('')
      } else {
        // 新查询：建任务 → 打开事件流
        if (beforeCreate && !await beforeCreate()) return
        const taskId = await submitQuery(text, {...effectivePreferences, papers_per_property:papersValue(effectivePreferences.papers_per_property)})
        changePreferences(null)
        setPreferencesOpen(false)
        onNewTask?.(taskId)
        // 失败（400）保留输入
        setInput('')
      }
    } catch (err) {
      toast(`提交失败：${err.message}`, 'error')
    } finally {
      submitRef.current = false
      setSubmitting(false)
    }
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {/* 内容区：统一时间线 —— 消息与卡片按产生顺序交错排列 */}
      <div ref={scrollRef} onScroll={handleScroll} onWheel={()=>{userScroll.current=performance.now()+900}} onTouchMove={()=>{userScroll.current=performance.now()+900}} onPointerDown={()=>{userScroll.current=performance.now()+1200}} onKeyDown={()=>{userScroll.current=performance.now()+900}} className="chat-gutter" style={{ flex: 1, overflowY: 'auto', padding: '24px 24px 16px' }}>
        <div className="chat-column">
          {pipeline.snapshot?.legacy_version === 1 && <p className="hint">旧版历史，只读展示，未按新规则复检。原任务状态：{pipeline.snapshot.legacy?.original_status}。<a href={artifactUrl(pipeline.snapshot.task_id, pipeline.snapshot.legacy_archive_artifact_id)} download>下载原始结果归档</a></p>}
          {/* 顶部信息带（用户重设计）：耗时 · 数据源 · 记录数 + 质量总结 */}
          {timeline.map((entry) => {
            if (entry.kind === 'msg') {
              const msg = messages.find((m) => m.id === entry.id)
              return msg && msg.phase !== 'completion' ? <Message key={`m-${entry.id}`} msg={msg} /> : null
            }
            if(entry.kind==='visit') return <div className="chat-return" key={entry.id}>
              <span>返回{stages.find(s=>s.id===entry.stageId)?.name}</span>
              <button className="text-link" onClick={()=>{setExpandedByUser(v=>({...v,[entry.stageId]:true}));
                scrollRef.current?.querySelector(`[data-stage-id="${entry.stageId}"]`)?.scrollIntoView({behavior:'smooth',block:'center'})}}>查看本阶段</button>
            </div>
            if(entry.kind==='review') {
              let review=(pipeline.readOnly?pipeline.presentation?.reviews:pipeline.snapshot?.reviews)?.find(r=>r.review_id===entry.reviewId)
              if(review&&entry.revision&&entry.revision!==review.revision)review={review_id:entry.reviewId,status:'closed_unanswered',question:'此审核问题后来经过修订。旧题干未保存。',evidence:[]}
              return review&&<ReviewInteraction key={entry.id} review={review} taskId={task?.task_id}
                readOnly={pipeline.readOnly} gate={pipeline.playback?.gate}
                onSubmit={submitAnswer} onReplaySubmit={pipeline.playback?.submitGate}
                receipts={pipeline.presentation?.review_receipts}/>
            }
            const stage = stages.find((s) => s.id === entry.id)
            if (!stage || pipeline.snapshot?.legacy_version || (stage.id === 'done' && !pipeline.presentation)) return null
            return (
              <Fragment key={`s-${entry.id}`}>
                <div className="stage-indent" data-stage-id={stage.id} style={{ marginLeft: 38, marginBottom: 8 }}>
                  <StageCard stage={stage} expanded={expandedByUser[stage.id] ?? (stage.id === 'done' || stage.id === autoExpandedStage)} onToggle={toggleStage} onOpenInsights={onOpenInsights} onOpenAgent={handleOpenAgent} sourceScores={sourceScores} data={data} onOpenData={onOpenData}
                    historyContent={pipeline.readOnly && stage.id==='understand'
                      ? <ReadOnlyInteractions presentation={pipeline.presentation} taskId={task?.task_id} stageId={stage.id}/>
                      : null}
                    onReplay={stage.id==='done' && !pipeline.readOnly && onReplaySample ? ()=>onReplaySample(task.task_id) : undefined} />
                </div>
                {pending && pending.stageId === stage.id && pending.type !== 'greeting' && <ClarificationCard payload={pending} onSubmit={submitAnswer} />}

              </Fragment>
            )
          })}

          {pipeline.snapshot?.legacy_version && pipeline.snapshot.delivery_ref && <Button variant="outline" onClick={()=>onOpenData?.('records')}>查看归档结果</Button>}
          {!pipeline.presentation && pipeline.snapshot?.kind !== 'replay' && data.availability === 'ready' && <CompletionOutcome data={data} onOpenData={onOpenData} />}

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
                    onReplay={onReplaySample}
                    onSwitchToUser={onSwitchToUser}
                  />
                </div>
              )
            ) : (
              <div className="query-start">
                <h2>查询一个天体</h2>
                <form className="query-compose" onSubmit={event => { event.preventDefault(); handleSubmit() }}>
                  <textarea aria-label="科研查询" value={input} rows={3} placeholder="输入天体名称和想了解的性质…"
                    onChange={event => setInput(event.target.value)}
                    onKeyDown={event => {
                      if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
                        event.preventDefault()
                        handleSubmit()
                      }
                    }}/>
                  <div className="query-preference-row"><div className="query-pref-summary"><button type="button" className="query-preference-toggle" aria-expanded={preferencesOpen} onClick={()=>setPreferencesOpen(value=>!value)}>每项 {effectivePreferences.papers_per_property} 篇 · {ADS_SORTS.find(([key])=>key===effectivePreferences.ads_sort)?.[1] || '相关度优先'}</button>{queryPreferences && <button type="button" className="query-pref-reset" onClick={()=>changePreferences(null)}>恢复默认</button>}</div>
                    {preferencesOpen && <div className="query-preferences"><RetrievalPreferences id="query" value={effectivePreferences} onChange={changePreferences}/></div>}
                  </div>
                  <div><Button type="submit" disabled={!input.trim() || submitting || papersValue(effectivePreferences.papers_per_property)===null}>{submitting ? '正在创建…' : '开始查询'} <Icon.Send /></Button></div>
                </form>
                <div className="example-queries">{EXAMPLE_PROMPTS.map(prompt =>
                  <button key={prompt} onClick={() => { setInput(prompt); scrollRef.current?.querySelector('textarea')?.focus() }}>{prompt}</button>)}</div>
              </div>
            )
          )}
        </div>
      </div>

      {readingHistory && running && !clarifying && <div className="latest-progress"><Button variant="outline" size="sm" onClick={() => { stickToBottomRef.current = true; setReadingHistory(false) }}>查看最新进展 ↓</Button></div>}
      {/* 输入栏（块 6 定案：附件 chips / 状态禁用；玻璃输入舱）
          2026-09-02：演示样例模式 → 禁发提示条（防误触发起真实计费查询） */}
      {pipeline.readOnly || pipeline.snapshot?.kind === 'replay' ? null : mode === 'sample' && task ? (
        <div style={{ padding: '12px 24px 20px', flexShrink: 0 }}>
          <div className="chat-column">
            <div
              className="composer"
              style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '11px 16px' }}
            >
              <Icon.Sparkle style={{ width: 15, height: 15, color: 'var(--accent-text)', flexShrink: 0 }} />
              <span style={{ flex: 1, fontSize: 'var(--text-note)', color: 'var(--content-fg-secondary)', lineHeight: 1.5 }}>
                演示样例
              </span>
              <button
                onClick={onSwitchToUser}
                title="切回『我的查询』发起新的真实查询"
                className="active-press"
                style={{
                  border: '1px solid color-mix(in srgb, var(--accent) 45%, transparent)',
                  background: 'var(--accent-light)', color: 'var(--accent-text)',
                  fontSize: 'var(--text-note)', fontWeight: 500, padding: '5px 12px', borderRadius: 'var(--radius-pill)',
                  cursor: 'pointer', flexShrink: 0, whiteSpace: 'nowrap',
                }}
              >
                发起真实查询
              </button>
            </div>
          </div>
        </div>
      ) : null}

    </div>
  )
}
