import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { fmtPair } from '@/lib/format'
import { journalLabel } from '@/lib/journal'
import { DUP_PRINCIPLE_TEXT, DUP_REASON_TEXT, DUP_RULE_TEXT } from '@/lib/dupMarkers'
import SourceImageLightbox from './SourceImageLightbox'
import { exactRecordIds, modificationReport } from '@/lib/resultData'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { readableText, recordChanges, modificationView, sourceName, measurementText, isDatabaseRecord } from '@/lib/readableData'
import { DefinitionNote, Prose, Excerpt } from './ReadableContent'

/* 记录详情弹窗（居中玻璃模态，风格对齐 SettingsDialog）：
 * 点击记录表格某行 → 展示该记录的完整数据血缘：
 * - 记录本体：provenance（数据库坐标 / 论文章节页码 + bbox）、提取置信度、原文摘录
 * - 处理轨迹：output_state.traceability.per_record_trace[record_id]（原始值→最终值 + 修改步骤）
 * - 清洗路由：report_state.quality.quality_scoring.per_source_routes[source_id]
 * - 冲突标注：report_state.conflict.resolution_report.annotations（按实体+字段匹配）
 * - 疑似重复：report_state.conflict.verification.duplicate_groups（record_ids 精确命中，见 dupMarkers）
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

/* 溯源定位图缩略图：论文页图 + bbox overlay（normalized_1000 → 百分比定位）。
 * 样式按定位方式 (provenance.bbox_source) 区分:
 *   - full_table: 整表宏定位 — 半透明大卡片 + "表格" 徽章 (表格数据轨)
 *   - vector/vlm_crop: 数值微观定位 — 细红框 (正文数据轨)
 *   - fallback: 段落兜底 — 虚线框
 * 点击缩略图 → 全屏图片浏览器 (SourceImageLightbox: 滚轮缩放/拖拽/双击复位)。
 * 图片加载失败（旧运行无落盘页图）时静默降级为只显示坐标文本。 */
function BboxSourceImage({ url, bbox, source }) {
  const [failed, setFailed] = useState(false)
  const [open, setOpen] = useState(false)
  if (!url || failed) return null
  const [x0, y0, x1, y1] = bbox
  const isTable = source === 'full_table'
  const isFallback = source === 'fallback'
  const overlay = isTable ? {
    border: '2px solid var(--accent)',
    background: 'color-mix(in srgb, var(--accent) 10%, transparent)',
    boxShadow: '0 0 0 9999px color-mix(in srgb, var(--overlay) 35%, transparent)',
  } : isFallback ? {
    border: '2px dashed var(--content-fg-tertiary)',
    background: 'transparent',
  } : {
    border: '2px solid var(--status-error)',
    background: 'color-mix(in srgb, var(--status-error) 14%, transparent)',
  }
  return (
    <>
      <div
        onClick={() => setOpen(true)}
        role="button" tabIndex={0} aria-label="查看原文定位图"
        onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setOpen(true) } }}
        title="点击全屏查看"
        style={{
          marginTop: 10, position: 'relative', display: 'inline-block', maxWidth: '100%',
          background: 'var(--surface-secondary)', borderRadius: 'var(--radius-md)', overflow: 'hidden',
          border: '1px solid var(--surface-border-subtle)', cursor: 'zoom-in',
        }}
      >
        <img
          src={url}
          alt="溯源定位图"
          onError={() => setFailed(true)}
          style={{ display: 'block', maxWidth: '100%', maxHeight: 340, width: 'auto', height: 'auto' }}
        />
        <div style={{ position: 'absolute', left: 0, top: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
          <div style={{
            position: 'absolute',
            left: `${x0 / 10}%`, top: `${y0 / 10}%`,
            width: `${(x1 - x0) / 10}%`, height: `${(y1 - y0) / 10}%`,
            boxSizing: 'border-box',
            ...overlay,
          }} />
          {isTable && (
            <span style={{
              position: 'absolute', left: `${x0 / 10}%`, top: `calc(${y0 / 10}% - 22px)`,
              fontSize: 11, padding: '1px 8px', borderRadius: 'var(--radius-pill)',
              color: 'var(--accent)', background: 'var(--surface-primary)',
              border: '1px solid var(--accent)', whiteSpace: 'nowrap',
            }}>
              表格定位 · 整表
            </span>
          )}
        </div>
        <span style={{
          position: 'absolute', right: 6, bottom: 6, fontSize: 10,
          padding: '1px 7px', borderRadius: 'var(--radius-pill)',
          color: 'var(--content-fg-secondary)', background: 'var(--surface-primary)',
          border: '1px solid var(--surface-border-subtle)', pointerEvents: 'none',
        }}>
          点击全屏查看
        </span>
      </div>
      {open && (
        <SourceImageLightbox
          url={url}
          bbox={bbox}
          source={source}
          onClose={() => setOpen(false)}
        />
      )}
    </>
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


export default function RecordDetailDialog({ record, quality, sources = [], loading, onClose, onOpenRecord, onOpenSource, dup = null, embedded = false }) {
  const propertyLabel = usePropertyLabel()
  useEffect(() => {
    const onKey = event => { if (!embedded && event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, embedded])
  const source = sources.find(item => item.source_id === record.source_id)
  const prov = record.provenance || {}, qr = quality?.quality_report
  const { trace, rows } = recordChanges(record, quality)
  const changes = rows.map(row => modificationView(row, [record]))
  const fieldDef = qr?.output_state?.metadata?.field_definitions?.[record.field_name]
  const annotations = qr?.report_state?.conflict?.resolution_report?.annotations
  const conflicts = (Array.isArray(annotations) ? annotations : []).filter(item => exactRecordIds(item).includes(record.record_id))
  const isDb = isDatabaseRecord(record, source)
  const isSupplement = ['supplement', 'supplementary'].includes(source?.source_type) || prov.source_kind === 'supplement'
  const doi = source?.doi
  return <div onClick={embedded ? undefined : onClose} className={embedded ? 'record-detail-embedded' : 'record-detail-backdrop'}>
    <section onClick={event => event.stopPropagation()} className="record-detail-panel" data-component="record-detail">
      <header className="record-detail-heading" data-detail-heading tabIndex={-1}><div><div className="record-property-title"><strong>{record.entity_name}</strong><span>{propertyLabel(record.field_name)}</span><DefinitionNote definition={fieldDef} /></div><p className="record-measurement"><strong>{readableText(record.field_value) || '未提供'}</strong>{record.field_unit && <span>{record.field_unit}</span>}</p></div><Button variant="ghost" size="icon" aria-label="关闭记录详情" onClick={onClose}><Icon.Close /></Button></header>
      <div className="record-detail-body">
        <section className="record-source"><h3>出处与证据</h3><div className="provenance-part"><h4>数据出处</h4><p className="record-source-title">{sourceName(source, record.source_id)}</p>{[source?.journal, source?.year].filter(Boolean).length > 0 && <p className="hint">{[source.journal, source.year].filter(Boolean).join(' · ')}</p>}
          <div className="record-source-links">{doi && <a className="text-link" href={'https://doi.org/' + encodeURIComponent(doi)} target="_blank" rel="noreferrer">查看 DOI 论文 ↗</a>}
          {source && onOpenSource && <button className="text-link record-source-action" data-detail-action="source" onClick={() => onOpenSource(source)}>查看来源详情 →</button>}</div>
          </div>
          {(prov.page != null || prov.db_table || prov.cds_table_id || prov.raw_column || prov.key_value != null || prov.row_index != null) && <div className="provenance-part"><h4>取值位置</h4><dl className="record-location">{isDb || isSupplement ? <>{(prov.db_table || prov.cds_table_id) && <div><dt>数据表</dt><dd>{prov.db_table || prov.cds_table_id}</dd></div>}{prov.raw_column && <div><dt>原始列</dt><dd>{prov.raw_column}{prov.raw_unit && ' (' + prov.raw_unit + ')'}</dd></div>}{prov.key_column && <div><dt>主键列</dt><dd>{prov.key_column}</dd></div>}{prov.key_value != null && <div><dt>主键值</dt><dd>{prov.key_value}</dd></div>}{prov.row_index != null && <div><dt>表内行</dt><dd>第 {prov.row_index + 1} 行（索引 {prov.row_index}）</dd></div>}{prov.parent_bibcode && <div><dt>所属论文</dt><dd>{prov.parent_bibcode}</dd></div>}</> : null}{prov.page != null && <div><dt>原文页码</dt><dd>第 {prov.page} 页</dd></div>}</dl></div>}
          {readableText(record.context_snippet) && <div className="provenance-part"><h4>原文摘录</h4><blockquote className="source-excerpt"><Excerpt value={record.context_snippet} label="展开完整原文" disclosureKey="record-excerpt" /></blockquote></div>}
          {!isDb && Array.isArray(prov.bbox) && prov.bbox.length === 4 && record.page_image_url && <div className="provenance-part"><h4>原文定位图</h4><BboxSourceImage key={record.record_id} url={record.page_image_url} bbox={prov.bbox} source={prov.bbox_source} /></div>}
          {(readableText(record.measurement_method) || readableText(record.condition_tags)) && <div className="provenance-part"><h4>测量方法与条件</h4><Prose value={record.measurement_method} />{readableText(record.condition_tags) && <p className="measurement-conditions">{Array.isArray(record.condition_tags) ? record.condition_tags.join(' · ') : readableText(record.condition_tags)}</p>}</div>}
        </section>
        {changes.length > 0 && <section className="record-changes"><h3>处理历程 <small>{changes.length} 步</small></h3><ol className="record-history">{trace?.original_value != null && <li className="history-snapshot"><span className="history-dot" /><div><h4>原始测量</h4><p>{measurementText(trace.original_value, trace.original_unit)}</p></div></li>}{changes.map((row, index) => <li key={index}><span className="history-number">{index + 1}</span><article className="record-change"><h4>{row.operation}</h4>{row.originals.filter(name => name !== row.operation).length > 0 && <p className="operation-original">{row.originals.filter(name => name !== row.operation).join(' · ')}</p>}{(row.before || row.after) && <div className="value-change"><span>{row.before || '未提供'}</span><span aria-hidden="true">→</span><strong>{row.after || '未提供'}</strong></div>}<Excerpt value={row.reason} label="展开处理原因" disclosureKey={`change-reason-${index}`} />{(row.timestamp || row.iteration != null || row.reportOrigin === '修改报告补充') && <p className="history-meta">{[row.timestamp && (Number.isNaN(Date.parse(row.timestamp)) ? row.timestamp : new Date(row.timestamp).toLocaleString('zh-CN', { hour12: false })), row.iteration != null ? `第 ${row.iteration} 轮` : '', row.reportOrigin === '修改报告补充' ? row.reportOrigin : ''].filter(Boolean).join(' · ')}</p>}</article></li>)}<li className="history-snapshot final"><span className="history-dot" /><div><h4>当前测量</h4><p>{measurementText(record.field_value, record.field_unit)}</p></div></li></ol></section>}
        {loading && !qr && <p className="hint" role="status">正在读取处理信息…</p>}
        {conflicts.length > 0 && <section><h3>相关测量差异</h3>{conflicts.map((item, i) => <div key={i}><Prose value={item.description || item.reason} />{item.source_count != null && <p>该性质涉及 {item.source_count} 个来源{Array.isArray(item.value_range) && item.field_unit && item.field_unit === record.field_unit ? '，已有值域为 ' + item.value_range.join(' — ') + ' ' + item.field_unit : ''}。</p>}</div>)}</section>}
        {dup?.group && <section className="record-duplicates"><h3>重复收录</h3><p>此数值在 {dup.group.sourceCount} 个来源中一致，当前记录{dup.isRepresentative ? '为该组代表记录' : '被标记为疑似重复'}。</p><details><summary>查看相关记录</summary>{dup.group.members.filter(item => item.isLive && item.recordId !== record.record_id).map(item => <button className="related-record" data-detail-action={'record:' + item.recordId} key={item.recordId} onClick={() => onOpenRecord?.(item.recordId)}>{sourceName(sources.find(source => source.source_id === item.sourceId), item.sourceId)} <span>查看记录 ›</span></button>)}</details></section>}
      </div>
    </section>
  </div>
}
