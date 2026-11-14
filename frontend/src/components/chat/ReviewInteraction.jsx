import { useLayoutEffect, useState } from 'react'
import { reviewReceipt } from '@/lib/reviewReceipt'
import { Icon } from '@/components/icons'
import { StatusDot } from '@/components/status'
import { ReviewQuestion } from './RuntimeQuestion'
import ReviewReading from './ReviewReading'

const states = {pending:'等待判断',accepted:'原回答已接收',applied:'已应用并复检',
  application_failed:'应用未完成',closed_unanswered:'问题已撤回',resolved:'审核已处理'}
export default function ReviewInteraction({review, taskId, readOnly, gate, onSubmit, onReplaySubmit, receipts=[]}) {
  const isPending = review.status === 'pending'
  const [sending,setSending] = useState(false)
  const [open,setOpen] = useState(isPending)
  // Fold once when the answer is received. Later receipts must not close
  // a record that the user deliberately reopened to read.
  useLayoutEffect(() => {
    setOpen(isPending)
  }, [taskId, review.review_id, review.revision, review.basis_hash, isPending])
  const [error,setError] = useState('')
  const evidence = review.evidence_bundle || review.evidence || []
  const prepared = {...review,task_id:taskId,evidence_bundle:evidence,
    evidence_refs:review.evidence_refs||evidence.map(e=>({id:e.evidence_id})),correction_types:review.correction_types||[],
    allowed_actions:review.allowed_actions || (review.choices || []).map(c=>c.action)}
  const locked = readOnly && gate?.available && gate.review_id === review.review_id &&
    gate.review_revision === review.revision && gate.basis_hash === review.basis_hash
  const simulation = gate?.answer?.simulation || gate?.answer?.actor==='simulated_test_operator' ||
    review.answer?.simulation || review.answer?.actor==='simulated_test_operator'
  const submit = async value => {
    if (sending) return
    setSending(true);setError('')
    try { if (locked) onReplaySubmit(value); else await onSubmit(value) }
    catch(e) { setError(e.message) }
    finally { setSending(false) }
  }
  const receipt = receipts.find(r=>r.review_id===review.review_id)?.receipt
  const answerLabel = !isPending && reviewReceipt(review)?.answer
  return <details className="chat-interaction" data-state={isPending?'waiting':'completed'} data-review-id={review.review_id} aria-label="人工审核" open={open} onToggle={e=>{if(e.target===e.currentTarget)setOpen(e.currentTarget.open)}}>
    <summary className="chat-interaction-heading">
      {isPending?<StatusDot status="waiting" size={8}/>:<Icon.Check className="stage-check" aria-hidden="true"/>}
      <strong>人工审核</strong>
      <span className="review-heading-result">{isPending?(locked?'原答已预填，等待提交':'需要你的判断'):answerLabel||states[review.status]||'审核记录'}</span>
      <Icon.ChevronDown className="chat-chevron" aria-hidden="true"/>
    </summary>
    <div className="chat-interaction-body">
    {error && <p role="alert">{error}</p>}
    {isPending && (!readOnly || locked) ?
      <ReviewQuestion key={locked?gate.key:review.review_id+':'+review.revision} review={prepared}
        disabled={sending} simulation={simulation} replayGate={locked?gate:null} onSubmit={submit}/> :
      <>{open && <ReviewReading review={prepared} taskId={taskId}/>}
        {simulation&&<p>当时的模拟审核</p>}
        {review.answer?(review.answer.reason&&<p>{review.answer.reason}</p>):
          <p>{review.status==='closed_unanswered'?'此问题已撤回。':readOnly?'此时尚无原回答。':'答案等待应用。'}</p>}
        {receipt&&<p>{receipt.postcheck==='passed'?'答后复检已通过':receipt.postcheck==='failed'?'答后复检未通过':'应用结果已保存'}</p>}
      </>}
    </div>
  </details>
}
