import { useEffect, useState } from 'react'
import { Icon } from '@/components/icons'
import * as api from '@/services/api'
import { titleText, displayText } from '@/lib/researchDisplay'
import EvidenceSource from './EvidenceSource'

const kinds = {
  paper: '论文',
  catalog: '星表',
  official_attachment: '官方补充材料',
  cited: '引用资料',
}
const versions = {
  published: '正式版',
  accepted: '接受稿',
  preprint: '预印本',
  unknown: '版本等级未确认',
}
const roles = {
  adopted_measurement: '采用测量',
  method: '方法引用',
  comparison: '比较引用',
  background: '背景依据',
}

export default function ResearchMaterialDetail({
  source,
  records = [],
  materials = [],
  sources = [],
  scope,
  onOpenRecord,
  onOpenSource,
  onOpenFigure,
  embeddedInfo = false,
  summary,
}) {
  const initial = materials.find((m) => m.material_id === (source.material_id || source.source_id))
  const [loaded, setLoaded] = useState(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [showAllAuthors, setShowAllAuthors] = useState(false)

  useEffect(() => {
    let valid = true
    setLoaded(null)
    setError('')
    if (scope?.deliveryId && !embeddedInfo)
      api
        .getMaterial(
          scope.taskId,
          scope.deliveryId,
          scope.deliveryRevision,
          source.material_id || source.source_id,
        )
        .then((row) => {
          if (valid) setLoaded(row)
        })
        .catch((e) => {
          if (valid) setError(e.message)
        })
    return () => {
      valid = false
    }
  }, [
    scope?.taskId,
    scope?.deliveryId,
    scope?.deliveryRevision,
    source.material_id,
    source.source_id,
    retry,
    embeddedInfo,
  ])

  const item = { ...source, ...initial, ...loaded, task_id: scope?.taskId || source.task_id }
  const meta = item.work?.records?.[0] || {}
  const authors = item.authors || meta.authors || []
  const parent = materials.find((m) => m.material_id === item.parent_material_id)
  const chosen = records.filter(
    (r) => (item.record_ids || []).includes(r.record_id) || r.source_id === item.source_id,
  )
  const cited = item.citations || []
  const tableViews = [
    ...new Map(
      (item.table_views || []).map((v) => [[v.table, v.row, v.column].join(':'), v]),
    ).values(),
  ]
  const original = item.artifact || item.schema_artifact

  // ==========================================
  // 分支 A: 原文引用资料视图 (kind === 'cited', 图三)
  // ==========================================
  if (item.kind === 'cited') {
    return (
      <div className="context-content research-material-detail material-cited" style={{ padding: '20px 24px 36px' }}>
        {/* 引用资料主身份卡片 */}
        <div className="citation-hero-card">
          <div className="citation-badges-row">
            <span className="provenance-badge badge-cited">
              <Icon.Quote style={{ width: 12, height: 12 }} />
              引用资料档案
            </span>
            {cited[0]?.role && (
              <span className="provenance-badge badge-role">
                {roles[cited[0].role] || '原文引用'}
              </span>
            )}
            <span className="provenance-badge badge-status">
              {item.availability || '保留未解析引用'}
            </span>
            {cited[0]?.page && (
              <span className="provenance-badge badge-page">
                PDF 物理第 {cited[0].page} 页
              </span>
            )}
          </div>

          {!embeddedInfo && <h3 className="citation-hero-title">
            {titleText({ title: item.title })}
          </h3>}

          <p className="citation-subtitle">
            本条目为从原作者论文正文中提取的第三方参考文献证据，记录原作者在参数测算、消光改正或方法对照时所依赖的原始引文依据。
          </p>
        </div>

        {summary}
        {/* 原文引用关系与金句证据舱 */}
        {cited.length > 0 && (
          <section className="citation-relations-section" style={{ marginTop: 20 }}>
            <div className="section-title-row">
              <h4>
                <Icon.Bookmark style={{ width: 16, height: 16, color: 'var(--accent)' }} />
                原文引用关系与上下文金句证据 · {cited.length} 条
              </h4>
            </div>

            {cited.map((r, idx) => (
              <div className="citation-evidence-box" key={r.reference_id || idx}>
                <div className="citation-evidence-header">
                  <div className="citation-evidence-tags">
                    <span className="citation-role-pill">
                      {roles[r.role] || '方法引用'}
                    </span>
                    {r.page && (
                      <span className="citation-page-pill">
                        <Icon.FileText style={{ width: 11, height: 11 }} />
                        PDF 物理第 {r.page} 页
                      </span>
                    )}
                    <span className="citation-state-pill">
                      {r.resolution_state === 'resolved' ? '已解析完整题录' : '保留未解析引文'}
                    </span>
                  </div>
                  <strong className="citation-code-badge">
                    {r.raw_code || r.bibliography_entry || '原文引文'}
                  </strong>
                </div>

                {r.link_quote ? (
                  <div className="citation-quote-wrapper">
                    <blockquote className="citation-evidence-quote">
                      “{r.link_quote}”
                    </blockquote>
                  </div>
                ) : (
                  <p className="hint">原文中未抓取到上下文金句。</p>
                )}

                {records.some((m) => m.record_id === r.measurement_id) && (
                  <div className="citation-record-link-row">
                    <button
                      type="button"
                      className="citation-jump-record-btn active-press"
                      onClick={() =>
                        onOpenRecord?.(records.find((m) => m.record_id === r.measurement_id))
                      }
                    >
                      <span>
                        查看此引用支撑的天体测量：
                        <strong>
                          {records.find((m) => m.record_id === r.measurement_id)?.field_name} (
                          {records.find((m) => m.record_id === r.measurement_id)?.field_value}{' '}
                          {records.find((m) => m.record_id === r.measurement_id)?.field_unit})
                        </strong>
                      </span>
                      <Icon.ArrowRight style={{ width: 14, height: 14 }} />
                    </button>
                  </div>
                )}
              </div>
            ))}
          </section>
        )}

        {/* 若引用有已保存摘要则呈现 */}
        {(item.abstract || meta.abstract) && (
          <section className="abstract-section">
            <div className="section-title-row">
              <h4>
                <Icon.AlignLeft style={{ width: 16, height: 16, color: 'var(--accent)' }} />
                引用文献摘要 (Abstract)
              </h4>
            </div>
            <div className="abstract-vessel">
              <p className="abstract-text">
                {String(item.abstract || meta.abstract).replace(/<[^>]+>/g, '')}
              </p>
            </div>
          </section>
        )}
      </div>
    )
  }

  // ==========================================
  // 分支 B: 来源文献/星表档案详情视图 (图二)
  // ==========================================
  return (
    <div className={'context-content research-material-detail material-' + item.kind} style={{ padding: '20px 24px 36px' }}>
      {/* 1. 文献主身份卡片 */}
      <div className="research-hero-card">
        <div className="provenance-card-header">
          <span className="provenance-badge badge-paper">
            <Icon.FileText style={{ width: 12, height: 12 }} />
            {kinds[item.kind] || '论文'}
          </span>
          <span className="provenance-badge badge-status">
            <Icon.Check style={{ width: 10, height: 10 }} />
            {item.availability || '原件已取得'}
          </span>
          {item.roles?.includes('cited') && (
            <span className="provenance-badge badge-cited">同时被本轮记录引用</span>
          )}
          {(item.year || meta.year) && (
            <span className="provenance-badge badge-year">
              {item.year || meta.year}
            </span>
          )}
          {item.version_grade && (
            <span className="provenance-badge badge-page">
              {versions[item.version_grade] || '正式版'}
            </span>
          )}
          {meta.publication && (
            <span className="provenance-badge badge-role">
              {displayText(meta.publication)}
            </span>
          )}
        </div>

        {!embeddedInfo && <h3 className="research-hero-title">{titleText(item)}</h3>}

        {!!authors.length && (
          <div className="research-hero-authors-row">
            <Icon.User style={{ width: 13, height: 13, color: 'var(--content-fg-secondary)', flexShrink: 0 }} />
            <span>
              {authors.slice(0, 3).map(displayText).join('，')}
              {authors.length > 3 ? ' 等' : ''}
              {(item.year || meta.year) ? ' · ' + (item.year || meta.year) : ''}
            </span>
            {authors.length > 3 && (
              <button
                type="button"
                className="author-toggle-btn active-press"
                onClick={() => setShowAllAuthors((v) => !v)}
              >
                {showAllAuthors ? '收起 ▴' : `全部 ${authors.length} 位作者 ▾`}
              </button>
            )}
          </div>
        )}

        {showAllAuthors && authors.length > 3 && (
          <div className="author-chips-container">
            {authors.map((a, i) => (
              <span className="author-chip" key={i}>
                <Icon.User style={{ width: 11, height: 11, color: 'var(--content-fg-secondary)' }} />
                {displayText(a)}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 2. 原件查阅与行动舱 */}
      {original && (
        <div className="paper-action-bar">
          <div className="paper-action-info">
            <div className="paper-action-icon-wrap">
              <Icon.FileText style={{ width: 20, height: 20, color: 'var(--accent)' }} />
            </div>
            <div>
              <div className="paper-action-format">
                {item.kind === 'paper' ? 'PDF 学术论文原件' : '原始数据文件'}
              </div>
              <div className="paper-action-meta">
                {original.byte_size != null && `${(original.byte_size / 1024).toFixed(1)} KiB`}
                {item.page_count != null && ` · 共 ${item.page_count} 个物理页`}
                {item.version_grade && ` · ${versions[item.version_grade] || '已核验版本'}`}
              </div>
            </div>
          </div>
          <a
            className="paper-action-btn active-press"
            href={api.artifactUrl(item.task_id, original.artifact_id)}
            target="_blank"
            rel="noreferrer"
          >
            <span>查阅保存的{item.kind === 'paper' ? ' PDF' : '原件'}</span>
            <Icon.ExternalLink style={{ width: 14, height: 14 }} />
          </a>
        </div>
      )}

      {error && (
        <p className="resource-error" role="alert" style={{ margin: '14px 0' }}>
          补充详情读取失败，已保存资料仍可查阅。
          <button className="text-link" onClick={() => setRetry((n) => n + 1)}>
            重新读取
          </button>
        </p>
      )}

      {/* 3. 学术凭证矩阵 (Identifier Grid) */}
      <div className="identifier-grid">
        {(item.bibcode || meta.bibcode) && (
          <div className="identifier-card">
            <div className="identifier-card-header">
              <span>ADS 题录编号</span>
              <span className="lang-tag">Harvard ADS</span>
            </div>
            <div className="identifier-card-value">
              {item.bibcode || meta.bibcode}
            </div>
            <a
              className="identifier-link"
              href={'https://ui.adsabs.harvard.edu/abs/' + encodeURIComponent(item.bibcode || meta.bibcode) + '/abstract'}
              target="_blank"
              rel="noreferrer"
            >
              <span>在 Harvard ADS 查阅</span>
              <Icon.ExternalLink style={{ width: 12, height: 12 }} />
            </a>
          </div>
        )}

        {(item.dois || meta.dois || []).map((doi, idx) => (
          <div className="identifier-card" key={doi}>
            <div className="identifier-card-header">
              <span>{idx === 0 ? '期刊正式 DOI' : '预印本 DOI'}</span>
              <span className="lang-tag">{doi.includes('arxiv') ? 'arXiv' : 'Journal'}</span>
            </div>
            <div className="identifier-card-value">{doi}</div>
            <a
              className="identifier-link"
              href={'https://doi.org/' + doi}
              target="_blank"
              rel="noreferrer"
            >
              <span>通过 DOI 解析跳转</span>
              <Icon.ExternalLink style={{ width: 12, height: 12 }} />
            </a>
          </div>
        ))}

        {(item.table_id || item.association?.catalog_id || item.association?.table_id) && (
          <div className="identifier-card">
            <div className="identifier-card-header">
              <span>CDS / VizieR 星表</span>
              <span className="lang-tag">VizieR</span>
            </div>
            <div className="identifier-card-value">
              {item.table_id || item.association?.catalog_id || item.association?.table_id}
            </div>
            <a
              className="identifier-link"
              href={`https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=${encodeURIComponent((item.table_id || item.association?.catalog_id || item.association?.table_id).replace(/\/[^\/]+$/, ''))}`}
              target="_blank"
              rel="noreferrer"
            >
              <span>在 CDS VizieR 检索星表</span>
              <Icon.ExternalLink style={{ width: 12, height: 12 }} />
            </a>
          </div>
        )}

        {item.association?.declared_filename && (
          <div className="identifier-card">
            <div className="identifier-card-header">
              <span>官方附件文件</span>
              <span className="lang-tag">Attachment</span>
            </div>
            <div className="identifier-card-value">{item.association.declared_filename}</div>
            <span style={{ fontSize: 12, color: 'var(--content-fg-secondary)' }}>
              随刊发布补充数据
            </span>
          </div>
        )}
      </div>

      {summary}
      {/* 4. 原摘要专属阅读舱 */}
      {(item.kind === 'paper' || item.kind === 'cited') && (item.abstract || meta.abstract) && (
        <section className="abstract-section">
          <div className="section-title-row">
            <h4>
              <Icon.AlignLeft style={{ width: 16, height: 16, color: 'var(--accent)' }} />
              原摘要 (Original Abstract)
            </h4>
            <span className="lang-tag">EN · 原文</span>
          </div>
          <div className="abstract-vessel">
            <p className="abstract-text">
              {String(item.abstract || meta.abstract).replace(/<[^>]+>/g, '')}
            </p>
            {(meta.keywords || []).length > 0 && (
              <div className="abstract-keywords-row">
                <span className="keywords-label">
                  <Icon.Tag style={{ width: 12, height: 12 }} /> 关键词:
                </span>
                {meta.keywords.map((k, i) => (
                  <span className="abstract-keyword-chip" key={i}>
                    {displayText(k)}
                  </span>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {/* 5. 官方补充材料关联 */}
      {item.kind === 'official_attachment' && (
        <section className="attachment-relation" style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--surface-border)' }}>
          <h4 style={{ fontSize: 15.5, fontWeight: 650, color: 'var(--content-fg)', marginBottom: 12 }}>
            所属论文与官方关联
          </h4>
          {parent && (
            <button
              className="provenance-entry-card active-press"
              data-detail-action="parent"
              onClick={() => onOpenSource?.(parent)}
            >
              <div className="provenance-card-header">
                <span className="provenance-badge badge-paper">所属母体论文</span>
              </div>
              <strong className="provenance-card-title">{titleText(parent)}</strong>
            </button>
          )}
          <p className="hint">{item.association?.locator || '历史未保存关联依据'}</p>
          {(item.association?.parent_bibcodes || []).map((b) => (
            <p key={b} className="hint">{b}</p>
          ))}
        </section>
      )}

      {/* 6. ReadMe 与脚注说明 */}
      {item.readme?.artifact?.artifact_id && (
        <div style={{ margin: '16px 0' }}>
          <a
            className="text-link"
            href={api.artifactUrl(item.task_id, item.readme.artifact.artifact_id)}
            target="_blank"
            rel="noreferrer"
          >
            打开已保存的 ReadMe 与脚注 ↗
          </a>
        </div>
      )}
      {!item.readme?.artifact?.artifact_id &&
        (item.readme?.url || item.association?.landing_url) && (
          <div style={{ margin: '16px 0' }}>
            <a
              className="text-link"
              href={item.readme?.url || item.association.landing_url}
              target="_blank"
              rel="noreferrer"
            >
              ReadMe 与官方说明 ↗
            </a>
          </div>
        )}

      {/* 7. 数据表结构与核验依据 (星表或补充材料) */}
      {['catalog', 'official_attachment'].includes(item.kind) && (
        <details className="catalog-structure-section catalog-structure-disclosure">
          <summary>
            <Icon.Database style={{ width: 16, height: 16, color: 'var(--accent)' }} />
            数据表结构与核验依据
            <Icon.ChevronDown className="catalog-structure-chevron" style={{ width: 16, height: 16 }} />
          </summary>

          {tableViews.length ? (
            tableViews.map((v) => (
              <EvidenceSource
                key={v.evidence_id}
                view={v}
                source={item}
                sources={sources}
                taskId={item.task_id}
                onOpenSource={onOpenSource}
              />
            ))
          ) : loaded && <p className="catalog-evidence-note">未保存目标行定位。</p>}

          {item.metadata?.columns?.length > 0 && (
            <div className="schema-table-card">
              <div className="schema-table-header">
                <div className="schema-header-left">
                  <Icon.Table style={{ width: 16, height: 16, color: 'var(--accent)' }} />
                  <span className="schema-header-title">数据表物理量结构定义</span>
                </div>
                <span className="schema-count-badge">
                  {item.metadata.columns.length} 个物理字段
                </span>
              </div>
              <div className="schema-table-scroll">
                <table className="schema-table">
                  <thead>
                    <tr>
                      <th style={{ width: '22%' }}>字段名称</th>
                      <th style={{ width: '16%' }}>物理单位</th>
                      <th style={{ width: '14%' }}>数据类型</th>
                      <th style={{ width: '48%' }}>科学释义与说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {item.metadata.columns.map((c, i) => (
                      <tr key={i}>
                        <td className="schema-col-name">
                          <code>{c.name}</code>
                        </td>
                        <td className="schema-col-unit">
                          {(c.unit_text || c.unit) ? (
                            <span className="schema-unit-pill">{c.unit_text || c.unit}</span>
                          ) : (
                            <span className="schema-unit-empty">—</span>
                          )}
                        </td>
                        <td className="schema-col-type">
                          <span className="schema-type-pill">
                            {c.datatype || c.source_format || 'float'}
                          </span>
                        </td>
                        <td className="schema-col-desc">
                          {c.description || '未提供补充说明'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </details>
      )}

      {/* 8. 本轮性质关联阶段进度 */}
      {item.assignments?.length > 0 && (
        <section style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--surface-border)' }}>
          <h4 style={{ fontSize: 15.5, fontWeight: 650, color: 'var(--content-fg)', marginBottom: 12 }}>
            本轮性质关联
          </h4>
          {item.assignments.map((a) => (
            <div className="material-assignment" key={a.property_id}>
              <strong>{a.name}</strong>
              <div className="assignment-stages">
                {[
                  [a.evaluated, '已评估'],
                  [a.eligible, '评估相关'],
                  [a.acquired, '已取得'],
                  [a.allocated, '获准阅读'],
                ].map(([yes, label]) => (
                  <span data-achieved={yes || undefined} key={label}>
                    {yes && <Icon.Check width={14} height={14} />} {label}
                  </span>
                ))}
              </div>
              <p className="hint">
                {a.read_pages.length} 个已读核心页 · {a.candidate_count} 个候选 ·{' '}
                {a.measurement_ids.length} 条交付测量
              </p>
            </div>
          ))}
        </section>
      )}

      {/* 9. 实际贡献测量 */}
      {!embeddedInfo && item.kind !== 'cited' && (
        <section style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--surface-border)' }}>
          <div className="section-title-row">
            <h4>
              <Icon.FileText style={{ width: 16, height: 16, color: 'var(--accent)' }} />
              实际贡献测量 · {chosen.length} 条
            </h4>
          </div>
          {chosen.length ? (
            <div className="research-record-links">
              {chosen.map((r) => (
                <button
                  className="record-source-card active-press"
                  key={r.record_id}
                  data-detail-action={'record:' + r.record_id}
                  onClick={() => onOpenRecord?.(r)}
                  style={{
                    borderRadius: 10,
                    padding: '12px 14px',
                    border: '1px solid var(--surface-border)',
                    background: 'var(--surface-bg)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4,
                    textAlign: 'left',
                    cursor: 'pointer',
                  }}
                >
                  <span style={{ fontSize: 13, color: 'var(--content-fg-secondary)' }}>{r.field_name}</span>
                  <strong style={{ fontSize: 16, color: 'var(--accent-text)' }}>
                    {r.field_value} {r.field_unit}
                  </strong>
                </button>
              ))}
            </div>
          ) : (
            <p className="hint">此资料没有测量进入当前交付修订。</p>
          )}
        </section>
      )}

      {/* 10. 原文引用关系 (如果是母文献引用的外部文献列表) */}
      {cited.length > 0 && (
        <section style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--surface-border)' }}>
          <div className="section-title-row">
            <h4>
              <Icon.Bookmark style={{ width: 16, height: 16, color: 'var(--accent)' }} />
              原文引用关系 · {cited.length} 条
            </h4>
          </div>
          {cited.map((r) => (
            <div className="citation-evidence-box" key={r.reference_id}>
              <div className="citation-evidence-header">
                <div className="citation-evidence-tags">
                  <span className="citation-role-pill">{roles[r.role] || '原文引用'}</span>
                  {r.page && (
                    <span className="citation-page-pill">
                      PDF 物理第 {r.page} 页
                    </span>
                  )}
                  <span className="citation-state-pill">
                    {r.resolution_state === 'resolved' ? '已解析题录' : '保留未解析引用'}
                  </span>
                </div>
                <strong className="citation-code-badge">
                  {r.raw_code || r.bibliography_entry || '原文引文'}
                </strong>
              </div>
              {r.link_quote && (
                <div className="citation-quote-wrapper">
                  <blockquote className="citation-evidence-quote">
                    “{r.link_quote}”
                  </blockquote>
                </div>
              )}
              {records.some((m) => m.record_id === r.measurement_id) && (
                <button
                  type="button"
                  className="citation-jump-record-btn active-press"
                  onClick={() =>
                    onOpenRecord?.(records.find((m) => m.record_id === r.measurement_id))
                  }
                  style={{ marginTop: 8 }}
                >
                  <span>查看引用所在记录 →</span>
                </button>
              )}
            </div>
          ))}
        </section>
      )}

      {/* 11. 研究图像 */}
      {!embeddedInfo && item.figures?.length > 0 && (
        <section style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--surface-border)' }}>
          <div className="section-title-row">
            <h4>
              <Icon.FileText style={{ width: 16, height: 16, color: 'var(--accent)' }} />
              本资料研究图像 · {item.figures.length} 幅
            </h4>
          </div>
          <div className="material-figure-strip">
            {item.figures.map((f) => (
              <button
                key={f.figure_id}
                className="active-press"
                onClick={() => onOpenFigure?.({ ...f, task_id: item.task_id })}
                style={{
                  borderRadius: 8,
                  overflow: 'hidden',
                  border: '1px solid var(--surface-border)',
                  background: 'var(--surface-bg)',
                  padding: 4,
                  cursor: 'pointer',
                  textAlign: 'center',
                }}
              >
                <img
                  loading="lazy"
                  src={api.artifactUrl(item.task_id, f.image_artifact.artifact_id)}
                  alt={f.label || '研究图像'}
                  style={{ width: '100%', height: 120, objectFit: 'contain', background: '#fff', borderRadius: 4 }}
                />
                <span style={{ fontSize: 12, color: 'var(--content-fg)', display: 'block', padding: '6px 4px 2px' }}>
                  {f.label || '研究图像'} · 第 {f.page} 页
                </span>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
