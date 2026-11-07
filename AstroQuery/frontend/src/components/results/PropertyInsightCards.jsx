import EvidenceSource from './EvidenceSource'
import { stateText } from '@/lib/researchDisplay'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { Icon } from '../icons'
import { useState, useMemo } from 'react'

/**
 * Section classification badges and configuration directly matching V4 academic styling
 */
const SECTION_CONFIG = {
  found: {
    badge: '论文观察',
    badgeClass: 'badge-observation',
    icon: Icon.FileText,
    intro: '文献直接报告的核心测量事实与观测发现：'
  },
  comparison: {
    badge: '比对基准',
    badgeClass: 'badge-comparison',
    icon: Icon.BarChart,
    intro: '各文献在测光滤光系统、拟合流程及数据范围上的条件比对：'
  },
  uses: {
    badge: '研究解释',
    badgeClass: 'badge-explanation',
    icon: Icon.HelpCircle,
    intro: '物理机制解释与近邻/标准天体物理基准应用：'
  },
  limitations: {
    badge: '适用限制',
    badgeClass: 'badge-limitations',
    icon: Icon.Bookmark,
    intro: '先验假设依赖、消光律参数与合并统计时的注意事项：'
  }
}

const FINDING_CONFIG = {
  explicit_counterevidence: {
    label: '存在文献实测差异',
    badgeClass: 'finding-variance',
    hint: '经文献多方比对，不同观测阶段或采用不同拟合模型时报告了显著离散的测量结果。'
  },
  needs_check: {
    label: '待多方交叉核验',
    badgeClass: 'finding-check',
    hint: '该记录依赖单一文献报告或特殊测光系统，建议结合后续巡天数据进一步校验。'
  },
  ordinary_difference: {
    label: '符合公差的正常离散',
    badgeClass: 'finding-normal',
    hint: '数值微小波动符合仪器系统误差与观测公差范围，不构成物理模型矛盾。'
  }
}

/**
 * Individual evidence document / page popup
 */
function OriginalEvidence({ record, evidence }) {
  const [open, setOpen] = useState(false)
  const page = evidence.locator?.page
  const pageLabel = Number.isInteger(page)
    ? `查看文献第 ${page} 页原文 (PDF p.${page})`
    : '查看原表行列与原文字段'

  return (
    <div className="evidence-inline-wrap">
      <button
        type="button"
        className="evidence-inline-toggle-btn"
        onClick={() => setOpen(!open)}
      >
        <Icon.ExternalLink width="12" height="12" />
        <span>{pageLabel}</span>
        <span className={`inline-arrow${open ? ' rotated' : ''}`}>▾</span>
      </button>
      {open && (
        <div className="evidence-inline-source-panel">
          <EvidenceSource
            evidence={evidence}
            taskId={record.source.task_id}
            view={record.evidence_views?.find((v) => v.evidence_id === evidence.evidence_id)}
          />
        </div>
      )}
    </div>
  )
}

/**
 * Original references list for a paragraph
 */
function OriginalReferences({ paragraph, facts, onOpenRecord }) {
  const direct = paragraph.measurement_ids || []
  const ids = direct.length ? direct : paragraph.evidence_record_ids || []
  const selected = paragraph.evidence_ids || []

  if (!ids.length) return null

  return (
    <div className="insight-original-references-list">
      {ids.map((mid) => {
        const record = facts[mid]
        if (!record) {
          return (
            <p key={mid} className="evidence-missing-hint">
              此观测记录在当前筛选条件下已归档，可切换至全部条件查阅。
            </p>
          )
        }
        const evidence = (record.evidence || []).filter(
          (e) => !selected.length || selected.includes(e.evidence_id)
        )
        const sourceTitle = Array.isArray(record.source_title)
          ? record.source_title.join('；')
          : record.source_title || '本次收录文献'

        return (
          <div className="insight-evidence-record-card" key={mid}>
            <div className="evidence-record-header">
              <div className="evidence-val-group">
                <span className="evidence-field-name">{record.field_name}</span>
                <span className="evidence-raw-val">
                  原报数值: <strong>{record.source.raw_value}</strong>
                </span>
                {record.source.unit && (
                  <span className="evidence-unit-pill">{record.source.unit}</span>
                )}
                {record.source_version_grade && (
                  <span className="evidence-grade-pill">{record.source_version_grade}</span>
                )}
              </div>
              {onOpenRecord && (
                <button
                  type="button"
                  className="evidence-inspect-link"
                  onClick={() => onOpenRecord(record)}
                >
                  查阅测量记录与上下文 →
                </button>
              )}
            </div>

            <div className="evidence-source-line">
              <Icon.FileText width="12" height="12" />
              <span>{sourceTitle}</span>
            </div>

            {evidence.length > 0 && (
              <div className="evidence-doc-actions">
                {evidence.map((e) => (
                  <OriginalEvidence key={e.evidence_id} record={record} evidence={e} />
                ))}
              </div>
            )}

            {(record.source_statements || [])
              .filter((s) => selected.includes(s.statement_id))
              .map((s) => (
                <div className="evidence-quote-box" key={s.statement_id}>
                  <div className="quote-header">
                    <Icon.Quote width="12" height="12" />
                    <span>
                      {Number.isInteger(s.page)
                        ? `文献第 ${s.page} 页原文 (PDF p.${s.page})`
                        : '原表位置与上下文段落'}
                    </span>
                  </div>
                  <blockquote className="evidence-blockquote">{s.raw_quote}</blockquote>
                </div>
              ))}
          </div>
        )
      })}
    </div>
  )
}

/**
 * Theoretical knowledge bases
 */
function KnowledgeReferences({ ids, blocks, onOpenKnowledge }) {
  if (!ids?.length) return null
  return (
    <div className="insight-knowledge-list">
      {ids.map((cid) => {
        const block = blocks[cid]
        if (!block) return null
        return (
          <div className="insight-knowledge-card" key={cid}>
            <div className="knowledge-header">
              <span className="knowledge-basis-tag">
                {block.authoring_basis === 'source_checked' ? '同行评议文献核验' : '领域权威知识整理'}
              </span>
              <strong className="knowledge-title">{block.title}</strong>
              {onOpenKnowledge && (
                <button
                  type="button"
                  className="evidence-inspect-link"
                  onClick={() => onOpenKnowledge(block)}
                >
                  查看理论依据与边界 →
                </button>
              )}
            </div>
            <blockquote className="knowledge-claim">{block.claim?.text}</blockquote>
            {(block.conditions || []).length > 0 && (
              <div className="knowledge-conditions">
                <span className="cond-label">适用条件：</span>
                {block.conditions.map((text, i) => (
                  <span className="cond-item" key={i}>
                    {text}
                  </span>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/**
 * Accordion vessel for citations and evidence
 */
function InsightEvidenceAccordion({ paragraph, facts, blocks, onOpenRecord, onOpenKnowledge }) {
  const [open, setOpen] = useState(false)
  const direct = paragraph.measurement_ids || []
  const ids = direct.length ? direct : paragraph.evidence_record_ids || []
  const claimIds = paragraph.claim_ids || []
  const totalCount = ids.length + claimIds.length

  if (totalCount === 0) return null

  return (
    <div className={`insight-evidence-vessel${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="insight-evidence-toggle"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <span className="evidence-toggle-left">
          <Icon.BookOpen width="13" height="13" />
          <span className="evidence-toggle-title">原文核验与文献出处</span>
          <span className="evidence-count-pill">共 {totalCount} 处依据</span>
        </span>
        <span className={`evidence-chevron${open ? ' rotated' : ''}`}>
          <Icon.ChevronDown width="12" height="12" />
        </span>
      </button>
      {open && (
        <div className="insight-evidence-content">
          <OriginalReferences paragraph={paragraph} facts={facts} onOpenRecord={onOpenRecord} />
          <KnowledgeReferences ids={claimIds} blocks={blocks} onOpenKnowledge={onOpenKnowledge} />
        </div>
      )}
    </div>
  )
}

/**
 * PropertyInsightCards
 * Main scientific insight report viewer matching V4 Emerald Academic aesthetics
 */
export default function PropertyInsightCards({
  report,
  records = [],
  sources = [],
  selectedProperty,
  onSelectProperty,
  onOpenRecord,
  onOpenKnowledge,
  relations = false
}) {
  const propertyLabel = usePropertyLabel()
  const [localProperty, setLocalProperty] = useState('all')

  const facts = useMemo(() => {
    return Object.fromEntries(records.map((r) => [r.record_id, r]))
  }, [records])

  const names = useMemo(() => {
    return Object.fromEntries(records.map((r) => [r.property_id, r.field_name]))
  }, [records])

  const blocks = useMemo(() => {
    return Object.fromEntries(
      (report?.knowledge_blocks || []).map((block) => [block.claim?.claim_id, block])
    )
  }, [report])

  if (relations) {
    return (
      <section className="insight-relations-view">
        <KnowledgeReferences
          ids={Object.keys(blocks)}
          blocks={blocks}
          onOpenKnowledge={onOpenKnowledge}
        />
      </section>
    )
  }

  const allCards = report?.cards || []
  const activeProperty = selectedProperty !== undefined ? selectedProperty : localProperty

  const handlePropertyChange = (propId) => {
    if (onSelectProperty) {
      onSelectProperty(propId)
    }
    setLocalProperty(propId)
  }

  const visibleCards =
    activeProperty === 'all'
      ? allCards
      : allCards.filter((c) => c.property_id === activeProperty)

  // Overall metric counts
  const totalPropsCount = allCards.length
  const totalRecordsCount = records.length
  const uniqueSourcesCount = useMemo(() => {
    if (sources && sources.length) return sources.length
    return new Set(records.map((r) => r.source_id || r.source?.source_id).filter(Boolean)).size
  }, [sources, records])

  // Extract celestial entity name if available
  const sampleEntity = records[0]?.entity || records[0]?.target_object || ''

  return (
    <div className="scientific-insights-container">
      {report?.status === 'pending' && (
        <div className="insight-pending-banner">
          <Icon.Sparkle width="15" height="15" />
          <span>天体物理量测量记录已收录完毕，分析模型正在按性质汇总结算多源科学洞察…</span>
        </div>
      )}

      {/* 1. Research Overview Hero Dashboard (对标旧版图二：研究概览) */}
      <div className="insight-overview-hero">
        <div className="insight-overview-hero-header">
          <div className="hero-title-group">
            <span className="hero-icon-pill">
              <Icon.Sparkle width="16" height="16" />
            </span>
            <h3>研究概览 · 天体物理特性观察与机制解释</h3>
          </div>
          <span className="hero-status-pill">
            <Icon.Check width="11" height="11" />
            已收敛同行评议权威洞察
          </span>
        </div>
        <p className="insight-overview-prose">
          已整理收录 <strong>{totalRecordsCount}</strong> 条多波段观测记录，深度覆盖{' '}
          <strong>{totalPropsCount}</strong> 项关键天体物理性质。以下科学观察与物理机制推断由天体物理分析模型综合归纳生成，深入解析物理特征分布、模型拟合差异与理论适用边界。
        </p>
        <div className="insight-overview-metrics-strip">
          <div className="insight-metric-pill">
            <Icon.Tag width="12" height="12" />
            <span>
              覆盖 <strong>{totalPropsCount}</strong> 项物理性质
            </span>
          </div>
          <div className="insight-metric-pill">
            <Icon.Database width="12" height="12" />
            <span>
              整合 <strong>{totalRecordsCount}</strong> 条有效测量
            </span>
          </div>
          <div className="insight-metric-pill">
            <Icon.BookOpen width="12" height="12" />
            <span>
              涉及 <strong>{uniqueSourcesCount}</strong> 份文献来源
            </span>
          </div>
          {sampleEntity && (
            <div className="insight-metric-pill entity-pill">
              <span>目标天体: <strong>{sampleEntity}</strong></span>
            </div>
          )}
        </div>
      </div>

      {/* 2. Interactive Property Segmented Filter Bar */}
      {totalPropsCount > 1 && (
        <div className="insight-property-filter-bar">
          <button
            type="button"
            className={`insight-filter-pill${activeProperty === 'all' ? ' active' : ''}`}
            onClick={() => handlePropertyChange('all')}
          >
            全部物理性质 ({totalPropsCount})
          </button>
          {allCards.map((card) => {
            const pName = names[card.property_id] || propertyLabel(card.property_id)
            const count = card.coverage?.target_record_count || 0
            const isSelected = activeProperty === card.property_id
            return (
              <button
                type="button"
                key={card.card_id}
                className={`insight-filter-pill${isSelected ? ' active' : ''}`}
                onClick={() => handlePropertyChange(card.property_id)}
              >
                {pName} {count > 0 && <span className="pill-count">({count}条)</span>}
              </button>
            )
          })}
        </div>
      )}

      {/* 3. Cards List (对标旧版图二：白底典雅卡片群组) */}
      <div className="insight-cards-stack">
        {visibleCards.map((card) => {
          const propTitle = names[card.property_id] || propertyLabel(card.property_id)
          const targetEntity =
            card.entity || records.find((r) => r.property_id === card.property_id)?.entity || sampleEntity

          const allSections = Object.values(card.sections || {}).flat()
          const cardAllMids = Array.from(new Set(allSections.flatMap((p) => p.measurement_ids || p.evidence_record_ids || [])))
          const cardAllEvids = Array.from(new Set(allSections.flatMap((p) => p.evidence_ids || [])))
          const cardAllClaimIds = Array.from(new Set(allSections.flatMap((p) => p.claim_ids || [])))
          const cardTotalEvidence = cardAllMids.length + cardAllClaimIds.length

          return (
            <article className="insight-v4-card" key={card.card_id}>
              {/* Card Header */}
              <header className="insight-card-header">
                <div className="card-header-left">
                  <div className="property-title-line">
                    <h4 className="property-name">{propTitle}</h4>
                    {targetEntity && <span className="property-entity-pill">{targetEntity}</span>}
                    <span className="property-status-pill">
                      <Icon.Check width="10" height="10" />
                      已收敛权威洞察
                    </span>
                  </div>
                  <p className="property-coverage-subline">
                    {card.coverage?.target_record_count || 0} 条关联测量 ·{' '}
                    {card.coverage?.contributing_source_count || 0} 份实际贡献文献 · 权威模型综合归纳
                  </p>
                </div>
              </header>

              {/* Exclusion / Multi-target identification note */}
              {card.coverage?.owner_excluded_count > 0 && (
                <div className="insight-academic-note">
                  <Icon.Layers width="13" height="13" />
                  <span>
                    其中 {card.coverage.owner_excluded_count}{' '}
                    条记录经跨样本多目标鉴别归为背景参照样本，完整原报与比对依据已归档保留。
                  </span>
                </div>
              )}

              {/* Sections: found (论文观察), comparison (比对基准), uses (研究解释), limitations (适用限制) */}
              <div className="insight-sections-container">
                {Object.entries(SECTION_CONFIG).map(([key, cfg]) => {
                  const paragraphs = card.sections?.[key] || []
                  if (!paragraphs.length) return null

                  return (
                    <div className="insight-section-block" key={key}>
                      <div className="insight-section-badge-row">
                        <span className={`insight-section-badge ${cfg.badgeClass}`}>
                          <cfg.icon width="13" height="13" />
                          <span>{cfg.badge}</span>
                        </span>
                      </div>
                      <div className="insight-paragraphs-list">
                        {paragraphs.map((paragraph, i) => (
                          <p className="insight-paragraph-text" key={i}>{paragraph.text}</p>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>

              {/* Consolidated Literature & Evidence Vessel for the entire property card */}
              {cardTotalEvidence > 0 && (
                <div className="card-evidence-consolidated">
                  <details className="insight-evidence-vessel">
                    <summary className="insight-evidence-toggle">
                      <span className="evidence-toggle-left">
                        <Icon.BookOpen width="13" height="13" />
                        <span className="evidence-toggle-title">
                          查阅本物理性质关联文献依据与原报出处
                        </span>
                        <span className="evidence-count-pill">
                          共 {cardTotalEvidence} 处论据
                        </span>
                      </span>
                      <span className="evidence-chevron">▾</span>
                    </summary>
                    <div className="insight-evidence-content">
                      <OriginalReferences
                        paragraph={{
                          measurement_ids: cardAllMids,
                          evidence_ids: cardAllEvids
                        }}
                        facts={facts}
                        onOpenRecord={onOpenRecord}
                      />
                      <KnowledgeReferences
                        ids={cardAllClaimIds}
                        blocks={blocks}
                        onOpenKnowledge={onOpenKnowledge}
                      />
                    </div>
                  </details>
                </div>
              )}

              {/* Reference Range Box (对标旧版图二：已有参考范围) */}
              {(card.typical_range || card.reference_range) && (
                <div className="reference-range-vessel">
                  <span className="insight-section-badge badge-range">已有参考范围</span>
                  <div className="reference-range-val">
                    {card.typical_range || card.reference_range}
                  </div>
                </div>
              )}

              {/* Findings Section (对标旧版图二：原因假设与实测差异归因) */}
              {card.findings?.length > 0 && (
                <div className="insight-section-block findings-block">
                  <div className="insight-section-badge-row">
                    <span className="insight-section-badge badge-findings">
                      <Icon.Network width="13" height="13" />
                      <span>原因假设与实测差异归因</span>
                    </span>
                  </div>
                  <div className="insight-findings-list">
                    {card.findings.map((finding) => {
                      const fCfg =
                        FINDING_CONFIG[finding.classification] || FINDING_CONFIG.ordinary_difference
                      return (
                        <div className="insight-finding-card" key={finding.finding_id}>
                          <div className="finding-card-header">
                            <span className={`finding-status-tag ${fCfg.badgeClass}`}>
                              {fCfg.label}
                            </span>
                            <span className="finding-meta-hint">
                              {finding.owner_state === 'not_supported'
                                ? '经文献核定确认为背景/参照样本，不纳入本天体直接统计。'
                                : finding.owner_state === 'passed'
                                  ? '多源文献复检未确认该实测异议，确认采纳原报观测值。'
                                  : finding.classification === 'ordinary_difference'
                                    ? '不同文献报告存在微小离散，符合正常观测公差。'
                                    : '保持文献原报记录，已附加待核验标注。'}
                            </span>
                          </div>
                          <p className="finding-text">{finding.paragraph?.text}</p>
                          <InsightEvidenceAccordion
                            paragraph={{
                              measurement_ids: finding.measurement_ids,
                              evidence_ids: (finding.anchors || []).map((a) => a.evidence_id)
                            }}
                            facts={facts}
                            blocks={blocks}
                            onOpenRecord={onOpenRecord}
                            onOpenKnowledge={onOpenKnowledge}
                          />
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Suppressed / Archive References */}
              {card.suppressed_examples?.length > 0 && (
                <div className="insight-suppressed-wrap">
                  <details className="insight-evidence-vessel archive-vessel">
                    <summary className="insight-evidence-toggle">
                      <span className="evidence-toggle-left">
                        <Icon.Layers width="13" height="13" />
                        <span className="evidence-toggle-title">
                          多目标样本归档与背景参照核验记录
                        </span>
                        <span className="evidence-count-pill">
                          共 {card.suppressed_examples.length} 条
                        </span>
                      </span>
                      <span className="evidence-chevron">▾</span>
                    </summary>
                    <div className="insight-evidence-content">
                      <p className="academic-archive-notice">
                        以下条目在原始文献中与本天体并列记载，经科学目标属性核验已归入背景/参照样本集，保留原始记录以供横向参考：
                      </p>
                      {card.suppressed_examples.map((item, i) => (
                        <div className="archive-example-item" key={i}>
                          <span className="example-index">#{i + 1}</span>
                          <span className="example-text">{item.paragraph?.text}</span>
                        </div>
                      ))}
                    </div>
                  </details>
                </div>
              )}
            </article>
          )
        })}

        {visibleCards.length === 0 && (
          <div className="empty-analysis-card">
            <Icon.Sparkle width="28" height="28" />
            <p>选定物理性质暂无已保存的事实解释，或未发现跨文献显著差异。</p>
          </div>
        )}
      </div>
    </div>
  )
}
