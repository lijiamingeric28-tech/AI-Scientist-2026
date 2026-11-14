import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { DefinitionNote } from './ReadableContent'
import EvidenceSource from './EvidenceSource'
import { typedValueText } from '@/lib/valueDisplay'
import { displayText, titleText, stateText } from '@/lib/researchDisplay'
import { measurementRole, readingConditions } from '@/lib/scienceReading'

const roles = { stat: '统计误差', sys: '系统误差', total: '原文总误差', unspecified: '原文误差' }
const errorKinds = {
  symmetric_delta: '对称误差',
  asymmetric_delta: '非对称误差',
  interval_endpoints: '区间端点',
  relative: '相对误差',
  percent: '百分比误差',
  variance: '方差',
  inverse_variance: '逆方差',
  covariance: '协方差',
  correlation: '相关系数',
  other_reported: '原文误差形式',
}
const meanings = {
  reported_error: '原文报告误差',
  standard_uncertainty: '标准不确定度',
  expanded_uncertainty: '扩展不确定度',
  confidence_interval: '置信区间',
  credible_interval: '可信区间',
  quantile_bounds: '分位数界限',
  unspecified: '统计含义未注明',
}
const sides = { minus: '负侧', plus: '正侧', delta: '幅度', lower: '下端点', upper: '上端点' }
const errorText = (value) =>
  Array.isArray(value?.matrix)
    ? value.matrix.map(row=>row.map(cell=>cell??'未报告').join('  ')).join('\n')
    : value?.kind === 'interval'
      ? typedValueText(value)
      : Object.entries(value || {})
        .filter(([key]) => !['kind', 'lower_closed', 'upper_closed'].includes(key))
        .map(([key, n]) => (sides[key] || key) + ' ' + (n ?? '未报告'))
        .join('；')

export function UncertaintyComponents({ record }) {
  const native = record.source.uncertainty || {}
  if (!native.components?.length)
    return (
      <p>
        {native.state === 'not_reported'
          ? '原文未报告不确定度'
          : native.state === 'not_applicable'
            ? '此记录不适用误差分量'
            : '误差含义待核实'}
      </p>
    )
  return (
    <div className="research-uncertainties">
      {native.components.map((component) => {
        const converted = record.derived?.uncertainty_typed?.components?.find(
          (c) => c.source_component_id === component.component_id,
        )
        const declared = record.uncertainty_units?.[component.component_id]
        const unit =
          component.kind === 'percent'
            ? '%'
            : component.kind === 'relative'
              ? '相对原报基准'
              : displayText(
                  declared ??
                    (['symmetric_delta', 'asymmetric_delta'].includes(component.kind)
                      ? record.source.unit
                      : null),
                )
        return (
          <section className="uncertainty-component" key={component.component_id}>
            <div className="research-section-heading">
              <h4>{roles[component.role] || '独立误差分量'}</h4>
              {converted?.status === 'failed' && <span>误差处理未完成</span>}
            </div>
            {(!['symmetric_delta','asymmetric_delta'].includes(component.kind) || component.raw_label && component.raw_label !== 'unspecified') && <p>
              {!['symmetric_delta','asymmetric_delta'].includes(component.kind) && (errorKinds[component.kind] || '原文误差形式')}
              {component.raw_label && component.raw_label !== 'unspecified' && ' · ' + component.raw_label}
            </p>}
            {component.values && (
              <p className="research-error-value">
                {component.kind === 'symmetric_delta'
                  ? '±' + component.values.delta
                  : errorText(component.values)}{' '}
                <span>{unit}</span>
              </p>
            )}
            {component.statistical_meaning && !['reported_error','unspecified'].includes(component.statistical_meaning) && <p>{meanings[component.statistical_meaning] || '原文报告的不确定度'}</p>}
            {component.level?.raw_text && <p>原文置信水平 {component.level.raw_text}</p>}
            {converted?.output_component && (
              <p>
                处理后 {errorText(converted.output_component.values)}{' '}
                {converted.unit_definition?.canonical_symbol ||
                  record.derived?.coordinate_units?.target}
              </p>
            )}
            {!converted?.output_component &&
              record.derived?.coordinate_units?.source !==
                record.derived?.coordinate_units?.target && <p>误差沿用原报单位</p>}
          </section>
        )
      })}
    </div>
  )
}

export default function MeasurementDetailV1({
  record,
  sources,
  onClose,
  onOpenSource,
  onOpenRecord,
  onOpenComparison,
  selection,
}) {
  const source = sources.find((s) => s.source_id === record.source_id)
  const native = record.source,
    ready = record.derived?.main_state === 'ready'
  const processing = record.activity?.find((a) => a.kind === 'representation')
  const disposition = { delivered: '已交付', unresolved: '待核实', not_supported: '原文不支持' }[record.record_status]
  const representation = ready && (processing?.status ?? record.derived?.status) === 'converted' ? '已归一转换' : '保留原报'
  const unit =
    native.unit ??
    native.unit_declaration?.canonical_symbol ??
    (native.unit_declaration?.kind === 'dimensionless' ? '无量纲' : '单位未注明')
  const known = readingConditions(record.context?.conditions, record.property_binding.definition.measurement_conditions_schema)
  const roleLabel = record.interpretation?.proposal?.result_role === 'reported_result' ? '' : measurementRole(record.interpretation?.proposal)
  const sourceScope = (record.context?.conditions || []).find(c=>c.key==='source_subject_and_measurand' && c.state==='known' && typeof c.value==='string')
  return (
    <section className="record-detail-panel research-record-detail" data-component="record-detail">
      <header className="record-detail-heading">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="record-property-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <strong data-detail-heading tabIndex={-1} style={{ fontSize: 18, fontWeight: 650, color: '#1e2a22' }}>
              {record.field_name}
            </strong>
            <DefinitionNote
              definition={{
                ...record.property_binding.definition,
                description: record.property_binding.definition.explanation?.quantity || record.property_binding.definition.description,
                standard_unit: record.property_binding.output_profile.unit.canonical_symbol,
              }}
            />
          </div>
          <div className="drawer-header-meta">
            <span className="drawer-meta-pill entity">{record.entity_name}</span>
          </div>
        </div>
        <div className="workbench-drawer-actions">
        {selection && <Button variant="outline" size="sm" aria-pressed={selection.has('records', record.record_id)}
          onClick={() => selection.toggle('records', [record])}>{selection.has('records', record.record_id) ? '取消选择' : '选择测量'}</Button>}
        <button
          type="button"
          className="drawer-close-btn"
          aria-label="关闭详情"
          title="关闭详情 (Esc)"
          onClick={onClose}
        >
          <Icon.Close style={{ width: 14, height: 14 }} />
        </button>
        </div>
      </header>
      <div className="record-detail-body">
        {/* 一体化科研测量核心看板（Hero Measurement Card） */}
        <div className="hero-measurement-card">
          <div className="hero-card-header">
            <div className="hero-value-wrap">
              <span className="hero-value-num">{String(record.field_value ?? '未记录')}</span>
              <span className="hero-value-unit">{record.field_unit ?? '单位未注明'}</span>
            </div>
            <div className="hero-badge-wrap">
              {disposition && <span className={`hero-status-tag ${record.record_status === 'delivered' ? 'verified' : 'unverified'}`}>{disposition}</span>}
              <span className="hero-status-tag limit">{representation}</span>
              {native.limit === 'upper' && <span className="hero-status-tag limit">上限</span>}
              {native.limit === 'lower' && <span className="hero-status-tag limit">下限</span>}
              {roleLabel && <span className="hero-status-tag limit">{roleLabel}</span>}
            </div>
          </div>

          <div className="hero-metrics-grid">
            <div className="hero-metric-item">
              <span className="hero-metric-label">不确定度 / 误差</span>
              <div className="hero-metric-value">
                <UncertaintyComponents record={record} />
              </div>
            </div>
            <div className="hero-metric-item">
              <span className="hero-metric-label">主值处理轨迹</span>
              <div className="hero-metric-value">
                {ready && (processing?.status === 'converted' || native.unit !== record.field_unit || typedValueText(native.value) !== typedValueText(record.derived.value_typed)) ? (
                  <span>{typedValueText(native.value)} {unit} → {record.field_value} {record.field_unit}</span>
                ) : (
                  <span>沿用原报 · {typedValueText(native.value)} {unit}</span>
                )}
              </div>
            </div>
          </div>
        </div>
        {(known.length>0 || sourceScope) && <section className="measurement-context" aria-label="测量条件">
          <h3>测量条件</h3><dl className="research-fields">
          {sourceScope && <div className="research-field-pair"><dt>测量对象</dt><dd>{sourceScope.value}</dd></div>}
          {known.map(c=><div className="research-field-pair" key={c.label+c.value}><dt>{c.label}</dt><dd>{c.value}</dd></div>)}
          </dl>
        </section>}
        <section aria-label="原文定位">
          <h3>原始证据</h3>
          {record.evidence?.length ? (
            record.evidence.map((e) => (
              <EvidenceSource
                key={e.evidence_id}
                evidence={e}
                source={source}
                sources={sources}
                onOpenSource={onOpenSource}
                taskId={native.task_id}
                view={record.evidence_views?.find((v) => v.evidence_id === e.evidence_id)}
              />
            ))
          ) : (
            <p>此历史版本未保存可打开的证据位置。</p>
          )}
        </section>
        <section aria-label="参考资料" className="provenance-section">
          <div className="section-title-row">
            <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, margin: 0 }}>
              <Icon.BookOpen style={{ width: 17, height: 17, color: 'var(--accent)' }} />
              参考资料与文献证据
            </h3>
            <span style={{ fontSize: 13, color: 'var(--content-fg-secondary)' }}>
              1 篇来源 · {(record.reported_references?.length || 0)} 条引用
            </span>
          </div>

          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--content-fg-secondary)', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>来源资料 (Source Material)</span>
            </div>
            {source ? (
              <button
                className="provenance-entry-card active-press"
                data-detail-action="source"
                onClick={() => onOpenSource?.(source)}
              >
                <div className="provenance-card-header">
                  <span className="provenance-badge badge-paper">
                    <Icon.FileText style={{ width: 12, height: 12 }} />
                    {source.kind === 'catalog' ? '星表原件' : '论文档案'}
                  </span>
                  <span className="provenance-badge badge-status">
                    <Icon.Check style={{ width: 10, height: 10 }} />
                    {source.availability || '原件已归档'}
                  </span>
                  {(source.work?.records?.[0]?.year || source.year) && (
                    <span className="provenance-badge badge-year">
                      {source.work?.records?.[0]?.year || source.year}
                    </span>
                  )}
                </div>
                <strong className="provenance-card-title">{titleText(source)}</strong>
                <div className="provenance-card-footer">
                  <span className="provenance-card-authors">
                    {source.work?.records?.[0]?.authors?.[0] || '核心作者群'} · 查看完整资料档案
                  </span>
                  <span className="provenance-action-link">
                    查阅档案 <Icon.ArrowRight style={{ width: 13, height: 13 }} />
                  </span>
                </div>
              </button>
            ) : (
              <p className="hint">来源档案未保存。</p>
            )}
          </div>

          {record.reported_references?.length > 0 && (
            <div style={{ marginTop: 18 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--content-fg-secondary)', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span>原文引用资料 (Citation References)</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {record.reported_references.map((r) => (
                  <button
                    className="provenance-entry-card active-press"
                    key={r.reference_id}
                    data-detail-action={'reference:' + r.reference_id}
                    onClick={() =>
                      onOpenSource?.({
                        protocol_version: 2,
                        kind: 'cited',
                        material_id: r.cited_work_id || r.reference_id,
                        source_id: r.cited_work_id || r.reference_id,
                        title: r.cited_work?.title || r.raw_code,
                        bibcode: r.cited_work?.bibcode,
                        abstract: r.cited_work?.abstract,
                        citations: [r],
                        availability: r.cited_work?.abstract ? '仅摘要' : '引文未解析',
                      })
                    }
                  >
                    <div className="provenance-card-header">
                      <span className="provenance-badge badge-cited">
                        <Icon.Quote style={{ width: 11, height: 11 }} />
                        {r.role === 'adopted_measurement'
                          ? '采用测量'
                          : r.role === 'method'
                            ? '方法引用'
                            : r.role === 'comparison'
                              ? '比较引用'
                              : '原文引用'}
                      </span>
                      {r.page && (
                        <span className="provenance-badge badge-page">
                          PDF 物理第 {r.page} 页
                        </span>
                      )}
                      <span className="provenance-badge badge-status">
                        {r.cited_work?.abstract ? '已解析摘要' : '保留原始引文'}
                      </span>
                    </div>
                    <strong className="provenance-card-title">
                      {titleText({ title: r.cited_work?.title || r.raw_code })}
                    </strong>
                    {r.link_quote && (
                      <p className="provenance-card-snippet">
                        “{r.link_quote}”
                      </p>
                    )}
                    <div className="provenance-card-footer">
                      <span className="provenance-card-authors">
                        {r.cited_work?.abstract ? '已解析摘要及引用上下文' : '原文献未解析引用条目'}
                      </span>
                      <span className="provenance-action-link">
                        查阅引文关系 <Icon.ArrowRight style={{ width: 13, height: 13 }} />
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
        <section aria-label="处理与质量">
          <h3>处理与质量</h3>
          {(record.archive_groups || []).map((group) => (
            <details key={group.group_id}>
              <summary>重复归档 · {group.member_refs.length} 条原报</summary>
              <p>{group.reason}</p>
              <div className="research-links">
                {group.member_refs.map((ref) => (
                  <button className="text-link" key={ref.id} onClick={() => onOpenRecord?.(ref.id)}>
                    查看组内原报
                  </button>
                ))}
              </div>
            </details>
          ))}
          {onOpenComparison && (
            <button className="text-link" onClick={() => onOpenComparison(record.property_id)}>
              查看本性质对照报告
            </button>
          )}

        </section>
      </div>
    </section>
  )
}
