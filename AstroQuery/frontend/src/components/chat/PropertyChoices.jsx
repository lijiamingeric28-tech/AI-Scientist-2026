import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { propertyChoices, publicCopy, scopeChoice } from '@/lib/queryChoices'
import './propertyChoices.css'

export function PropertyDefinition({ binding }) {
  const definition = binding.definition || {}
  const quantity = publicCopy(definition.explanation?.quantity)
  if (!quantity) return null
  return <details className="choice-definition"><summary aria-label={definition.name_cn + '的定义'}>定义</summary>
    <p lang={/[\u4e00-\u9fff]/u.test(quantity) ? 'zh' : 'en'}>{quantity}</p></details>
}

const omittableKinds = new Set(['unsupported_property', 'inapplicable_property', 'unsupported_unit', 'unsupported_filter'])

export default function PropertyChoices({ state, sending, submit }) {
  const { draft, pending: question } = state
  const storageKey = 'astro-draft-choice:' + state.task_id
  const signature = JSON.stringify([draft.target?.target_id, question.model_property_selection?.operation_id,
    state.omission_context_hash, question.property_catalog?.bindings.map(b => b.property_id)])
  const [selected, setSelected] = useState(() => {
    try {
      const old = JSON.parse(sessionStorage.getItem(storageKey))
      if (old?.signature === signature && Array.isArray(old.ids) && old.ids.every(id =>
        question.property_catalog?.bindings.some(b => b.property_id === id))) return old.ids
    } catch { /* Storage may be unavailable. The saved draft remains authoritative. */ }
    return draft.selected_property_ids || []
  })
  const [accepted, setAccepted] = useState([])
  const groups = propertyChoices(question, draft)
  const choices = groups.filter(g => g.options.length > 1)
  const singles = [...new Map(groups.filter(g => g.options.length === 1)
    .map(g => [g.options[0].binding.property_id, g.options[0]])).values()]
  const saved = draft.selected_property_ids || []
  const changed = selected.length !== saved.length || saved.some(id => !selected.includes(id))
  const omissions = draft.issues.filter(i => omittableKinds.has(i.kind) &&
    (i.status === 'open' || changed && i.status === 'accepted_omission'))
  const blocked = draft.issues.filter(i => i.status === 'open' &&
    !omittableKinds.has(i.kind) && !['ambiguous_property','property_count'].includes(i.kind))
  const ready = selected.length >= 1 && selected.length <= 5 && !blocked.length && omissions.every(i => accepted.includes(i.issue_id))
  function updateSelection(ids) {
    setAccepted([])
    setSelected(ids)
    try { sessionStorage.setItem(storageKey, JSON.stringify({signature, ids})) } catch { /* Optional local preferences. */ }
  }
  function option({binding, candidate}) {
    const {property_id: id, definition} = binding
    const checked = selected.includes(id)
    const summary = publicCopy(candidate?.summary)
    const symbol = (definition.aliases || []).filter(s => typeof s === 'string' && s !== definition.name_cn && s.length <= 14)
      .sort((a,b) => a.length - b.length)[0]
    const profile = binding.output_profile
    const unit = ['log10','ln'].includes(profile?.representation?.kind) ? null : profile?.unit?.canonical_symbol
    return <div key={id} className="choice-option" data-picked={checked}>
      <label><input type="checkbox" checked={checked} disabled={sending || (!checked && selected.length >= 5)}
        onChange={() => updateSelection(checked ? selected.filter(value => value !== id) : [...selected,id])}/>
        <span className="choice-name">{definition.name_cn}
          {symbol && <span className="choice-symbol">{symbol}</span>}</span>
        {unit && unit !== '1' && <span className="choice-unit">{unit}</span>}
        {summary && <span className="choice-note">{summary}</span>}
      </label><PropertyDefinition binding={binding}/>
    </div>
  }
  const target = draft.target
  const targetName = target?.user_mentions?.[0] || target?.main_id
  return <div className="property-choice">
    <header><h3>{targetName ? '你想查' + targetName + '的哪些性质？' : '你想查哪些性质？'}</h3>
      <span>可选 1–5 项</span></header>
    {choices.map((g, n) => {
      const main = g.options.filter(o => o.candidate?.match !== 'related')
      const other = main.length ? g.options.filter(o => o.candidate?.match === 'related') : []
      const matching = g.options.filter(o => o.candidate?.match === 'equivalent')
      const together = [...new Set([...selected, ...matching.map(o => o.binding.property_id)])]
      return <fieldset className="choice-group" key={g.text + n} disabled={sending}>
        <legend>{g.text==='可选性质'||g.text==='其他可选性质' ? g.text : '“' + g.text + '”按哪种定义查询？'}</legend>
        {matching.length>1 && <div className="choice-combine"><span>以下 {matching.length} 项都匹配你的原问，可分别查询。</span>
          <button type="button" disabled={together.length>5 || together.length===selected.length} onClick={()=>updateSelection(together)}>同时选这 {matching.length} 项</button></div>}
        {(main.length ? main : g.options).map(option)}
        {!!other.length && <details className="choice-alternatives" open={other.some(o => selected.includes(o.binding.property_id)) || undefined}>
          <summary>其他口径（{other.length}）</summary>{other.map(option)}</details>}
      </fieldset>
    })}
    {singles.length>0 && <fieldset className="choice-group" disabled={sending}>
      <legend>{choices.length ? '一同查询的性质' : '查询性质'}</legend>{singles.map(option)}</fieldset>}
    {omissions.length > 0 && <fieldset className="choice-scope" disabled={sending}><legend>本次查询范围</legend>
      {omissions.map(i => <label key={i.issue_id}><input type="checkbox" checked={accepted.includes(i.issue_id)} onChange={e => {
        setAccepted(ids => e.target.checked ? [...ids, i.issue_id] : ids.filter(id => id !== i.issue_id))
      }}/>{scopeChoice(i,draft)}</label>)}</fieldset>}
    {blocked.map(i => <p role="status" className="choice-blocker" key={i.issue_id}>{i.kind==='property_selection_incomplete'
      ? '“' + (i.request_text || '此项要求') + '”的候选尚未核实。请修改问题后再试。'
      : '请补充说明' + (publicCopy(i.request_text || i.description) ? '：' + publicCopy(i.request_text || i.description) : '这项要求') + '。'}</p>)}
    <div className="choice-submit"><span aria-live="polite">已选 {selected.length} 项</span>
      <Button variant="accent" disabled={sending || !ready} onClick={() => submit({type:'start_selected',
        property_ids:selected, omission_ids:omissions.map(i => i.issue_id), omission_context_hash:state.omission_context_hash})}>
        {sending ? '正在提交…' : '开始查询'}</Button></div>
  </div>
}
