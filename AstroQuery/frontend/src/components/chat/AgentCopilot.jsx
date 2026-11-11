import { useCallback, useMemo } from 'react'
import { Icon } from '@/components/icons'
import AnswerBlocks from './AnswerBlocks'
import { useCopy } from './AnswerData'
import './researchAnswer.css'

function Turn({ question, options, chosen, latest, busy, action, taskId, dark, onChoose, onCite, onAsk, onRetry }) {
  const [copied, copy] = useCopy()
  const index = Math.max(0, options.indexOf(chosen))
  const generating = chosen?.status === 'generating'
  return <section className="research-turn" aria-label="追问">
    {question && <div className="research-user-message">{question.content}</div>}
    {chosen && <div className="research-response" data-answer-id={chosen.id} data-answer-state={chosen.status}>
      {generating && <div className="research-working" role="status"><span />{action || '正在准备回答'}</div>}
      <AnswerBlocks message={chosen} taskId={taskId} dark={dark} onCite={onCite} onAsk={onAsk} onRetry={onRetry} />
      {chosen.status !== 'complete' && !generating && <p className="research-quiet" role="status">
        {chosen.status === 'stopped' ? '已停止生成' : chosen.status === 'interrupted' ? '这轮生成中断' : chosen.message || '回答未能生成'}
      </p>}
      {!generating && <div className="research-turn-controls">
        {chosen.content && <button type="button" className="research-action" onClick={() => copy(chosen.content)}><Icon.Copy width={15} height={15} />{copied || '复制回答'}</button>}
        {latest && chosen.question_id && <button type="button" className="research-action" disabled={busy} onClick={() => onRetry(chosen.id)}>
          <Icon.Refresh width={15} height={15} />{chosen.status === 'complete' ? '重新回答' : '重试'}
        </button>}
        {options.length > 1 && <div className="research-versions" aria-label="回答版本">
          <button type="button" className="research-action" disabled={index === 0} aria-label="上一版回答" onClick={() => onChoose(question.id, options[index - 1].id)}><Icon.ChevronLeft width={16} height={16} /></button>
          <span>{index + 1} / {options.length}</span>
          <button type="button" className="research-action" disabled={index + 1 >= options.length} aria-label="下一版回答" onClick={() => onChoose(question.id, options[index + 1].id)}><Icon.ChevronRight width={16} height={16} /></button>
        </div>}
        {!!chosen.elapsed_seconds && <time>{chosen.elapsed_seconds.toFixed(1)} 秒</time>}
      </div>}
    </div>}
  </section>
}

export function visibleAnswers(rows, selected) {
  const turns = [], byQuestion = new Map()
  for (const row of rows) {
    if (row.role === 'user') {
      const entry = { key: row.id, question: row, options: [] }
      byQuestion.set(row.id, entry)
      turns.push(entry)
    } else if (row.question_id && byQuestion.has(row.question_id)) {
      byQuestion.get(row.question_id).options.push(row)
    } else if (row.role === 'assistant') {
      const last = turns.at(-1)
      if (!row.question_id && last?.question && !last.options.length) last.options.push(row)
      else turns.push({ key: row.id, options: [row] })
    }
  }
  return turns.map(turn => ({ ...turn, chosen: turn.options.find(option => option.id === selected[turn.key]) || turn.options.at(-1) }))
}

export default function AgentCopilot({ followup, taskId, scope, dark, onOpenDetail, onAsk }) {
  const { rows, selectedAnswers, busy, error, pending, choose, ask, retryConnection } = followup
  const turns = useMemo(() => visibleAnswers(rows, selectedAnswers), [rows, selectedAnswers])
  const open = useCallback((message, citationId) => onOpenDetail?.({
    type: 'agent-citation', messageId: message.id, citationId, taskId, scope: message.scope || scope,
  }), [onOpenDetail, taskId, scope])
  const retry = useCallback((retryOf, repairBlock) => ask({ retryOf, repairBlock }), [ask])
  if (!turns.length && !pending && !error) return null
  return <div className="research-copilot" aria-label="查询追问">
    <h2>追问</h2>
    {turns.map((turn, i) => <Turn key={turn.key} {...turn} taskId={taskId} dark={dark} latest={i === turns.length - 1}
      busy={busy} action={pending?.message?.id === turn.chosen?.id ? pending?.action : ''} onChoose={choose} onCite={open}
      onAsk={onAsk} onRetry={retry} />)}
    {pending && !pending.message && <p className="research-working" role="status"><span />正在开始追问…</p>}
    {error && <div className="research-local-error" role="status">{error}
      {!busy && <button type="button" className="research-action" onClick={retryConnection}>恢复连接</button>}
    </div>}
  </div>
}
