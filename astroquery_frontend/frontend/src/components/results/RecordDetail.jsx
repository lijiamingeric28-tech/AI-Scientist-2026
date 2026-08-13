import { useEffect, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { fmtPair } from '@/lib/format'

/* 记录详情弹窗（居中玻璃模态，风格对齐 SettingsDialog）：
 * 点击记录表格某行 → 展示该记录的完整数据血缘：
 * - 记录本体：provenance（数据库坐标 / 论文章节页码 + bbox）、提取置信度、原文摘录
 * - 处理轨迹：output_state.traceability.per_record_trace[record_id]（原始值→最终值 + 修改步骤）
 * - 清洗路由：report_state.quality.quality_scoring.per_source_routes[source_id]
 * - 冲突标注：report_state.conflict.resolution_report.annotations（按实体+字段匹配）
 * - Insight 建议：report_state.insights.field_insights（按实体+字段匹配）
 * - 字段语义：output_state.metadata.field_definitions[field_name]
 * 全部数据来自 GET /quality + /sources，由 ResultTabs 惰性加载后传入。
 */

const METHOD_LABELS = {
  database_query: '数据库查询', vlm_text: 'VLM 文本提取', vlm_table: 'VLM 表格提取',
}
const ROUTE_LABELS = {
  Normalization: '归一化', Conflict: '冲突消解', DirectExport: '直接导出',
  Export: '导出', Quarantine: '隔离', Skip: '跳过',
}

function Chip({ children, color, bg }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      fontSize: 11, padding: '2px 10px', borderRadius: 'var(--radius-pill)',
      color: color || 'var(--content-fg-secondary)',
      background: bg || 'var(--surface-secondary)',
      border: '1px solid var(--surface-border-subtle)',
    }}>
      {children}
    </span>
  )
}

function fmtTime(ts) {
  try { return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false }) } catch { return '' }
}

function Section({ label, children }) {
  return (
    <div>
      <div className="section-label" style={{ marginBottom: 6 }}>{label}</div>
      {children}
    </div>
  )
}

/* 加载中的占位（quality 接口未返回时，血缘相关分区先显示骨架） */
function SectionSkeleton({ rows = 2 }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {Array.from({ length: rows }).map((_, i) => <div key={i} className="skeleton" style={{ height: 26 }} />)}
    </div>
  )
}

export default function RecordDetailDialog({ record, quality, sources, loading, onClose }) {
  // Esc 关闭
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const qr = quality?.quality_report || null

  /* ── 数据血缘各切片 ── */
  const trace = useMemo(
    () => qr?.output_state?.traceability?.per_record_trace?.[record.record_id] || null,
    [qr, record.record_id],
  )
  const route = useMemo(
    () => qr?.report_state?.quality?.per_source_routes?.[record.source_id] || null,
    [qr, record.source_id],
  )
  const source = useMemo(
    () => (sources || []).find((s) => s.source_id === record.source_id) || null,
    [sources, record.source_id],
  )
  // 冲突标注：实体+字段匹配；记录来源在涉事来源中则高亮
  const conflicts = useMemo(() => {
    const anns = qr?.report_state?.conflict?.resolution_report?.annotations
    if (!Array.isArray(anns)) return []
    return anns.filter((a) => a.entity_name === record.entity_name && a.field_name === record.field_name)
  }, [qr, record.entity_name, record.field_name])
  // Insight 字段洞察：实体+字段匹配；来源类型一致的排前
  const fieldInsights = useMemo(() => {
    const fi = qr?.report_state?.insights?.field_insights
    if (!Array.isArray(fi)) return []
    const kind = record.provenance?.source_kind || source?.type
    return fi
      .filter((f) => f.entity_name === record.entity_name && f.field_name === record.field_name)
      .sort((a, b) => ((b.source_type === kind) ? 1 : 0) - ((a.source_type === kind) ? 1 : 0))
  }, [qr, record, source])
  const fieldDef = useMemo(
    () => qr?.output_state?.metadata?.field_definitions?.[record.field_name] || null,
    [qr, record.field_name],
  )
  const lowConf = useMemo(() => {
    const arr = qr?.output_state?.insights?.usage_recommendations?.low_confidence_records
    if (!Array.isArray(arr)) return false
    return arr.some((x) => String(x).includes(record.record_id))
  }, [qr, record.record_id])

  const prov = record.provenance || {}
  const isDb = record.extraction_method === 'database_query'

  return (
    <div
      onClick={onClose}
      className="animate-fade-in"
      style={{ position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 150, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="glass animate-drawer-in"
        data-component="record-detail"
        style={{
          width: 660, maxWidth: '94vw', maxHeight: '88vh',
          display: 'flex', flexDirection: 'column',
          background: 'color-mix(in srgb, var(--seed-surface) 82%, transparent)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-modal)',
          overflow: 'hidden',
        }}
      >
        {/* 头部：实体 + 字段 + 值 */}
        <div style={{ padding: '14px 18px 12px', borderBottom: '1px solid var(--surface-border)', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 15, fontWeight: 590, color: 'var(--content-fg)' }}>{record.entity_name}</span>
                <span className="font-mono" style={{ fontSize: 13, color: 'var(--content-fg-secondary)' }}>{record.field_name}</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
                <span className="font-mono" style={{ fontSize: 22, fontWeight: 590, letterSpacing: '-0.02em', color: 'var(--content-fg)' }}>
                  {String(record.field_value)}
                </span>
                {record.field_unit && <span style={{ fontSize: 13, color: 'var(--content-fg-tertiary)' }}>{record.field_unit}</span>}
              </div>
            </div>
            <Button variant="ghost" size="icon" onClick={onClose}><Icon.Close /></Button>
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
            <Chip><span className="font-mono">{record.source_id}</span></Chip>
            <Chip>{METHOD_LABELS[record.extraction_method] || record.extraction_method}</Chip>
            {typeof record.extraction_confidence === 'number' && (
              <Chip color="var(--status-progress)" bg="var(--status-progress-bg)">
                置信度 {Math.round(record.extraction_confidence * 100)}%
              </Chip>
            )}
            {route && (
              <Chip
                color={route === 'Conflict' ? 'var(--status-warn)' : 'var(--status-success)'}
                bg={route === 'Conflict' ? 'var(--status-warn-bg)' : 'var(--status-success-bg)'}
              >
                路由 · {ROUTE_LABELS[route] || route}
              </Chip>
            )}
            {lowConf && <Chip color="var(--status-warn)" bg="var(--status-warn-bg)">低置信度记录</Chip>}
          </div>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
          <div style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 20 }}>

            {/* ── 数据来源 ── */}
            <Section label="数据来源">
              <div className="row-item">
                {source?.title && (
                  <div style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)', marginBottom: 4 }}>{source.title}</div>
                )}
                {isDb ? (
                  <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 12px', fontSize: 12 }}>
                    {[
                      ['数据表', prov.db_table], ['键', prov.key_value ? `${prov.key_column} = ${prov.key_value}` : null],
                      ['原始列', prov.raw_column ? `${prov.raw_column}${prov.raw_unit ? `（${prov.raw_unit}）` : ''}` : null],
                      ['行号', prov.row_index != null ? String(prov.row_index) : null],
                    ].filter(([, v]) => v).map(([k, v]) => (
                      <div key={k} style={{ display: 'contents' }}>
                        <span style={{ color: 'var(--content-fg-tertiary)' }}>{k}</span>
                        <span className="font-mono" style={{ color: 'var(--content-fg)', wordBreak: 'break-all' }}>{v}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 12px', fontSize: 12 }}>
                    {[
                      ['页码', prov.page != null ? `第 ${prov.page} 页` : null],
                      ['区域', Array.isArray(prov.bbox) ? `[${prov.bbox.join(', ')}]${prov.bbox_coord_system ? ` · ${prov.bbox_coord_system}` : ''}` : null],
                      ['溯源 ID', record.trace_id || null],
                    ].filter(([, v]) => v).map(([k, v]) => (
                      <div key={k} style={{ display: 'contents' }}>
                        <span style={{ color: 'var(--content-fg-tertiary)' }}>{k}</span>
                        <span className="font-mono" style={{ color: 'var(--content-fg)', wordBreak: 'break-all' }}>{v}</span>
                      </div>
                    ))}
                  </div>
                )}
                {record.measurement_method && (
                  <div className="hint" style={{ marginTop: 8 }}>测量方法：{record.measurement_method}</div>
                )}
                {Array.isArray(record.condition_tags) && record.condition_tags.length > 0 && (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                    {record.condition_tags.map((t) => <Chip key={t}>{t}</Chip>)}
                  </div>
                )}
              </div>
              {record.context_snippet && (
                <div style={{
                  marginTop: 8, padding: '10px 14px',
                  background: 'var(--surface-secondary)', borderRadius: 'var(--radius-md)',
                  borderLeft: '3px solid var(--accent)',
                  fontSize: 12.5, lineHeight: 1.7, color: 'var(--content-fg-secondary)', fontStyle: 'italic',
                }}>
                  {record.context_snippet}
                </div>
              )}
            </Section>

            {/* ── 处理轨迹 ── */}
            <Section label="处理轨迹">
              {loading && !trace ? <SectionSkeleton rows={2} /> : trace ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {trace.modified ? (
                    <>
                      <div className="row-item" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                        <span className="font-mono" style={{ fontSize: 13, color: 'var(--content-fg-secondary)', textDecoration: 'line-through', textDecorationColor: 'var(--status-error)' }}>
                          {String(trace.original_value)}{trace.original_unit ? ` ${trace.original_unit}` : ''}
                        </span>
                        <Icon.ChevronRight style={{ color: 'var(--content-fg-tertiary)' }} />
                        <span className="font-mono" style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>
                          {String(trace.final_value)}{trace.final_unit ? ` ${trace.final_unit}` : ''}
                        </span>
                        <Chip color="var(--status-warn)" bg="var(--status-warn-bg)">已修改</Chip>
                      </div>
                      {(trace.modifications || []).map((m, i) => (
                        <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'baseline', padding: '6px 10px', background: i % 2 ? 'var(--surface-secondary)' : 'transparent', borderRadius: 'var(--radius-sm)' }}>
                          <span className="font-mono" style={{ flexShrink: 0, fontSize: 11, color: 'var(--content-fg-tertiary)' }}>{fmtTime(m.timestamp)}</span>
                          <Chip>{m.stage}</Chip>
                          <span className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg-secondary)' }}>
                            {fmtPair(m.before, m.after)}
                          </span>
                          <span style={{ flex: 1, fontSize: 11, color: 'var(--content-fg-tertiary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.reason || ''}</span>
                        </div>
                      ))}
                    </>
                  ) : (
                    <div className="hint" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Icon.Check style={{ color: 'var(--status-success)' }} />
                      该记录未经过清洗修改，原始值直接进入最终输出
                    </div>
                  )}
                </div>
              ) : (
                <div className="hint-dim">无该记录的处理轨迹</div>
              )}
            </Section>

            {/* ── 冲突标注（有匹配才显示） ── */}
            {conflicts.length > 0 && (
              <Section label={`冲突标注 · ${conflicts.length}`}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {conflicts.map((c, i) => {
                    const involved = Array.isArray(c.source_ids) && c.source_ids.includes(record.source_id)
                    return (
                      <div key={i} className="row-item">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
                          <Chip color="var(--status-warn)" bg="var(--status-warn-bg)">{c.annotation_type}</Chip>
                          {c.cause_label && <Chip>{c.cause_label}</Chip>}
                          {involved && <Chip color="var(--status-progress)" bg="var(--status-progress-bg)">本记录来源涉事</Chip>}
                          {typeof c.confidence === 'number' && (
                            <span className="font-mono" style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
                              置信度 {Math.round(c.confidence * 100)}%
                            </span>
                          )}
                        </div>
                        <div className="hint">
                          {c.source_count} 个来源的值域 {Array.isArray(c.value_range) ? c.value_range.join(' – ') : '—'}
                          {c.action ? ` · 处置：${c.action}` : ''}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </Section>
            )}

            {/* ── Insight 建议 ── */}
            <Section label="Insight 建议">
              {loading && fieldInsights.length === 0 ? <SectionSkeleton rows={3} /> : fieldInsights.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {fieldInsights.map((f, i) => (
                    <div key={i} className="row-item">
                      {f.observation && <div className="hint" style={{ marginBottom: 6 }}>{f.observation}</div>}
                      {f.interpretation && <div className="hint-dim" style={{ marginBottom: f.typical_range || (Array.isArray(f.cause_hypotheses) && f.cause_hypotheses.length) ? 6 : 0 }}>解读：{f.interpretation}</div>}
                      {f.typical_range && <div className="hint-dim">典型范围：{String(f.typical_range)}</div>}
                      {Array.isArray(f.cause_hypotheses) && f.cause_hypotheses.length > 0 && (
                        <div className="hint-dim">成因假设：{f.cause_hypotheses.join('；')}</div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="hint-dim">Insight 模块未针对该字段生成建议</div>
              )}
            </Section>

            {/* ── 字段定义 ── */}
            {fieldDef && (
              <Section label="字段定义">
                <div className="row-item">
                  {fieldDef.description && <div className="hint" style={{ marginBottom: 6 }}>{fieldDef.description}</div>}
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {fieldDef.standard_unit && <Chip>标准单位 {fieldDef.standard_unit}</Chip>}
                    {fieldDef.semantic_type && <Chip>{fieldDef.semantic_type}</Chip>}
                    {fieldDef.criticality && (
                      <Chip color={fieldDef.criticality === 'critical' ? 'var(--status-error)' : 'var(--content-fg-secondary)'}>
                        {fieldDef.criticality === 'critical' ? '关键字段' : fieldDef.criticality === 'important' ? '重要字段' : fieldDef.criticality}
                      </Chip>
                    )}
                  </div>
                </div>
              </Section>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
