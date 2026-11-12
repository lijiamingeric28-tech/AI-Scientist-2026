import { Icon } from '@/components/icons'
import { ADS_SORTS, papersValue } from '@/lib/retrievalPreferences'
import './settings.css'

export default function RetrievalPreferences({ value, onChange, disabled = false, id = 'retrieval', overridden = [], layout = 'compact' }) {
  const invalid = papersValue(value.papers_per_property) === null
  const papersOverridden = disabled || overridden.includes('literature_papers_per_property')
  const sortOverridden = disabled || overridden.includes('ads_sort')

  if (layout === 'settings') {
    return (
      <div className="settings-config-rows-group">
        <div className="settings-config-row">
          <div className="settings-config-row-label">
            <strong>每项性质的论文目标 (Papers per Property)</strong>
            <span>为每个待查询物理性质抓取的最大可读正文篇数（范围 1–40 篇）</span>
            {overridden.includes('literature_papers_per_property') && (
              <span style={{ color: 'var(--seed-accent)' }}>此项当前由启动环境配置提供</span>
            )}
            {invalid && (
              <span id={`${id}-error`} className="settings-inline-error" role="alert">
                请输入 1–40 的整数。
              </span>
            )}
          </div>
          <div className="settings-config-row-control">
            <div className="settings-segmented-group" role="group" aria-label="论文目标快捷选择">
              {[10, 15, 20].map(n => (
                <button
                  type="button"
                  key={n}
                  disabled={papersOverridden}
                  aria-pressed={Number(value.papers_per_property) === n}
                  className={`settings-segmented-btn ${Number(value.papers_per_property) === n ? 'is-active' : ''}`}
                  onClick={() => onChange({ ...value, papers_per_property: n })}
                >
                  <span>{n}</span>
                </button>
              ))}
            </div>
            <div className={`settings-pill-input-group is-numeric${papersOverridden ? ' is-disabled' : ''}`}>
              <input
                id={`${id}-papers`}
                type="number"
                min="1"
                max="40"
                step="1"
                inputMode="numeric"
                className="settings-pill-input"
                aria-label="每项性质的论文目标"
                aria-invalid={invalid || undefined}
                aria-describedby={invalid ? `${id}-error` : undefined}
                disabled={papersOverridden}
                value={value.papers_per_property}
                onChange={e => onChange({ ...value, papers_per_property: e.target.value })}
              />
            </div>
            <span className="settings-unit-suffix">篇</span>
          </div>
        </div>

        <div className="settings-config-row">
          <div className="settings-config-row-label">
            <strong>ADS 论文排序方式 (ADS Sort Order)</strong>
            <span>影响 NASA ADS 文献检索的候选排序优先级；同一篇论文可用于多项性质</span>
            {overridden.includes('ads_sort') && (
              <span style={{ color: 'var(--seed-accent)' }}>此项当前由启动环境配置提供</span>
            )}
          </div>
          <div className="settings-config-row-control">
            <div className="theme-select-container">
              <select
                id={`${id}-sort`}
                className="settings-select-control theme-preset-select"
                value={value.ads_sort}
                disabled={sortOverridden}
                aria-label="ADS 论文排序"
                onChange={e => onChange({ ...value, ads_sort: e.target.value })}
              >
                {ADS_SORTS.map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
              <Icon.ChevronDown className="theme-select-chevron" />
            </div>
          </div>
        </div>
      </div>
    )
  }

  return <div className="retrieval-preferences">
    <div className="preference-setting">
      <label htmlFor={`${id}-papers`}>每项性质的论文目标</label>
      <div className="paper-target-control"><div className="paper-presets" aria-label="论文目标快捷选择">
        {[10, 15, 20].map(n => <button type="button" key={n} disabled={papersOverridden} aria-pressed={Number(value.papers_per_property) === n} onClick={() => onChange({ ...value, papers_per_property: n })}>{n}</button>)}
      </div><div className="paper-number"><input id={`${id}-papers`} type="number" min="1" max="40" step="1" inputMode="numeric" aria-invalid={invalid || undefined} aria-describedby={invalid ? `${id}-error` : undefined} disabled={papersOverridden} value={value.papers_per_property} onChange={e => onChange({ ...value, papers_per_property: e.target.value })}/><span>篇</span></div></div>
      {invalid && <p id={`${id}-error`} className="preference-error" role="alert">请输入 1–40 的整数。</p>}
    </div>
    <div className="preference-setting"><label htmlFor={`${id}-sort`}>ADS 论文排序</label>
      <select id={`${id}-sort`} value={value.ads_sort} disabled={sortOverridden} onChange={e => onChange({ ...value, ads_sort: e.target.value })}>{ADS_SORTS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
    </div>
  </div>
}
