import { useEffect, useState } from 'react'
import SourceImageLightbox from './SourceImageLightbox'
import { artifactUrl } from '@/services/api'
import { titleText } from '@/lib/researchDisplay'
import { Icon } from '@/components/icons'

export default function ResearchFigure({ figure, sources = [], onOpenSource, onPrevious, onNext }) {
  const [mode, setMode] = useState('image'),
    [zoom, setZoom] = useState(false),
    [failed, setFailed] = useState(false)
  useEffect(() => {
    setMode('image')
    setZoom(false)
    setFailed(false)
  }, [figure.figure_id])
  useEffect(() => setFailed(false), [mode])
  useEffect(() => {
    const key = (event) => {
      if (zoom || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) return
      if (event.key === 'ArrowLeft' && onPrevious) {
        event.preventDefault()
        onPrevious()
      }
      if (event.key === 'ArrowRight' && onNext) {
        event.preventDefault()
        onNext()
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [zoom, onPrevious, onNext])

  const source = sources.find((s) => s.source_id === figure.source_id)
  const image = figure.image_url || (figure.task_id && figure.image_artifact ? artifactUrl(figure.task_id, figure.image_artifact.artifact_id) : '')
  const page = figure.page_url || (figure.task_id && figure.page_artifact ? artifactUrl(figure.task_id, figure.page_artifact.artifact_id) : '')
  const precise = figure.crop_precision === 'native_single_caption_geometry'
  const box =
    precise && mode === 'page' && figure.page_bbox?.length === 4
      ? figure.page_bbox.map((n) => n * 1000)
      : null
  const url = mode === 'page' ? page : (image || page)

  // Non-defensive crop label
  const cropLabel = figure.crop_precision === 'native_single_caption_geometry'
    ? '独立图例精细裁切'
    : '文献原版面收录'

  const captionContent = figure.caption && figure.caption.trim() && !figure.caption.includes('未保存图注')
    ? figure.caption
    : '文献正文未标注独立题注，已按上下文原版面展示收录。'

  return (
    <div className="context-content research-figure-detail" style={{ padding: '20px 24px 36px' }}>
      {/* 1. 图例身份卡片 */}
      <div className="figure-hero-card">
        <div className="figure-hero-header">
          <div className="figure-badges-row">
            <span className="figure-label-pill">
              <Icon.Image style={{ width: 13, height: 13 }} />
              <span>{figure.label || '研究图像'}</span>
            </span>
            <span className="figure-page-pill">
              <Icon.FileText style={{ width: 12, height: 12 }} />
              <span>文献第 {figure.page} 页 (PDF p.{figure.page})</span>
            </span>
            <span className={`figure-status-pill ${precise ? 'status-precise' : 'status-page'}`}>
              {precise ? <Icon.Maximize style={{ width: 11, height: 11 }} /> : <Icon.Layers style={{ width: 11, height: 11 }} />}
              <span>{cropLabel}</span>
            </span>
          </div>

          {/* 顶栏上一张/下一张翻页导航 */}
          {(onPrevious || onNext) && (
            <div className="figure-nav-group">
              <button
                type="button"
                className="figure-nav-btn active-press"
                disabled={!onPrevious}
                onClick={onPrevious}
                title="上一张图 (左箭头)"
              >
                <Icon.ChevronLeft style={{ width: 13, height: 13 }} />
                <span>上一张</span>
              </button>
              <button
                type="button"
                className="figure-nav-btn active-press"
                disabled={!onNext}
                onClick={onNext}
                title="下一张图 (右箭头)"
              >
                <span>下一张</span>
                <Icon.ChevronRight style={{ width: 13, height: 13 }} />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* 2. 图像呈现模式切换与操作条 */}
      <div className="figure-toolbar-unified">
        <div className="segmented-switch-group">
          <button
            type="button"
            className={`segmented-switch-btn ${mode === 'image' ? 'active' : ''}`}
            onClick={() => setMode('image')}
          >
            <Icon.Image style={{ width: 13, height: 13 }} />
            <span>裁切高清图</span>
          </button>
          <button
            type="button"
            className={`segmented-switch-btn ${mode === 'page' ? 'active' : ''}`}
            onClick={() => setMode('page')}
          >
            <Icon.FileText style={{ width: 13, height: 13 }} />
            <span>原版面上下文</span>
          </button>
        </div>

        <div className="figure-actions-right">
          <button
            type="button"
            className="figure-action-pill-btn active-press"
            onClick={() => setZoom(true)}
          >
            <Icon.Maximize style={{ width: 13, height: 13 }} />
            <span>放大全屏查看</span>
          </button>
          <a
            className="figure-action-pill-btn active-press"
            href={
              figure.pdf_url ||
              (figure.task_id && figure.pdf_artifact_id ? artifactUrl(figure.task_id, figure.pdf_artifact_id) + '#page=' + figure.page : '#')
            }
            target="_blank"
            rel="noreferrer"
          >
            <span>在 PDF 中打开</span>
            <Icon.ExternalLink style={{ width: 12, height: 12 }} />
          </a>
        </div>
      </div>

      {/* 3. 图像观片台容器 */}
      {failed ? (
        <div className="figure-failed-box">
          <p>图像解析流读取受阻，可切换至原版面或直接在原 PDF 中查阅。</p>
          <button type="button" className="text-link" onClick={() => setMode('page')}>
            切换为原版面
          </button>
        </div>
      ) : (
        <div
          className="figure-stage-vessel"
          role="button"
          tabIndex={0}
          onClick={() => setZoom(true)}
          onKeyDown={(e) => { if (e.key === 'Enter') setZoom(true) }}
          aria-label="放大研究图像"
        >
          <img src={url} alt={figure.label || '研究图像'} onError={() => setFailed(true)} />
          {box && (
            <span
              data-figure-crop
              style={{
                left: box[0] / 10 + '%',
                top: box[1] / 10 + '%',
                width: (box[2] - box[0]) / 10 + '%',
                height: (box[3] - box[1]) / 10 + '%',
              }}
            />
          )}
          <div className="figure-stage-hover-hint">
            <Icon.Maximize style={{ width: 14, height: 14 }} />
            <span>点击进入无级无损放大探索</span>
          </div>
        </div>
      )}

      {/* 4. 原始图注学术舱 */}
      <div className="figure-caption-card">
        <div className="figure-card-section-title">
          <Icon.AlignLeft style={{ width: 15, height: 15, color: 'var(--accent)' }} />
          <span>原始文献图注 (Original Caption)</span>
        </div>
        <blockquote className="figure-caption-quote">
          {captionContent}
        </blockquote>
      </div>

      {/* 5. 科学目标关联依据 */}
      {(figure.association_quote || figure.description) && (
        <div className="figure-association-card">
          <div className="figure-card-section-title">
            <Icon.Sparkle style={{ width: 15, height: 15, color: 'var(--accent)' }} />
            <span>科学目标关联分析与原文章节依据</span>
          </div>
          {figure.description && (
            <p className="figure-association-desc">{figure.description}</p>
          )}
          {figure.association_quote && (
            <blockquote className="figure-association-quote">
              {figure.association_quote}
            </blockquote>
          )}
        </div>
      )}

      {/* 6. 所属母体文献卡片 */}
      {source && (
        <div
          className="figure-source-card active-press"
          role="button"
          tabIndex={0}
          onClick={() => onOpenSource?.(source)}
          onKeyDown={(e) => { if (e.key === 'Enter') onOpenSource?.(source) }}
        >
          <div className="figure-source-header">
            <div className="figure-source-tag">
              <Icon.BookOpen style={{ width: 13, height: 13 }} />
              <span>所属母体学术文献</span>
            </div>
            <span className="figure-source-action">
              <span>查阅文献档案</span>
              <Icon.ArrowRight style={{ width: 13, height: 13 }} />
            </span>
          </div>
          <div className="figure-source-title">{titleText(source)}</div>
        </div>
      )}

      {zoom && (
        <SourceImageLightbox
          label={mode === 'page' ? '研究图像原版面' : '研究图像'}
          url={url}
          bbox={box}
          source="native_text"
          onClose={() => setZoom(false)}
        />
      )}
    </div>
  )
}
