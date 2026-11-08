import { useEffect, useMemo } from 'react'
import { useRememberedState } from '@/hooks/useViewMemory'
import { artifactUrl } from '@/services/api'
import { titleText, stateText } from '@/lib/researchDisplay'
import { Icon } from '@/components/icons'

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
  onVisibleTab,
  figuresLoading = false,
  figuresError = false,
  onRetryFigures,
}) {
  const [tab, setTab] = useRememberedState(memory, 'tab', 'materials')
  useEffect(() => { if (active) onVisibleTab?.(tab) }, [active, tab, onVisibleTab])
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

  const getKindInfo = (m) => {
    if (m.kind === 'catalog') return { label: '星表目录', icon: Icon.Table, cls: 'catalog' }
    if (m.kind === 'official_attachment') return { label: '官方补充材料', icon: Icon.Bookmark, cls: 'attachment' }
    if (m.kind === 'cited') return { label: '第三方引文', icon: Icon.Quote, cls: 'cited' }
    return { label: '论文档案', icon: Icon.FileText, cls: 'paper' }
  }

  return (
    <div className="materials-browser research-materials">
      {/* 统一单行工具栏：视图切换药丸 + 搜索框 + 下拉筛选组 */}
      <div className="materials-unified-toolbar">
        <div className="materials-segmented-bar" role="tablist" aria-label="资料与图像浏览方式">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'materials'}
            className={'segmented-tab-btn' + (tab === 'materials' ? ' active' : '')}
            onClick={() => setTab('materials')}
          >
            <Icon.BookOpen style={{ width: 13, height: 13 }} />
            <span>资料档案</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'figures'}
            className={'segmented-tab-btn' + (tab === 'figures' ? ' active' : '')}
            onClick={() => setTab('figures')}
          >
            <Icon.Image style={{ width: 13, height: 13 }} />
            <span>研究图像</span>
          </button>
        </div>

        {tab === 'materials' && (
          <div className="materials-search-box">
            <Icon.Search className="search-icon-svg" />
            <input
              className="workspace-search-compact"
              placeholder="搜索题名、第一作者、星表编号或性质…"
              aria-label="搜索资料"
              value={search}
              onChange={changeFilter(setSearch)}
            />
          </div>
        )}

        <div className="materials-filter-dropdowns">
          {tab === 'materials' ? (
            <>
              <select
                className="materials-select-compact"
                aria-label="资料类型"
                value={kind}
                onChange={changeFilter(setKind)}
              >
                <option value="all">全部资料类型</option>
                {Object.entries(kinds).map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
              <select
                className="materials-select-compact"
                aria-label="资料状态"
                value={state}
                onChange={changeFilter(setState)}
              >
                <option value="all">全部归档状态</option>
                {[...new Set(materials.map((m) => m.availability).filter(Boolean))].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </>
          ) : (
            <select
              className="materials-select-compact"
              aria-label="图像作品"
              value={work}
              onChange={changeFilter(setWork)}
            >
              <option value="all">全部文献来源</option>
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
            className="materials-select-compact"
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
      </div>

      {/* 极简纤细学术统计行 */}
      <div className="materials-slim-stats-row">
        {tab === 'materials' ? (
          <>
            <span>当前显示 <strong>{rows.length}</strong> 份资料档案</span>
            <span className="stats-dot">·</span>
            <span>本修订 <strong>{sources.length}</strong> 份提取来源</span>
            {citations.length > 0 && (
              <>
                <span className="stats-dot">·</span>
                <span>引用关系 <strong>{citations.length}</strong> 条（已解析 <strong>{resolved.length}</strong> 条 · 被引作品 <strong>{citedWorks}</strong> 篇）</span>
              </>
            )}
          </>
        ) : (
          <>
            {!figuresLoading && !figuresError && <span>当前展示 <strong>{chosen.length}</strong> 幅科学研究图像</span>}
            <span className="stats-dot">·</span>
            <span>涉及 <strong>{new Set(chosen.map((f) => f.source_id)).size}</strong> 份文献来源</span>
          </>
        )}
      </div>

      {tab === 'materials' ? (
        <>

          {/* 资料档案卡片列表 */}
          <div className="materials-cards-grid">
            {rows.slice((current - 1) * 20, current * 20).map((m) => {
              const kindInfo = getKindInfo(m)
              const KindIcon = kindInfo.icon
              const isAvailable = m.availability && (m.availability.includes('已取得') || m.availability.includes('已归档') || m.availability === 'available')
              return (
                <article
                  className="material-archive-card active-press"
                  key={m.material_id}
                  onClick={() => onOpenSource({ ...m, protocol_version: m.protocol_version || 2 })}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') onOpenSource({ ...m, protocol_version: m.protocol_version || 2 }) }}
                >
                  <div className="material-card-header">
                    <div className="material-badges-row">
                      <span className={`material-badge kind ${kindInfo.cls}`}>
                        <KindIcon style={{ width: 12, height: 12 }} />
                        <span>{kindInfo.label}</span>
                      </span>
                      {m.roles?.includes('cited') && m.kind !== 'cited' && (
                        <span className="material-badge cited-role">
                          <Icon.Quote style={{ width: 11, height: 11 }} />
                          <span>被引用文献</span>
                        </span>
                      )}
                      {m.availability && (
                        <span className={`material-badge ${isAvailable ? 'status-ok' : 'year'}`}>
                          {isAvailable && <Icon.Check style={{ width: 11, height: 11, color: 'var(--accent)' }} />}
                          <span>{m.availability}</span>
                        </span>
                      )}
                      {m.year && (
                        <span className="material-badge year">
                          <span>{m.year}</span>
                        </span>
                      )}
                    </div>
                  </div>

                  <h3 className="material-card-title">{titleText(m)}</h3>

                  <div className="material-meta-row">
                    {m.authors?.[0] && (
                      <span className="material-author">
                        <Icon.User style={{ width: 13, height: 13 }} />
                        <span>{m.authors[0]}{m.authors.length > 1 ? ` 等 (${m.authors.length} 位作者)` : ''}</span>
                      </span>
                    )}
                    {m.table_id && (
                      <span className="material-table-badge">
                        表格: {m.table_id}
                      </span>
                    )}
                    {m.association?.catalog_id && (
                      <span className="material-table-badge">
                        星表: {m.association.catalog_id}
                      </span>
                    )}
                  </div>

                  <div className="material-card-footer">
                    <div className="material-contrib-tags">
                      {m.properties?.length ? (
                        m.properties.map((p) => (
                          <span key={p.property_id} className="contrib-pill">
                            {p.name} · {p.count} 条测量
                          </span>
                        ))
                      ) : (
                        <span className="contrib-pill zero">
                          {m.kind === 'cited' ? '引用关联已保存' : '本修订贡献 0 条直接测量'}
                        </span>
                      )}
                    </div>
                    <span className="material-action-affordance">
                      <span>查阅档案</span>
                      <Icon.ArrowRight style={{ width: 13, height: 13 }} />
                    </span>
                  </div>
                </article>
              )
            })}
          </div>

          {!rows.length && <div className="materials-empty-box">当前筛选条件下未检索到匹配的学术资料档案。</div>}

          {/* 分页控制条 */}
          <div className="research-pagination-bar">
            <button
              className="research-pagination-pill"
              disabled={current === 1}
              onClick={() => setPage(current - 1)}
            >
              <Icon.ChevronLeft style={{ width: 13, height: 13 }} />
              <span>上一页</span>
            </button>
            <span className="research-pagination-indicator">
              第 {current} / {maxPage} 页
            </span>
            <button
              className="research-pagination-pill"
              disabled={current === maxPage}
              onClick={() => setPage(current + 1)}
            >
              <span>下一页</span>
              <Icon.ChevronRight style={{ width: 13, height: 13 }} />
            </button>
          </div>
        </>
      ) : (
        <>

          {/* 研究图像画廊网格 */}
          <div className="figure-gallery-grid">
            {chosen.slice((currentFigure - 1) * 12, currentFigure * 12).map((f) => (
              <article
                className="figure-gallery-card"
                data-figure-id={f.figure_id}
                data-crop-precision={f.crop_precision}
                key={f.figure_id}
              >
                <div
                  className="figure-image-container"
                  role="button"
                  tabIndex={0}
                  aria-label={'查看研究图像 ' + (f.label || '') + ' 第' + f.page + '页'}
                  onClick={() => onOpenFigure({ ...f, galleryIds: chosen.map((x) => x.figure_id) })}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') onOpenFigure({ ...f, galleryIds: chosen.map((x) => x.figure_id) })
                  }}
                >
                  <img
                    loading="lazy"
                    decoding="async"
                    src={
                      f.image_url ||
                      (f.task_id && f.image_artifact?.artifact_id
                        ? artifactUrl(f.task_id, f.image_artifact.artifact_id)
                        : f.page_url || '')
                    }
                    alt={f.label || '研究图像'}
                  />
                  <span className="figure-hover-badge">
                    <Icon.Maximize style={{ width: 12, height: 12 }} />
                    <span>放大预览与定位</span>
                  </span>
                </div>

                <div className="figure-card-content">
                  <div>
                    <div className="figure-meta-bar">
                      <span className="figure-label-badge">{f.label || '研究图像'}</span>
                      <span className="figure-page-chip">
                        <Icon.FileText style={{ width: 11, height: 11 }} />
                        <span>物理第 {f.page} 页</span>
                      </span>
                    </div>

                    <p className="figure-caption-text" title={f.caption}>
                      {f.caption || '（论文未附加独立图注或由页面解析直接提取）'}
                    </p>
                  </div>

                  <div className="figure-action-row">
                    <button
                      type="button"
                      className="figure-action-btn"
                      onClick={() => onOpenFigure(f)}
                    >
                      <span>图像与原页</span>
                      <Icon.ArrowRight style={{ width: 13, height: 13 }} />
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>

          {figuresLoading && <p className="materials-empty-box" role="status">正在读取研究图像…</p>}
          {figuresError && <p className="resource-error" role="alert">研究图像读取失败。 <button className="text-link" onClick={onRetryFigures}>重新读取</button></p>}
          {!figuresLoading && !figuresError && !chosen.length && <div className="materials-empty-box">当前筛选条件下未检索到匹配的科学研究图像。</div>}

          {/* 图像分页控制条 */}
          <div className="research-pagination-bar">
            <button
              className="research-pagination-pill"
              disabled={currentFigure === 1}
              onClick={() => setFigurePage(currentFigure - 1)}
            >
              <Icon.ChevronLeft style={{ width: 13, height: 13 }} />
              <span>上一页</span>
            </button>
            <span className="research-pagination-indicator">
              第 {currentFigure} / {maxFigurePage} 页
            </span>
            <button
              className="research-pagination-pill"
              disabled={currentFigure === maxFigurePage}
              onClick={() => setFigurePage(currentFigure + 1)}
            >
              <span>下一页</span>
              <Icon.ChevronRight style={{ width: 13, height: 13 }} />
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
