import { useMemo } from 'react'
import { useRememberedState } from '@/hooks/useViewMemory'
import { artifactUrl } from '@/services/api'
import { titleText, stateText } from '@/lib/researchDisplay'

const kinds = {
  paper: '论文',
  catalog: '星表',
  official_attachment: '官方补充材料',
  cited: '引用资料',
}
export default function MaterialsV1({
  materials = [],
  figures = [],
  sources = [],
  onOpenSource,
  onOpenFigure,
  memory = {},
  active = true,
  properties = [],
}) {
  const [tab, setTab] = useRememberedState(memory, 'tab', 'materials')
  const [kind, setKind] = useRememberedState(memory, 'kind', 'all')
  const [search, setSearch] = useRememberedState(memory, 'search', '')
  const [property, setProperty] = useRememberedState(memory, 'property', 'all')
  const [state, setState] = useRememberedState(memory, 'availability', 'all')
  const [work, setWork] = useRememberedState(memory, 'work', 'all')
  const [page, setPage] = useRememberedState(memory, 'page', 1)
  const [figurePage, setFigurePage] = useRememberedState(memory, 'figurePage', 1)
  const rows = materials.filter(
    (m) =>
      (kind === 'all' ||
        (kind === 'cited' ? m.roles?.includes('cited') || m.kind === 'cited' : m.kind === kind)) &&
      [
        titleText(m),
        ...(m.authors || []),
        m.table_id,
        m.association?.catalog_id,
        ...(m.properties || []).map((p) => p.name),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(search.toLowerCase()) &&
      (property === 'all' ||
        m.assignments?.some((a) => a.property_id === property) ||
        m.properties?.some((p) => p.property_id === property)) &&
      (state === 'all' || m.availability === state),
  )
  const chosen = figures.filter(
    (f) =>
      (work === 'all' || f.source_id === work) &&
      (property === 'all' || f.property_ids?.includes(property)),
  )
  const maxPage = Math.max(1, Math.ceil(rows.length / 20)),
    current = Math.min(page, maxPage)
  const maxFigurePage = Math.max(1, Math.ceil(chosen.length / 12)),
    currentFigure = Math.min(figurePage, maxFigurePage)
  const citations = useMemo(
    () => [
      ...new Map(
        materials.flatMap((m) => m.citations || []).map((r) => [r.reference_id, r]),
      ).values(),
    ],
    [materials],
  )
  const resolved = citations.filter((r) => r.resolution_state === 'resolved')
  const citedWorks = new Set(resolved.map((r) => r.cited_work_id).filter(Boolean)).size
  const changeFilter = (setter) => (e) => {
    setter(e.target.value)
    setPage(1)
    setFigurePage(1)
  }
  return (
    <div className="materials-browser research-materials">
      <nav className="data-tabs" aria-label="资料浏览方式">
        {[
          ['materials', '资料档案'],
          ['figures', '研究图像'],
        ].map(([id, label]) => (
          <button
            key={id}
            className={'tab-btn' + (tab === id ? ' active' : '')}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>
      <div className="research-toolbar">
        {tab === 'materials' ? (
          <>
            <input
              className="workspace-search"
              placeholder="搜索题名、作者、目录或性质"
              aria-label="搜索资料"
              value={search}
              onChange={changeFilter(setSearch)}
            />
            <select
              className="workspace-select"
              aria-label="资料类型"
              value={kind}
              onChange={changeFilter(setKind)}
            >
              <option value="all">全部资料</option>
              {Object.entries(kinds).map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
            <select
              className="workspace-select"
              aria-label="资料状态"
              value={state}
              onChange={changeFilter(setState)}
            >
              <option value="all">全部状态</option>
              {[...new Set(materials.map((m) => m.availability).filter(Boolean))].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </>
        ) : (
          <select
            className="workspace-select"
            aria-label="图像作品"
            value={work}
            onChange={changeFilter(setWork)}
          >
            <option value="all">全部来源</option>
            {sources
              .filter((s) => figures.some((f) => f.source_id === s.source_id))
              .map((s) => (
                <option value={s.source_id} key={s.source_id}>
                  {titleText(s)}
                </option>
              ))}
          </select>
        )}
        <select
          className="workspace-select"
          aria-label={tab === 'figures' ? '图像性质' : '资料关联性质'}
          value={property}
          onChange={changeFilter(setProperty)}
        >
          <option value="all">全部性质</option>
          {properties.map((p) => (
            <option value={p.property_id} key={p.property_id}>
              {p.name || p.name_cn || p.definition?.name_cn}
            </option>
          ))}
        </select>
      </div>
      {tab === 'materials' ? (
        <>
          <p className="research-counts">
            当前显示 {rows.length} 份资料档案 · 本修订 {sources.length} 份提取来源
          </p>
          {citations.length > 0 && (
            <p className="research-counts">
              引用关系 {citations.length} 条 · 已解析 {resolved.length} 条 · 已解析被引作品{' '}
              {citedWorks} 篇
            </p>
          )}
          <div className="material-list">
            {rows.slice((current - 1) * 20, current * 20).map((m) => (
              <button
                className="material-entry"
                key={m.material_id}
                onClick={() => onOpenSource({ ...m, protocol_version: m.protocol_version || 2 })}
              >
                <div>
                  <span className="material-kind">
                    {kinds[m.kind] || '资料'}
                    {m.roles?.includes('cited') && m.kind !== 'cited' ? ' · 被引用' : ''}
                  </span>
                  <h3>{titleText(m)}</h3>
                  <p>{[m.authors?.[0], m.year, m.availability].filter(Boolean).join(' · ')}</p>
                </div>
                <div className="material-contribution">
                  {m.properties?.length ? (
                    m.properties.map((p) => (
                      <span key={p.property_id}>
                        {p.name} · {p.count} 条
                      </span>
                    ))
                  ) : (
                    <span>{m.kind === 'cited' ? '引用关联已保存' : '本修订贡献 0 条测量'}</span>
                  )}
                </div>
              </button>
            ))}
          </div>
          {!rows.length && <p>当前筛选没有匹配资料。</p>}
          <div className="research-pagination">
            <button disabled={current === 1} onClick={() => setPage(current - 1)}>
              上一页
            </button>
            <span>
              {current} / {maxPage}
            </span>
            <button disabled={current === maxPage} onClick={() => setPage(current + 1)}>
              下一页
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="research-counts">
            当前显示 {chosen.length} 幅图像 · 涉及 {new Set(chosen.map((f) => f.source_id)).size}{' '}
            份来源
          </p>
          <div className="figure-grid">
            {chosen.slice((currentFigure - 1) * 12, currentFigure * 12).map((f) => (
              <article
                className="figure-card"
                data-figure-id={f.figure_id}
                data-crop-precision={f.crop_precision}
                key={f.figure_id}
              >
                <button
                  className="figure-button"
                  aria-label={'查看研究图像 ' + (f.label || '') + ' 第' + f.page + '页'}
                  onClick={() => onOpenFigure({ ...f, galleryIds: chosen.map((x) => x.figure_id) })}
                >
                  <img
                    loading="lazy"
                    src={f.image_url || artifactUrl(f.task_id, f.image_artifact.artifact_id)}
                    alt={f.label || '研究图像'}
                  />
                </button>
                <div className="research-section-heading">
                  <h3>{f.label || '研究图像'}</h3>
                  <span>物理第 {f.page} 页</span>
                </div>
                <p className="figure-caption-preview">{f.caption}</p>
                <button className="text-link" onClick={() => onOpenFigure(f)}>
                  图像与原页
                </button>
              </article>
            ))}
          </div>
          {!chosen.length && <p>当前筛选没有研究图像。</p>}
          <div className="research-pagination">
            <button disabled={currentFigure === 1} onClick={() => setFigurePage(currentFigure - 1)}>
              上一页
            </button>
            <span>
              {currentFigure} / {maxFigurePage}
            </span>
            <button
              disabled={currentFigure === maxFigurePage}
              onClick={() => setFigurePage(currentFigure + 1)}
            >
              下一页
            </button>
          </div>
          {figures.coverage?.length > 0 && (
            <details className="research-image-coverage">
              <summary>按来源查看图像覆盖 · {figures.coverage.length} 份论文</summary>
              <div className="research-tags">
                {['available', 'partial', 'failed', 'checked_no_relevant'].map((s) => (
                  <span key={s}>
                    {stateText(s)} {figures.coverage.filter((c) => c.state === s).length}
                  </span>
                ))}
              </div>
              {figures.coverage.map((c, i) => (
                <div className="research-coverage-row" key={i}>
                  <span>{titleText(sources.find((s) => s.source_id === c.source_id))}</span>
                  <strong>{stateText(c.state)}</strong>
                </div>
              ))}
            </details>
          )}
        </>
      )}
    </div>
  )
}
