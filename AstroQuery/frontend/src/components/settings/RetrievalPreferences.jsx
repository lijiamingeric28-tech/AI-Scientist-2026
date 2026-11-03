import { ADS_SORTS, papersValue } from '@/lib/retrievalPreferences'

export default function RetrievalPreferences({ value, onChange, disabled = false, id = 'retrieval', overridden = [] }) {
  const invalid = papersValue(value.papers_per_property) === null
  return <div className="retrieval-preferences">
    <div className="preference-setting">
      <label htmlFor={`${id}-papers`}>每项性质的论文目标</label>
      <div className="paper-target-control"><div className="paper-presets" aria-label="论文目标快捷选择">
        {[10, 15, 20].map(n => <button type="button" key={n} disabled={disabled || overridden.includes('literature_papers_per_property')} aria-pressed={Number(value.papers_per_property) === n} onClick={() => onChange({ ...value, papers_per_property: n })}>{n}</button>)}
      </div><div className="paper-number"><input id={`${id}-papers`} type="number" min="1" max="40" step="1" inputMode="numeric" aria-invalid={invalid || undefined} aria-describedby={invalid ? `${id}-error` : undefined} disabled={disabled || overridden.includes('literature_papers_per_property')} value={value.papers_per_property} onChange={e => onChange({ ...value, papers_per_property: e.target.value })}/><span>篇</span></div></div>
      {invalid && <p id={`${id}-error`} className="preference-error" role="alert">请输入 1–40 的整数。</p>}
    </div>
    <div className="preference-setting"><label htmlFor={`${id}-sort`}>ADS 论文排序</label>
      <select id={`${id}-sort`} value={value.ads_sort} disabled={disabled || overridden.includes('ads_sort')} onChange={e => onChange({ ...value, ads_sort: e.target.value })}>{ADS_SORTS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
    </div>
  </div>
}
