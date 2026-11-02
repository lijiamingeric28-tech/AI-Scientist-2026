import { useEffect, useRef, useState } from 'react'
import { useContentTransition } from '@/hooks/useContentTransition'
import { useSlidingPanes } from '@/hooks/useSlidingPanes'
import { useSlidingUnderline } from '@/hooks/useSlidingUnderline'
import { useRememberedState } from '@/hooks/useViewMemory'
import { Button } from '@/components/ui/button'
import StageCard from '@/components/chat/StageCard'
import LogDrawer from '@/components/log/LogDrawer'
import ExecutionOverview from './ExecutionOverview'
import { ResourceState } from '@/components/results/DataView'
import { Pagination } from '@/components/results/AnalysisView'
import { Prose } from '@/components/results/ReadableContent'
import { executionTraces } from '@/lib/resultData'
import { modificationView, readableText, sourceName } from '@/lib/readableData'

const LABELS = { completed: '已完成', running: '执行中', error: '失败', waiting: '未开始', skipped: '已跳过', cancelled: '已取消' }
export default function WorkflowView({ memory = {}, task, pipeline, data, onGoChat, onShowStageInChat, onOpenDetail, onOpenData, active = true }) {
  const { pending, taskDone } = pipeline
  const stages = (pipeline.stages || []).filter(stage => stage.id !== 'done')
  const [selectedId, setSelectedId] = useRememberedState(memory, 'stage', null), [following, setFollowing] = useRememberedState(memory, 'following', true), [section, setSection] = useRememberedState(memory, 'section', 'stages')
  const current = stages.find(stage => stage.status === 'running') || [...stages].reverse().find(stage => ['completed', 'error', 'cancelled'].includes(stage.status)) || stages[0]
  useEffect(() => { if (following && current) setSelectedId(current.id) }, [following, current?.id])
  const selected = stages.find(stage => stage.id === selectedId) || current
  const paneRef = useRef(null), contentRef = useRef(null), navRef = useRef(null)
  const panes = useSlidingPanes(contentRef, section, ['stages', 'logs', 'statistics'], { active, identity: task?.task_id })
  useSlidingUnderline(navRef, `${section}:${active}`)
  useContentTransition(paneRef, selectedId, { active: active && section === 'stages' && !following && !panes.moving, selector: '.workflow-stage-content', distance: 12, duration: 240, order: stages.map(stage => stage.id) })
  const openAgent = (agent, stage) => onOpenDetail({ type: 'stage', stageId: stage.id, agentKey: agent.id || agent.agent })
  return <div ref={paneRef} className="workflow-workbench" data-component="workflow-view"><header className="workflow-heading"><div><h2>执行工作流</h2><p className="hint">{stages.filter(stage => stage.status === 'completed').length} / {stages.length} 个处理阶段已完成</p></div>{!following && !taskDone && <Button variant="outline" size="sm" onClick={() => setFollowing(true)}>跟随当前阶段</Button>}</header>
    {pending && pending.type !== 'greeting' && <div className="notice"><span>{pending.title || '有待确认问题'}</span><Button variant="outline" size="sm" onClick={onGoChat}>去处理</Button></div>}
    <nav ref={navRef} className="data-tabs" aria-label="工作流分类">{[['stages', '阶段与步骤'], ['logs', '日志与错误'], ['statistics', '全过程概览']].map(([key, label]) => <button key={key} className={`tab-btn${section === key ? ' active' : ''}`} onClick={() => setSection(key)}>{label}</button>)}</nav>
    <div ref={contentRef} className="workflow-panes slide-panes" data-sliding={panes.moving || undefined}>
    <div {...panes.paneProps('stages', 'grid')} className="workflow-stage-layout workflow-pane"><nav className="workflow-stage-nav" aria-label="七阶段导航">{stages.map((stage, index) => <button key={stage.id} className={selected?.id === stage.id ? 'active' : ''} aria-current={selected?.id === stage.id ? 'step' : undefined} onClick={() => { setSelectedId(stage.id); setFollowing(false) }}><span className={`stage-number ${stage.status}`}>{index + 1}</span><span><strong>{stage.name}</strong><small>{LABELS[stage.status] || stage.status}</small></span></button>)}</nav><div className="workflow-stage-content">{selected && <><header className="selected-stage-heading"><h3>{selected.name}</h3><span>{LABELS[selected.status] || selected.status}{selected.duration ? ` · ${selected.duration}` : ''}</span><button className="text-link" onClick={() => onShowStageInChat(selected.id)}>在对话中查看</button></header>{selected.status === 'running' && selected.summary && <p className="stage-output-summary">{readableText(selected.summary)}</p>}<StageCard key={selected.id} presentation="workflow" stage={selected} expanded onToggle={() => {}} onOpenAgent={openAgent} sourceScores={pipeline.sourceScores} data={data} onOpenData={onOpenData} onOpenInsights={() => onOpenData('analysis')} /></>}</div></div>
    <div {...panes.paneProps('logs', 'flex')} className="workflow-log-page workflow-pane">{stages.flatMap(stage => (stage.errors || []).map((error, index) => <div key={`${stage.id}-${index}`} className="resource-error">{stage.name} · {error.message}<button className="text-link" onClick={() => onShowStageInChat(stage.id)}>查看阶段</button></div>))}<LogDrawer fill open={panes.hasVisited('logs')} liveLogs={pipeline.logs} /></div>
    <div {...panes.paneProps('statistics')} className="workflow-scroll-page workflow-pane">{panes.hasVisited('statistics') && <ExecutionOverview task={task} pipeline={pipeline} stages={stages} />}</div>
    </div>
  </div>
}
