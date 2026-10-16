import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { eventHistoryUrl } from '@/services/api'
import { timingEvent, stageSeconds, taskSeconds } from '@/lib/executionFacts'
import { fmtDuration } from '@/lib/format'

const cache = new Map()
const labels = { completed:'已完成', running:'执行中', waiting:'未开始', skipped:'已跳过', error:'失败', cancelled:'已取消' }
export default function ExecutionOverview({ task, pipeline, stages }) {
  const [history, setHistory] = useState(cache.get(task?.task_id) || null), [error, setError] = useState(''), [version, setVersion] = useState(0), [now, setNow] = useState(Date.now())
  const terminal = ['completed','error','failed','cancelled'].includes(task?.status)
  useEffect(() => {
    if (!task || !terminal) return
    let alive = true
    const key = task.replay_of || task.task_id
    const read = async () => {
      try {
        const readEvents = async id => { const response = await fetch(eventHistoryUrl(id)); if (!response.ok) throw new Error(`事件读取失败 (${response.status})`); const body = await response.json(); return (body.events || []).map(timingEvent).filter(Boolean) }
        const current = await readEvents(task.task_id)
        const original = task.replay_of ? await readEvents(key) : current
        if (alive) { const value = { current, original }; cache.set(task.task_id, value); setHistory(value); setError('') }
      } catch (err) { if (alive) setError(err.message) }
    }
    if (cache.has(task.task_id) && !version) setHistory(cache.get(task.task_id)); else read()
    return () => { alive = false }
  }, [task?.task_id, terminal, version])
  useEffect(() => { if (terminal) return; const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer) }, [terminal])
  const live = pipeline.executionFacts || [], events = history?.current || live
  const total = taskSeconds(events, task, now)
  return <section className="execution-overview" data-component="execution-overview"><div className="kpi-card"><p className="kpi-label">{task?.replay_of ? '本次回放历时' : '任务历时'}</p><strong className="kpi-value-sm">{total.seconds != null && Number.isFinite(total.seconds) ? fmtDuration(total.seconds) : '未记录'}</strong><p className="hint">{total.basis}</p></div>
    {error && <div className="resource-error">{error}<Button variant="outline" size="sm" onClick={() => setVersion(value => value + 1)}>重试</Button></div>}
    <h3>{task?.replay_of ? '原任务阶段计时' : '全过程阶段概览'}</h3><table className="report-table"><thead><tr><th>处理阶段</th><th>状态</th><th>执行耗时</th></tr></thead><tbody>{stages.map(stage => { const duration = stageSeconds(task?.replay_of ? history?.original || [] : events, stage.id); return <tr key={stage.id}><td>{stage.name}</td><td>{labels[stage.status] || stage.status}</td><td>{duration != null ? fmtDuration(duration) : stage.status === 'running' ? '计时中' : !terminal && stage.status === 'completed' ? '完成后汇总' : '未记录'}</td></tr> })}</tbody></table><p className="hint">阶段计时读取真实执行记录；并行区间合并，回跳按实际记录累计，不与任务历时直接相加。</p>
  </section>
}
