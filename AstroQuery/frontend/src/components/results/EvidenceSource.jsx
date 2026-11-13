import { useState } from 'react'
import { artifactUrl } from '@/services/api'
import SourceImageLightbox from './SourceImageLightbox'
import { titleText } from '@/lib/researchDisplay'
import { rawCells } from '@/lib/scienceReading'
import FormattedExcerpt from './FormattedExcerpt'

const ROLES = {
  main_excerpt: '测量摘录',
  subject_evidence: '天体归属',
  role_evidence: '结果类型',
  quantity_evidence: '性质定义',
  scope_evidence: '表头与章节',
  local_evidence: '数值位置',
  counter_evidence: '相关反证',
  semantics_evidence: '误差说明',
  evidence: '关联原文',
}
const roleName = (role) => ROLES[role] || '关联原文'

export function OriginalPage({ taskId, artifact, point }) {
  const [open, setOpen] = useState(false),
    [failed, setFailed] = useState(false)
  const [selected, setSelected] = useState(0)
  const [ready, setReady] = useState(false)
  const [showLines, setShowLines] = useState(false)
  const [fallback, setFallback] = useState(false)
  const fragments = point.anchors?.length ? point.anchors : [point]
  const fragment = fragments[selected] || fragments[0]
  const id = artifact?.id || artifact?.artifact_id
  if (!id) return <p>历史版本未保存原件身份。</p>
  const saved = point.preview_artifact?.artifact_id
  const preview = saved && !fallback
    ? artifactUrl(taskId, saved)
    : artifactUrl(taskId, id) + '/pages/' + point.page
  const precise = fragment.value_line_bbox
  const usable =
    point.width > 0 && point.height > 0
      ? (precise && !showLines ? [precise] : fragment.bbox || []).filter(
          (box) =>
            Array.isArray(box) && box.length === 4 && box[2] > box[0] && box[3] > box[1] &&
            box.every(Number.isFinite) &&
            box[0] >= 0 &&
            box[1] >= 0 &&
            box[2] <= point.width &&
            box[3] <= point.height,
        )
      : []
  const broad = !precise && usable.length > 4
  const boxes = broad && !showLines ? [] : usable
  return (
    <section
      className="research-evidence-page"
      data-location-precision={usable.length ? 'native-lines' : 'page-only'}
    >
      <div className="research-section-heading">
        <h4>PDF 物理第 {point.page} 页</h4>
        <a
          className="text-link"
          href={artifactUrl(taskId, id) + '#page=' + point.page}
          target="_blank"
          rel="noreferrer"
        >
          打开原 PDF
        </a>
      </div>
      {fragments.length > 1 && (
        <label className="evidence-fragment-select">
          证据片段{' '}
          <select
            aria-label={'第' + point.page + '页证据片段'}
            value={selected}
            onChange={(event) => {setSelected(Number(event.target.value));setShowLines(false)}}
          >
            {fragments.map((part, i) => (
              <option value={i} key={i}>
                {(part.roles || [part.role]).map(roleName).join('、')} · {i + 1}
              </option>
            ))}
          </select>
        </label>
      )}
      {precise && <span className="page-location-note">原报所在行</span>}
      {(broad || (precise && fragment.bbox?.length > 1)) && <button className="text-link" type="button" aria-pressed={showLines} onClick={()=>setShowLines(!showLines)}>
        {showLines ? '收起整段标记' : '查看摘录涉及的文本行'}</button>}
      {!failed ? (
        <button
          className="research-page-preview"
          aria-label={'放大原PDF物理第' + point.page + '页'}
          style={!ready ? {aspectRatio:point.width && point.height ? point.width+'/'+point.height : '3 / 4'} : undefined}
          onClick={() => setOpen(true)}
        >
          {!ready && <span className="page-loading" role="status">正在读取原页…</span>}
          <img
            decoding="async"
            onLoad={()=>setReady(true)}
            src={preview}
            alt={'PDF 物理第 ' + point.page + ' 页原件'}
            onError={() => {if (saved && !fallback) setFallback(true); else setFailed(true)}}
          />
          {boxes.map((box, i) => (
            <span
              data-evidence-box
              key={i}
              style={{
                left: (100 * box[0]) / point.width + '%',
                top: (100 * box[1]) / point.height + '%',
                width: (100 * (box[2] - box[0])) / point.width + '%',
                height: (100 * (box[3] - box[1])) / point.height + '%',
              }}
            />
          ))}
        </button>
      ) : (
        <p role="status">原页预览暂时无法读取，可打开原 PDF。</p>
      )}
      <FormattedExcerpt
        excerpt={fragment.excerpt}
        role={(fragment.roles || [fragment.role]).map(roleName).join('、')}
      />
      {open && (
        <SourceImageLightbox
          label={'原文定位图 · PDF 物理第 ' + point.page + ' 页'}
          focusBox={precise && boxes.length === 1 ? precise.map((v,i)=>v/(i%2 ? point.height : point.width)) : null}
          url={preview}
          boxes={boxes.map((box) =>
            box.map((v, i) => (1000 * v) / (i % 2 ? point.height : point.width)),
          )}
          source="native_text"
          onClose={() => setOpen(false)}
        />
      )}
    </section>
  )
}

export function NativeCells({ cells = [] }) {
  return (
    <div className="research-table-scroll">
      <table className="native-cells">
        <thead>
          <tr>
            <th>原列</th>
            <th>原始单元格</th>
            <th>原单位</th>
            <th>列说明</th>
          </tr>
        </thead>
        <tbody>
          {cells.map((cell, i) => (
            <tr key={cell.column + ':' + i} data-main-cell={cell.is_main || undefined}>
              <th scope="row">
                {cell.column}
                {cell.is_main && <span className="research-status">主值</span>}
              </th>
              <td className="native-literal">{cell.raw == null ? '源空值' : String(cell.raw)}</td>
              <td>{cell.metadata?.unit_text ?? cell.metadata?.unit ?? '未注明'}</td>
              <td>{cell.metadata?.description || '历史未保存列说明'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PaperPages({pages,taskId,artifact}) {
  const [active,setActive] = useState(0)
  const page = pages[active] || pages[0]
  if (!page) return <p>此原件没有已保存的物理页码。</p>
  return <div className="research-evidence-viewer">
    {pages.length>1 && <label>证据页 <select aria-label="选择证据页" value={page.page} onChange={event=>setActive(pages.findIndex(p=>p.page===Number(event.target.value)))}>
      {pages.map(p=><option key={p.page} value={p.page}>PDF 第 {p.page} 页</option>)}
    </select></label>}
    <OriginalPage key={page.page} taskId={taskId} artifact={artifact} point={page}/>
  </div>
}

export default function EvidenceSource({
  evidence,
  view,
  taskId,
  source,
  sources = [],
  onOpenSource,
}) {
  const location = view?.attachment_location
  const parentId = location?.parent_work_id || view?.parent_work_id
  const parent = parentId && sources.find((s) =>
    s.kind === 'paper' && !s.official_supplement && s.source_id !== source?.source_id &&
    (s.work_id === parentId || s.work?.work_id === parentId),
  )
  const parentButton = parent && (
    <button className="record-source-card" onClick={() => onOpenSource?.(parent)}>
      <strong>所属论文</strong>
      {titleText(parent)}
    </button>
  )
  if (view?.kind === 'table') {
    const selected = view.cells
      .filter((c) => c.is_main || c.is_selected)
      .sort((a, b) => Number(b.is_main) - Number(a.is_main))
    const others = view.cells.filter((c) => !c.is_main && !c.is_selected)
    const readme = view.readme?.artifact || source?.readme?.artifact
    return (
      <section className="research-table-evidence">
        <div className="research-section-heading">
          <h4>
            {location?.source_table_id || source?.association?.declared_filename ||
              location?.member_path || source?.table_id || '原始数据表'}
          </h4>
          {view.artifact_ref?.id && (
            <a
              className="text-link"
              href={artifactUrl(taskId, view.artifact_ref.id)}
              target="_blank"
              rel="noreferrer"
            >
              打开数据原件
            </a>
          )}
        </div>
        <p className="table-row-position">
          {view.row_basis === 'attachment_data_row' ? '附件数据行' : '查询响应数据行'}第{' '}
          {view.row + 1} 行 <span>零基索引 {view.row}</span>
          {view.column && <span> · {view.column} 列</span>}
          {location?.hdu != null && <span> · FITS HDU {location.hdu}</span>}
        </p>
        {parentButton}
        {location?.container_artifact_ref && (
          <a className="text-link" href={artifactUrl(taskId, location.container_artifact_ref)}
            target="_blank" rel="noreferrer">
            打开原始压缩包{location.member_path && ` · ${location.member_path}`}
          </a>
        )}
        <NativeCells cells={selected} />
        {!!others.length && (
          <details>
            <summary>同一数据行的其他 {others.length} 列</summary>
            <NativeCells cells={others} />
          </details>
        )}
        {readme?.artifact_id && (
          <a
            className="text-link"
            href={artifactUrl(taskId, readme.artifact_id)}
            target="_blank"
            rel="noreferrer"
          >
            打开已保存的 ReadMe 与脚注
          </a>
        )}
        {!readme?.artifact_id && source?.readme?.url && (
          <a className="text-link" href={source.readme.url} target="_blank" rel="noreferrer">
            ReadMe 与脚注
          </a>
        )}
      </section>
    )
  }
  if (view?.kind === 'pdf') {
    const pages = new Map()
    for (const p of view.points) {
      if (!pages.has(p.page)) pages.set(p.page, { ...p, anchors: [], bbox: [] })
      const page = pages.get(p.page)
      page.anchors.push(p)
      page.bbox.push(...(p.bbox || []))
    }
    return <>
      {parentButton}
      <PaperPages pages={[...pages.values()]} taskId={taskId} artifact={view.artifact_ref}/>
    </>
  }
  const locator = evidence?.locator || {}
  if (locator.page && evidence?.artifact_ref)
    return (
      <OriginalPage
        taskId={taskId}
        artifact={evidence.artifact_ref}
        point={{ page: locator.page, excerpt: evidence.raw_text, role: 'main_excerpt' }}
      />
    )
  return (
    <section>
      <p>
        {locator.table || '原始数据表'}
        {Number.isInteger(locator.row) && ' · 原记录零基行索引 ' + locator.row}
        {locator.column && ' · ' + locator.column + ' 列'}
      </p>
      {rawCells(evidence) ? (
        <NativeCells cells={rawCells(evidence)} />
      ) : (
        evidence?.raw_text && (
          <FormattedExcerpt
            excerpt={evidence.raw_text}
            role={evidence.role ? roleName(evidence.role) : '原始数据摘录'}
          />
        )
      )}
      {evidence?.artifact_ref?.id && (
        <a href={artifactUrl(taskId, evidence.artifact_ref.id)} target="_blank" rel="noreferrer">
          打开保存的原件
        </a>
      )}
    </section>
  )
}
