import { useEffect, useMemo, useState } from 'react'
import { useRememberedState } from '@/hooks/useViewMemory'
import ProcessingTimeline from './ProcessingTimeline'
import PropertyInsightCards from './PropertyInsightCards'
import { activityLabels, displayText, stateText, titleText } from '@/lib/researchDisplay'

const names = {
  request_materials: '请求与材料',
  extraction: '提取',
  quality_cleaning: '质检与清洗',
  comparison_review: '对照与审核',
  delivery: '交付',
  insights: '洞察',
}
const stages = {
  materials: '检索与材料',
  extraction: '提取',
  quality: '质检',
  cleaning: '清洗',
  comparison: '对照',
  insights: '洞察',
}
const tabAliases = { modifications: 'trace', sources: 'comparison' }
const countText = (cell) =>
  cell.count == null
    ? '历史未记录'
    : cell.count + (cell.total == null ? '' : ' / ' + cell.total) + ' ' + (cell.unit || '')

function ScoreBasis({ component: c }) {
  return (
    <div className="score-basis">
      {c.property_coverage && (
        <p>
          有交付测量的性质 {c.property_coverage.covered} / {c.property_coverage.requested}
        </p>
      )}
      {c.readable_per_property && (
        <p>各性质可读篇数 {Object.values(c.readable_per_property).join('、')}</p>
      )}
      {c.materials?.length > 0 && (
        <details>
          <summary>{c.materials.length} 份材料的阅读范围</summary>
          {c.materials.map((m, i) => (
            <p key={i}>
              材料 {i + 1} · {m.completed_ranges} / {m.expected_ranges} 个获准范围
            </p>
          ))}
        </details>
      )}
      {c.candidate_roots != null && (
        <p>
          原文质检 {c.concluded_roots}/{c.candidate_roots} 项根问题
        </p>
      )}
      {c.eligible_records != null && (
        <p>
          主值处理或核验不变 {c.processed_or_no_change_verified}/{c.eligible_records} 条原报
        </p>
      )}
      {c.properties_with_data != null && (
        <p>
          已核对性质 {c.properties_checked}/{c.properties_with_data}
        </p>
      )}
      {c.necessary_reviews != null && (
        <p>
          必要审核应用并复检 {c.answers_applied_rechecked}/{c.necessary_reviews}
        </p>
      )}
      {c.same_snapshot_exports_verified != null && (
        <p>同快照交付格式验证 {c.same_snapshot_exports_verified ? '通过' : '尚未通过'}</p>
      )}
      {c.requested_properties != null && (
        <p>
          合格洞察 {Array.isArray(c.qualified_properties)?c.qualified_properties.length:(c.qualified_properties ?? '尚未生成')}/{c.requested_properties} 项性质
        </p>
      )}
      <p>
        {c.state === 'deferred_by_scope' ? '本轮范围未启用洞察' : c.state === 'no_materials'
          ? '此范围未取得材料'
          : c.earned == null
            ? '此项尚未汇总'
            : c.earned === c.weight
              ? '本项已完成报告要求的范围'
              : '本项存在未完成范围，口径见上述指标'}
      </p>
    </div>
  )
}

export default function TaskAnalysisV1({
  quality,
  records = [],
  sources = [],
  insights,
  differences,
  matrix = [],
  activity = [],
  onOpenRecord,
  onLocateRecord,
  onOpenRecords,
  onOpenKnowledge,
  requestTab,
  requestProperty,
  requestKey,
  memory = {},
  resourceErrors = {},
  onRetry,
}) {
  const [tab, setTab] = useRememberedState(memory, 'tab', 'overview'),
    [property, setProperty] = useRememberedState(memory, 'property', 'all'),
    [action, setAction] = useRememberedState(memory, 'action', 'all')
  const [source, setSource] = useState('all'),
    [date, setDate] = useState(''),
    [effect, setEffect] = useState('all'),
    [page, setPage] = useState(1)
  useEffect(() => {
    if ((!requestTab && !requestProperty) || memory.appliedRequest === requestKey) return
    memory.appliedRequest = requestKey
    if (requestTab) setTab(tabAliases[requestTab] || requestTab)
    if (requestProperty) setProperty(requestProperty)
  }, [requestTab, requestProperty, requestKey])
  useEffect(() => setPage(1), [property, action, source, date, effect])
  const report = quality.report
  const propertyNames = Object.fromEntries([
    ...records.map((r) => [r.property_id, r.field_name]),
    ...matrix.map((r) => [r.property_id, r.name]),
  ])
  const groups = differences?.archive_groups || report.archive_groups || []
  const checks = differences?.checks || report.comparison_checks || []
  const selected = activity.filter(
    (a) =>
      (property === 'all' || a.property_id === property) &&
      (action === 'all' || a.kind === action) &&
      (source === 'all' || a.source_ids?.includes(source)) &&
      (!date || (a.at && new Date(a.at).toLocaleDateString('sv-SE') === date)) &&
      (effect === 'all' ||
        (effect === 'changed' && a.actual_change) ||
        (effect === 'no_change' && a.status === 'no_change')),
  )
  const contributions = useMemo(
    () =>
      sources
        .map((s) => ({ ...s, records: records.filter((r) => r.source_id === s.source_id) }))
        .filter((s) => s.records.length),
    [sources, records],
  )
  const openRecord = (id) => onLocateRecord?.(id)
  const selectCoverage = (row, key) => {
    setProperty(row.property_id)
    if (key === 'insights') setTab('insights')
    else if (key === 'comparison') setTab('comparison')
    else if (key === 'materials' || key === 'extraction') onOpenRecords?.(row.property_id)
    else {
      setTab('trace')
      setAction(key === 'quality' ? 'quality' : 'representation')
    }
  }
  return (
    <div className="research-analysis">
      <nav className="data-tabs" aria-label="质量与洞察分区">
        {[
          ['overview', '任务评分'],
          ['trace', '处理溯源'],
          ['comparison', '对照与覆盖'],
          ['insights', '科学洞察'],
        ].map(([id, label]) => (
          <button
            className={'tab-btn' + (tab === id ? ' active' : '')}
            key={id}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>
      {Object.entries(resourceErrors)
        .filter(
          ([key, value]) =>
            value &&
            ((tab === 'insights' && key === 'insights') ||
              (tab === 'trace' && key === 'activity') ||
              (tab === 'comparison' && ['matrix', 'differences'].includes(key))),
        )
        .map(([key, value]) => (
          <p className="resource-error" role="alert" key={key}>
            此部分读取失败。
            <button className="text-link" onClick={() => onRetry?.(key)}>
              重新读取
            </button>
          </p>
        ))}
      {tab === 'overview' && (
        <section className="research-score-overview">
          <div className="task-quality-summary">
            <div>
              <h3>本次查询完成度</h3>

            </div>
            <strong>
              {report.score == null ? '待汇总' : report.score}
              <small> / 100</small>
            </strong>
            <span>
              {report.property_coverage?.covered}/{report.property_coverage?.requested}{' '}
              项性质有交付测量
            </span>
            {report.possible_points!==100&&<p>原始计分 {report.earned_points} / {report.possible_points}，总分采用报告的折算结果。</p>}
          </div>
          <div className="research-score-components">
            {report.components.map((component) => {
              const c =
                component.key === 'insights' && report.status === 'pending'
                  ? { ...component, earned: null }
                  : component
              return (
                <details key={c.key}>
                  <summary>
                    <span>{names[c.key] || '评分分项'}</span>
                    <meter
                      min="0"
                      max={c.weight}
                      value={c.earned ?? 0}
                      aria-label={names[c.key] || '评分分项'}
                      aria-valuetext={
                      c.earned == null ? (c.state==='deferred_by_scope'?'本轮不计入':'待汇总') : c.earned.toFixed(2) + ' / ' + c.weight
                      }
                    />
                    <strong>
                    {c.earned == null ? (c.state==='deferred_by_scope'?'本轮不计入':'待汇总') : c.earned.toFixed(2)} <span>/ {c.weight}</span>
                    </strong>
                  </summary>
                  <ScoreBasis component={c} />
                </details>
              )
            })}
          </div>
          <h3>材料覆盖</h3>
          <div className="research-readable-list">
            {Object.entries(report.readable_per_property || {}).map(([pid, n]) => (
              <div key={pid}>
                <span>{propertyNames[pid] || '本轮性质'}</span>
                <strong>{n} 篇可读正文</strong>
              </div>
            ))}
          </div>
          <button className="text-link" onClick={() => setTab('comparison')}>
            查看各性质的处理覆盖与对照
          </button>
        </section>
      )}
      {tab === 'trace' && (
        <section>
          <div className="research-toolbar">
            <select
              aria-label="溯源性质"
              value={property}
              onChange={(e) => setProperty(e.target.value)}
            >
              <option value="all">全部性质</option>
              {Object.entries(propertyNames).map(([id, name]) => (
                <option value={id} key={id}>
                  {name}
                </option>
              ))}
            </select>
            <select
              aria-label="处理动作"
              value={action}
              onChange={(e) => setAction(e.target.value)}
            >
              <option value="all">全部动作</option>
              {Object.entries(activityLabels).map(([id, label]) => (
                <option value={id} key={id}>
                  {label}
                </option>
              ))}
            </select>
            <select
              aria-label="溯源来源"
              value={source}
              onChange={(e) => setSource(e.target.value)}
            >
              <option value="all">全部来源</option>
              {sources.map((s) => (
                <option value={s.source_id} key={s.source_id}>
                  {titleText(s)}
                </option>
              ))}
            </select>
            <label>
              处理日期 <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </label>
            <select
              aria-label="值变更范围"
              value={effect}
              onChange={(e) => setEffect(e.target.value)}
            >
              <option value="all">全部处理</option>
              <option value="changed">只看实际变化</option>
              <option value="no_change">核实无需改变</option>
            </select>
          </div>
          <p className="research-counts">
            {selected.length} 项处理活动 · 涉及{' '}
            {new Set(selected.flatMap((a) => a.measurement_ids)).size} 条交付测量
          </p>
          <ProcessingTimeline
            entries={selected.slice((page - 1) * 20, page * 20)}
            records={records}
            onOpenRecord={openRecord}
          />
          <div className="research-pagination">
            <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              上一页
            </button>
            <span>
              {page} / {Math.max(1, Math.ceil(selected.length / 20))}
            </span>
            <button disabled={page * 20 >= selected.length} onClick={() => setPage((p) => p + 1)}>
              下一页
            </button>
          </div>
        </section>
      )}
      {tab === 'comparison' && (
        <section>
          <h3>按性质查看处理覆盖</h3>
          <div className="research-table-scroll">
            <table className="coverage-matrix">
              <thead>
                <tr>
                  <th>性质</th>
                  {Object.values(stages).map((label) => (
                    <th key={label}>{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.map((row) => (
                  <tr key={row.property_id}>
                    <th scope="row">{row.name}</th>
                    {Object.keys(stages).map((key) => (
                      <td key={key}>
                        <button
                          className="coverage-cell"
                          data-state={row.cells[key].state}
                          onClick={() => selectCoverage(row, key)}
                        >
                          <strong>{stateText(row.cells[key].state)}</strong>
                          <span>{countText(row.cells[key])}</span>
                        </button>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!matrix.length && <p>本修订未保存性质级覆盖摘要。</p>}
          {matrix.some((row) => row.evidence) && (
            <details>
              <summary>证据定位范围</summary>
              <p>按测量计数，同一记录可同时具有页码、摘录与区域定位。</p>
              <div className="research-table-scroll">
                <table className="coverage-matrix">
                  <thead>
                    <tr>
                      <th>性质</th>
                      <th>原文页码</th>
                      <th>原文摘录</th>
                      <th>原生文本区域</th>
                      <th>表格行列</th>
                    </tr>
                  </thead>
                  <tbody>
                    {matrix.map((row) => (
                      <tr key={row.property_id}>
                        <th>{row.name}</th>
                        {['page', 'excerpt', 'region', 'table'].map((key) => (
                          <td key={key}>{row.evidence?.[key] ?? '历史未记录'} 条</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
          <details>
            <summary>尚待完善的处理范围</summary>
            {matrix.flatMap((row) =>
              Object.entries(row.cells)
                .filter(([, cell]) => !['complete', 'not_applicable'].includes(cell.state))
                .map(([key, cell]) => (
                  <p key={row.property_id + key}>
                    <button className="text-link" onClick={() => selectCoverage(row, key)}>
                      {row.name} · {stages[key]} · {stateText(cell.state)}
                    </button>{' '}
                    {countText(cell)}
                  </p>
                )),
            )}
          </details>
          <div className="research-section-heading">
            <h3>重复归档与差异</h3>
            <span>
              {groups.length} 个归档组 ·{' '}
              {new Set(groups.flatMap((g) => g.member_refs.map((r) => r.id))).size} 条成员原报
            </span>
          </div>
          <select
            aria-label="对照性质"
            value={property}
            onChange={(e) => setProperty(e.target.value)}
          >
            <option value="all">全部性质</option>
            {Object.entries(propertyNames).map(([id, name]) => (
              <option value={id} key={id}>
                {name}
              </option>
            ))}
          </select>
          {Object.entries(propertyNames)
            .filter(([pid]) => property === 'all' || pid === property)
            .map(([pid, name]) => {
              const check = checks.find((c) => c.property_id === pid),
                ownGroups = groups.filter((g) => g.property_id === pid)
              const human = activity.filter((a) => a.kind === 'human' && a.property_id === pid)
              return (
                <section className="property-comparison" key={pid}>
                  <div className="research-section-heading">
                    <h4>{name}</h4>
                    <span>{check ? stateText(check.state) : '未完成核对'}</span>
                  </div>
                  {ownGroups.map((g) => (
                    <details key={g.group_id}>
                      <summary>同次测量重复记载 · {g.member_refs.length} 条</summary>
                      <p>{g.reason}</p>
                      <div className="research-links">
                        {g.member_refs.map((ref) => {
                          const r = records.find((x) => x.record_id === ref.id)
                          return (
                            <button
                              key={ref.id}
                              className="text-link"
                              onClick={() => openRecord(ref.id)}
                            >
                              {r ? r.field_value + ' ' + (r.field_unit || '') : '原报'} · 查看证据
                            </button>
                          )
                        })}
                      </div>
                    </details>
                  ))}
                  {(check?.suspicions || []).map((s, i) => (
                    <div className="comparison-question" key={s.group_id || i}>
                      <h5>疑似差异与可比条件</h5>
                      <p>{s.question || s.reason}</p>
                      <div className="research-links">
                        {(s.measurement_refs || []).map((ref) => {
                          const r = records.find((x) => x.record_id === ref.id)
                          return (
                            <button
                              className="text-link"
                              key={ref.id}
                              onClick={() => openRecord(ref.id)}
                            >
                              {r ? r.source.raw_value + ' ' + (r.source.unit || '') : '查看原报'}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                  {human.length > 0 && (
                    <ProcessingTimeline
                      entries={human}
                      records={records}
                      onOpenRecord={openRecord}
                    />
                  )}
                  {!check && <p>此性质没有完整核对报告。</p>}
                  {check &&
                    !(check.duplicates || []).length &&
                    !(check.suspicions || []).length && (
                      <p>
                        {check.state === 'checked'
                          ? '已核范围未形成归档组或疑似矛盾。'
                          : '本修订未保存完整对照结论。'}
                      </p>
                    )}
                </section>
              )
            })}
          <h3>来源 × 性质贡献</h3>
          <p className="research-counts">按进入本修订的测量计数</p>
          <div className="research-table-scroll">
            <table className="contribution-matrix">
              <thead>
                <tr>
                  <th>实际贡献来源</th>
                  {Object.entries(propertyNames).map(([pid, name]) => (
                    <th key={pid}>{name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {contributions.map((s) => (
                  <tr key={s.source_id}>
                    <th scope="row">{titleText(s)}</th>
                    {Object.keys(propertyNames).map((pid) => {
                      const own = s.records.filter((r) => r.property_id === pid)
                      return (
                        <td key={pid}>
                          {own.length ? (
                            <button
                              className="text-link"
                              onClick={() => onOpenRecords?.(pid, s.source_id)}
                            >
                              {own.length} 条
                            </button>
                          ) : (
                            '—'
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {tab === 'insights' && (
        <section>
          {insights?.cards?.length ? (
            <PropertyInsightCards
              report={
                property === 'all'
                  ? insights
                  : { ...insights, cards: insights.cards.filter((c) => c.property_id === property) }
              }
              records={records}
              onOpenRecord={onOpenRecord}
              onOpenKnowledge={onOpenKnowledge}
            />
          ) : (
            <p>
              {insights?.status === 'pending'
                ? '本修订洞察待生成。'
                : insights?.generation_enabled === false
                  ? '本任务未启用洞察。'
                  : '本修订未保存科学洞察。'}
            </p>
          )}
          {property !== 'all' && (
            <button className="text-link" onClick={() => setProperty('all')}>
              查看全部性质洞察
            </button>
          )}
        </section>
      )}
    </div>
  )
}
