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
  method: '方法',
  comparison: '比较',
  background: '背景',
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
}) {
  const initial = materials.find((m) => m.material_id === (source.material_id || source.source_id))
  const [loaded, setLoaded] = useState(null),
    [error, setError] = useState(''),
    [retry, setRetry] = useState(0)
  useEffect(() => {
    let valid = true
    setLoaded(null)
    setError('')
    if (scope?.deliveryId)
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
  return (
    <div className={'context-content research-material-detail material-' + item.kind}>
      <h3>{titleText(item)}</h3>
      <p className="material-kind-line">
        {kinds[item.kind] || '资料'} · {item.availability || '已有归档'}
        {item.roles?.includes('cited') && item.kind !== 'cited' ? ' · 同时被本轮记录引用' : ''}
      </p>
      {!!authors.length && (
        <p className="research-authors">
          {authors.slice(0, 3).map(displayText).join('，')}
          {authors.length > 3 ? ' 等' : ''}
          {(item.year || meta.year) && ' · ' + (item.year || meta.year)}
        </p>
      )}
      {authors.length > 3 && (
        <details>
          <summary>全部 {authors.length} 位作者</summary>
          <p>{authors.map(displayText).join('；')}</p>
        </details>
      )}
      <dl className="research-fields">
        {(item.bibcode || meta.bibcode) && (
          <>
            <dt>ADS</dt>
            <dd>
              <a
                href={
                  'https://ui.adsabs.harvard.edu/abs/' +
                  encodeURIComponent(item.bibcode || meta.bibcode) +
                  '/abstract'
                }
                target="_blank"
                rel="noreferrer"
              >
                {item.bibcode || meta.bibcode}
              </a>
            </dd>
          </>
        )}
        {(item.dois || meta.dois || []).map((doi) => (
          <div className="research-field-pair" key={doi}>
            <dt>DOI</dt>
            <dd>
              <a href={'https://doi.org/' + doi} target="_blank" rel="noreferrer">
                {doi}
              </a>
            </dd>
          </div>
        ))}
        {meta.publication && (
          <>
            <dt>出版信息</dt>
            <dd>{displayText(meta.publication)}</dd>
          </>
        )}
        {item.version_grade && (
          <>
            <dt>采用版本</dt>
            <dd>{versions[item.version_grade] || '版本等级未确认'}</dd>
          </>
        )}
        {item.page_count != null && (
          <>
            <dt>PDF 篇幅</dt>
            <dd>{item.page_count} 个物理页</dd>
          </>
        )}
        {item.association?.catalog_id && (
          <>
            <dt>CDS 目录</dt>
            <dd>{item.association.catalog_id}</dd>
          </>
        )}
        {item.association?.declared_filename && (
          <>
            <dt>附件文件</dt>
            <dd>{item.association.declared_filename}</dd>
          </>
        )}
        {original?.byte_size != null && (
          <>
            <dt>文件大小</dt>
            <dd>{(original.byte_size / 1024).toFixed(1)} KiB</dd>
          </>
        )}
      </dl>
      {original && (
        <a
          className="research-primary-link"
          href={api.artifactUrl(item.task_id, original.artifact_id)}
          target="_blank"
          rel="noreferrer"
        >
          打开保存的{item.kind === 'paper' ? ' PDF' : '数据原件'}
        </a>
      )}
      {error && (
        <p className="resource-error" role="alert">
          补充详情读取失败，已保存资料仍可查阅。
          <button className="text-link" onClick={() => setRetry((n) => n + 1)}>
            重新读取
          </button>
        </p>
      )}
      {(item.kind === 'paper' || item.kind === 'cited') && (item.abstract || meta.abstract) && (
        <section>
          <h4>原摘要</h4>
          <p className="research-abstract">
            {String(item.abstract || meta.abstract).replace(/<[^>]+>/g, '')}
          </p>
          {(meta.keywords || []).length > 0 && (
            <div className="research-tags">
              {meta.keywords.map((k, i) => (
                <span key={i}>{displayText(k)}</span>
              ))}
            </div>
          )}
        </section>
      )}
      {item.kind === 'official_attachment' && (
        <section className="attachment-relation">
          <h4>所属论文与官方关联</h4>
          {parent && (
            <button
              className="record-source-card"
              data-detail-action="parent"
              onClick={() => onOpenSource?.(parent)}
            >
              <strong>所属论文</strong>
              {titleText(parent)}
            </button>
          )}
          <p>{item.association?.locator || '历史未保存关联依据'}</p>
          {(item.association?.parent_bibcodes || []).map((b) => (
            <p key={b}>{b}</p>
          ))}
        </section>
      )}
      {item.readme?.artifact?.artifact_id && (
        <a
          className="text-link"
          href={api.artifactUrl(item.task_id, item.readme.artifact.artifact_id)}
          target="_blank"
          rel="noreferrer"
        >
          打开已保存的 ReadMe 与脚注
        </a>
      )}
      {!item.readme?.artifact?.artifact_id &&
        (item.readme?.url || item.association?.landing_url) && (
          <a
            className="text-link"
            href={item.readme?.url || item.association.landing_url}
            target="_blank"
            rel="noreferrer"
          >
            ReadMe 与官方说明
          </a>
        )}
      {['catalog', 'official_attachment'].includes(item.kind) && (
        <section>
          <h4>目标行与原始单元格</h4>
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
          ) : (
            <p>{loaded ? '本修订没有保存可核验的目标行单元格。' : '正在读取已保存的行列证据…'}</p>
          )}
          {item.metadata?.columns?.length > 0 && (
            <details>
              <summary>表结构 · {item.metadata.columns.length} 列</summary>
              <div className="research-table-scroll">
                <table className="native-cells">
                  <thead>
                    <tr>
                      <th>列名</th>
                      <th>单位</th>
                      <th>类型</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {item.metadata.columns.map((c, i) => (
                      <tr key={i}>
                        <th>{c.name}</th>
                        <td>{c.unit_text ?? c.unit ?? '未注明'}</td>
                        <td>{c.datatype || c.source_format || '未记录'}</td>
                        <td>{c.description || '未记录'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </section>
      )}
      {item.assignments?.length > 0 && (
        <section>
          <h4>本轮性质关联</h4>
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
              <p>
                {a.read_pages.length} 个已读核心页 · {a.candidate_count} 个候选 ·{' '}
                {a.measurement_ids.length} 条交付测量
              </p>
            </div>
          ))}
        </section>
      )}
      {!!item.attachment_ids?.length && (
        <section>
          <h4>官方补充材料</h4>
          {item.attachment_ids.map((id) => {
            const attachment = materials.find((m) => m.material_id === id)
            return (
              attachment && (
                <button
                  className="record-source-card"
                  key={id}
                  onClick={() => onOpenSource?.(attachment)}
                >
                  {attachment.association?.declared_filename || titleText(attachment)}
                </button>
              )
            )
          })}
        </section>
      )}
      {item.kind !== 'cited' && (
        <section>
          <h4>实际贡献测量 · {chosen.length} 条</h4>
          {chosen.length ? (
            <div className="research-record-links">
              {chosen.map((r) => (
                <button
                  className="record-source-card"
                  key={r.record_id}
                  data-detail-action={'record:' + r.record_id}
                  onClick={() => onOpenRecord?.(r)}
                >
                  <span>{r.field_name}</span>
                  <strong>
                    {r.field_value} {r.field_unit}
                  </strong>
                </button>
              ))}
            </div>
          ) : (
            <p>此资料没有测量进入当前交付修订。</p>
          )}
        </section>
      )}
      {cited.length > 0 && (
        <section>
          <h4>原文引用关系 · {cited.length} 条</h4>
          {cited.map((r) => (
            <div className="citation-relation" key={r.reference_id}>
              <strong>{r.raw_code || r.bibliography_entry || '原文引文'}</strong>
              <p>
                {roles[r.role] || '原文引用'} ·{' '}
                {r.resolution_state === 'resolved' ? '已解析题录' : '保留未解析引用'}
                {r.page ? ' · PDF 物理第 ' + r.page + ' 页' : ''}
              </p>
              {r.link_quote && <blockquote>{r.link_quote}</blockquote>}
              {records.some((m) => m.record_id === r.measurement_id) && (
                <button
                  className="text-link"
                  onClick={() =>
                    onOpenRecord?.(records.find((m) => m.record_id === r.measurement_id))
                  }
                >
                  查看引用所在记录
                </button>
              )}
            </div>
          ))}
        </section>
      )}
      {item.figures?.length > 0 && (
        <section>
          <h4>本资料研究图像 · {item.figures.length} 幅</h4>
          <div className="material-figure-strip">
            {item.figures.map((f) => (
              <button
                key={f.figure_id}
                onClick={() => onOpenFigure?.({ ...f, task_id: item.task_id })}
              >
                <img
                  loading="lazy"
                  src={api.artifactUrl(item.task_id, f.image_artifact.artifact_id)}
                  alt={f.label || '研究图像'}
                />
                <span>
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
