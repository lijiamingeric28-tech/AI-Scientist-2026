import { useEffect, useRef, useState } from 'react'
import PropertyChoices from './PropertyChoices'
import { Button } from '@/components/ui/button'
import ReviewCorrection, { useCorrection } from './ReviewCorrection'
import ReviewReading from './ReviewReading'
import { reviewRows } from '@/lib/scienceReading'

export function ReviewQuestion({ review, onSubmit, disabled, simulation, replayGate = null }) {
  const locked = !!replayGate
  const formKey=`astro-review:${review.task_id}:${review.review_id}:${review.revision}`
  const read=()=>{try{return JSON.parse(sessionStorage.getItem(formKey)||'{}')}catch{return {}}}
  const [action,setAction]=useState(()=>locked ? replayGate.answer.action : read().action|| (review.allowed_actions.includes(review.rejected_answer?.action)?review.rejected_answer.action:'')),[reason,setReason]=useState(()=>locked ? '' : read().reason||review.rejected_answer?.reason||'')
  useEffect(()=>{if(!locked)sessionStorage.setItem(formKey,JSON.stringify({action,reason}))},[formKey,action,reason,locked])
  const [correctionTarget,setCorrectionTarget] = useState(review.scope?.measurement_ids?.[0] || '')
  const selectedOriginal = review.record_interpretations?.[correctionTarget]
  const editingReview = selectedOriginal ? {...review,current_interpretation:selectedOriginal.proposal,correction_target_id:correctionTarget} : review
  const editor = useCorrection(editingReview, {readOnly:locked})
  const choiceName = a => review.choices?.find(c=>c.action===a)?.label || ({
    confirm:'确认当前解释',correct:'按原件更正',not_supported:'原件不支持该解释',unable:'证据不足，暂不判断',
  })[a] || '查看原回答'
  return <section className="review-question">
    {simulation && <p className="hint">{locked ? '当时的模拟审核' : '模拟审核'}</p>}
    <ReviewReading review={review} taskId={review.task_id} hideTitle={true}>
    {review.validation_feedback && <p role="alert">{review.validation_feedback.message}</p>}
    {locked ? <label>原审核选择 <select aria-label="审核判断" disabled value={action}>
      {review.allowed_actions.map(a=><option key={a} value={a}>{choiceName(a)}</option>)}</select></label> :
      <fieldset className="review-options"><legend>你的判断</legend>{review.allowed_actions.map(a=>
        <label key={a}><input type="radio" name={formKey} value={a} checked={action===a} disabled={disabled}
          onChange={()=>setAction(a)}/><span>{choiceName(a)}</span></label>)}</fieldset>}
    {review.choices?.find(c => c.action === action)?.impact && <p className="hint">此选择的影响：{review.choices.find(c => c.action === action).impact}</p>}
    {!locked && action === 'correct' && review.issue_kind === 'comparison_contradiction' && <label>需要修正的记录 <select value={correctionTarget} onChange={event => setCorrectionTarget(event.target.value)}>{reviewRows(review).map((r,i) => <option key={r.id} value={r.id}>记录 {i+1} · {r.value} {r.unit} {r.role}</option>)}</select></label>}
    {!locked && action === 'correct' && <ReviewCorrection review={editingReview} editor={editor} />}
    {locked && replayGate.answer.correction && <details><summary>原审核填写的更正</summary><p>{({correct_value:'更正主值',correct_unit:'更正单位',correct_uncertainty:'更正不确定度',correct_context:'更正测量条件'})[replayGate.answer.correction.type]}</p>
      {replayGate.answer.correction.raw_value && <p>原报 {replayGate.answer.correction.raw_value}</p>}
      {replayGate.answer.correction.unit && <p>单位 {replayGate.answer.correction.unit}</p>}
      {(replayGate.answer.correction.components || replayGate.answer.correction.conditions || []).map((c,i)=><p key={i}>{c.raw_text}</p>)}
      {replayGate.answer.correction.quote && <blockquote>{replayGate.answer.correction.quote}</blockquote>}</details>}
    {!locked && <label style={{ display: 'block', margin: '8px 0' }}>依据{action === 'unable' ? '（可不填）' : ''} <textarea aria-label="审核依据" value={reason} onChange={event => setReason(event.target.value)} maxLength={16000} /></label>}
    {locked ? <button type="button" className="hitl-submit-btn" onClick={()=>onSubmit(replayGate.key)}>提交并继续回放</button> :
    <button type="button" className="hitl-submit-btn" disabled={disabled || !action || action !== 'unable' && !reason.trim() || action === 'correct' && !editor.quote.trim()} onClick={() => onSubmit({ review_id: review.review_id, action, reason,
      ...(review.choices?.find(c => c.action === action)?.comparison_outcome ? {comparison_outcome: review.choices.find(c => c.action === action).comparison_outcome} : {}),
      ...(action === 'correct' ? { correction: editor.correction, ...(review.issue_kind === 'comparison_contradiction' ? {correction_measurement_id:correctionTarget} : {}) } : {}) })}>提交判断并复检</button>}

    </ReviewReading>
  </section>
}

export default function RuntimeQuestion({ payload, onSubmit }) {
  const state = payload.state, question = state.pending
  const [text, setText] = useState(''), [sending, setSending] = useState(false), [error, setError] = useState('')
  const busy = useRef(false)
  const submit = async action => {
    if (busy.current) return
    busy.current = true; setSending(true); setError('')
    try { await onSubmit(action); setText('') }
    catch (err) { setError(err.message) }
    finally { busy.current = false; setSending(false) }
  }
  useEffect(() => { setError('') }, [question?.question_id])
  const paused = ['paused', 'interrupted'].includes(state.lifecycle)
  const hasTarget = !!state.draft?.target
  const targetChoices = question?.candidate_targets || []
  return <section className="query-question draft-question" aria-label="查询确认">
    {(error || payload.error) && <p role="alert" className="resource-error">{error || payload.error}</p>}
    {paused ? <><h3>查询已暂停</h3><div className="stage-links">
      {state.query_ref ? <Button disabled={sending} onClick={() => submit({ control: 'continue' })}>继续执行</Button> : state.draft && <>
        <Button disabled={sending} onClick={() => submit(state.draft.status==='paused'?{ type: 'continue_editing' }:{control:'continue'})}>继续编辑</Button>
        {state.draft.last_error && <Button disabled={sending} onClick={() => submit({ type: state.draft.pause_reason === 'registry_unavailable' ? 'reload_registry' : 'retry_service', error_id: state.draft.last_error.code })}>重试未完成的准备</Button>}
      </>}
      <Button disabled={sending} variant="outline" onClick={() => submit({ control: 'cancel' })}>取消任务</Button>
    </div></> : <>
      {question && !hasTarget && <><h3>{targetChoices.length ? '你指的是哪一个天体？' : '请补充天体名称'}</h3>
        {targetChoices.length ? <div className="stage-links">{targetChoices.map(target =>
          <Button key={target.target_id} variant="outline" disabled={sending} onClick={() => submit({ type: 'select_target', candidate_id: target.target_id })}>
            {target.main_id} · {target.primary_otype}</Button>)}</div> : <p>输入这个天体的名称或目录编号。</p>}</>}
      {question && hasTarget && <PropertyChoices key={question.question_id} state={state} sending={sending} submit={submit}/>}
      {!state.query_ref && question && <div className="draft-secondary">
        <details className="draft-edit" open={!hasTarget && !targetChoices.length || undefined}><summary>修改问题</summary>
          <form onSubmit={event => { event.preventDefault(); if (text.trim()) submit({ type: 'submit_text', text }) }}>
            <label>补充或修改你的要求<input aria-label="编辑查询草稿" value={text} disabled={sending} onChange={event => setText(event.target.value)} /></label>
            <Button disabled={sending || !text.trim()} variant="outline" type="submit">更新问题</Button>
          </form></details>
        <Button variant="ghost" disabled={sending} onClick={()=>submit({control:'pause'})}>暂时退出</Button>
      </div>}
      {state.reviews.some(r=>r.status==='pending')&&<h3>有 {state.reviews.filter(r=>r.status==='pending').length} 项待判断</h3>}
      {state.reviews.filter(review => review.status === 'pending').map(review => <ReviewQuestion key={`${review.review_id}:${review.revision}`} review={review} onSubmit={submit} disabled={sending} simulation={state.review_actor?.simulation} />)}
    </>}
  </section>
}
