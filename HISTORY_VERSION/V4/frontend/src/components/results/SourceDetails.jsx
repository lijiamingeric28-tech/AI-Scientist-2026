import { Excerpt, Prose } from './ReadableContent'
import { SOURCE_TYPES, sourceName, readableText } from '@/lib/readableData'
import { usePropertyLabel } from '@/lib/propertyLabel'

export default function SourceDetails({ source, records }) {
  const propertyLabel = usePropertyLabel()
  const authors = Array.isArray(source.authors) ? source.authors.map(readableText).filter(Boolean) : []
  const selected = records.filter(record => record.source_id === source.source_id)
  const fields = [...new Set(selected.map(record => record.field_name).filter(Boolean))]
  const database = ['database', 'db'].includes(source.source_type)
  return <div className="context-content source-reading"><h3>{sourceName(source, source.source_id)}</h3><p className="hint">{[SOURCE_TYPES[source.source_type] || source.source_type, source.journal, source.year].filter(Boolean).join(' · ')}</p>
    {database && <><section><h4>数据库概况</h4>{source.vizier_table_id && <dl className="record-location"><div><dt>数据表</dt><dd>{source.vizier_table_id}</dd></div></dl>}<Excerpt value={source.description} label="展开数据库介绍" /><Prose value={source.research_content} /></section>
      {(source.observation_facility || source.waveband || source.research_methodology) && <section><h4>观测设施与方法</h4><dl className="record-location">{source.observation_facility && <div><dt>设施</dt><dd>{readableText(source.observation_facility)}</dd></div>}{source.waveband && <div><dt>波段</dt><dd>{readableText(source.waveband)}</dd></div>}</dl><Excerpt value={source.research_methodology} label="展开研究方法" /></section>}
      <section><h4>本次提取</h4><p>{selected.length} 条记录 · {fields.length} 项性质</p>{fields.length > 0 && <p className="source-coverage">{fields.map(propertyLabel).join('、')}</p>}</section>
      {readableText(source.reference_paper) && <section><h4>参考论文</h4><Prose value={source.reference_paper} />{source.bibcode && <a className="text-link" href={`https://ui.adsabs.harvard.edu/abs/${encodeURIComponent(source.bibcode)}/abstract`} target="_blank" rel="noreferrer">查看 ADS 论文 ↗</a>}</section>}</>}
    {authors.length > 0 && <section><h4>作者</h4><p>{authors.slice(0, 3).join('；')}{authors.length > 3 && ' 等'}</p>{authors.length > 3 && <details><summary>全部作者</summary><p>{authors.join('；')}</p></details>}</section>}
    {source.doi && <a className="text-link" href={`https://doi.org/${encodeURIComponent(source.doi)}`} target="_blank" rel="noreferrer">查看 DOI 论文 ↗</a>}
    {/^https?:\/\//.test(source.access_path || '') && <a className="text-link" href={source.access_path} target="_blank" rel="noreferrer">打开来源文件 ↗</a>}
    {readableText(source.abstract) && <section><h4>摘要</h4><Excerpt value={readableText(source.abstract).replace(/<[^>]+>/g, '')} label="展开完整摘要" /></section>}
  </div>
}
