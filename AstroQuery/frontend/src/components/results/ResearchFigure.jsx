import { useEffect, useState } from 'react'
import SourceImageLightbox from './SourceImageLightbox'
import { artifactUrl } from '@/services/api'
import { titleText, stateText } from '@/lib/researchDisplay'

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
  const image = figure.image_url || artifactUrl(figure.task_id, figure.image_artifact.artifact_id)
  const page = figure.page_url || artifactUrl(figure.task_id, figure.page_artifact.artifact_id)
  const precise = figure.crop_precision === 'native_single_caption_geometry'
  const box =
    precise && mode === 'page' && figure.page_bbox?.length === 4
      ? figure.page_bbox.map((n) => n * 1000)
      : null
  const url = mode === 'page' ? page : image
  return (
    <div className="context-content research-figure-detail">
      <div className="research-section-heading">
        <h3>{figure.label || '研究图像'}</h3>
        <span>{stateText(figure.crop_precision)}</span>
      </div>
      <div className="research-toolbar">
        <div className="workspace-chips">
          <button
            className={'filter-chip' + (mode === 'image' ? ' active' : '')}
            aria-pressed={mode === 'image'}
            onClick={() => setMode('image')}
          >
            保存图像
          </button>
          <button
            className={'filter-chip' + (mode === 'page' ? ' active' : '')}
            aria-pressed={mode === 'page'}
            onClick={() => setMode('page')}
          >
            原 PDF 页
          </button>
        </div>
        <button className="text-link" onClick={() => setZoom(true)}>
          放大查看
        </button>
      </div>
      {failed ? (
        <p role="status">图像读取失败，可打开原 PDF 页。</p>
      ) : (
        <button
          className="research-figure-stage"
          aria-label="放大研究图像"
          onClick={() => setZoom(true)}
        >
          <img src={url} alt={figure.label || '保存的研究图像'} onError={() => setFailed(true)} />
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
        </button>
      )}
      <p>PDF 物理第 {figure.page} 页</p>
      <div className="research-links">
        {onPrevious && (
          <button className="text-link" onClick={onPrevious}>
            上一张
          </button>
        )}
        {onNext && (
          <button className="text-link" onClick={onNext}>
            下一张
          </button>
        )}
        <a
          className="text-link"
          href={
            figure.pdf_url ||
            artifactUrl(figure.task_id, figure.pdf_artifact_id) + '#page=' + figure.page
          }
          target="_blank"
          rel="noreferrer"
        >
          打开原 PDF 页
        </a>
      </div>
      <section>
        <h4>原始图注</h4>
        <blockquote>{figure.caption || '此历史版本未保存图注'}</blockquote>
      </section>
      {source && (
        <button className="record-source-card" onClick={() => onOpenSource?.(source)}>
          <strong>来源资料</strong>
          <span>{titleText(source)}</span>
        </button>
      )}
      {(figure.association_quote || figure.description) && (
        <details>
          <summary>与目标和性质的关联依据</summary>
          <p>{figure.description}</p>
          <blockquote>{figure.association_quote}</blockquote>
        </details>
      )}
      {zoom && (
        <SourceImageLightbox
          label={mode === 'page' ? '研究图像原页' : '研究图像'}
          url={url}
          bbox={box}
          source="native_text"
          onClose={() => setZoom(false)}
        />
      )}
    </div>
  )
}
