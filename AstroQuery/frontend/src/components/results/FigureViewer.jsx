import { useDismissTransition } from "@/hooks/useDismissTransition"
import { useDialogFocus } from "@/hooks/useDialogFocus"
import { useEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Button } from "@/components/ui/button"
import { Icon } from "@/components/icons"
import Markdown from "@/lib/markdown"

export function FigureLightboxModal({ fig, onClose }) {
  const dismissal = useDismissTransition(onClose)
  const dialogRef = useDialogFocus(true, dismissal.close)
  const [view, setView] = useState({ scale: 1, pan: { x: 0, y: 0 } })
  const [isMax, setIsMax] = useState(false)
  const [failed, setFailed] = useState(false)
  const stageRef = useRef(null)
  const dragRef = useRef(null)

  const clampScale = (v) => Math.min(8, Math.max(1, v))

  const zoomBy = (factor) => setView((s) => {
    const ns = clampScale(s.scale * factor)
    return { scale: ns, pan: ns === 1 ? { x: 0, y: 0 } : s.pan }
  })

  useEffect(() => {
    const onKey = (e) => {
      if (e.defaultPrevented) return
      if (!e.defaultPrevented && e.key === 'Escape') dismissal.close()
      if (e.key === '+' || e.key === '=') zoomBy(1.25)
      if (e.key === '-') zoomBy(1 / 1.25)
      if (e.key === '0') setView({ scale: 1, pan: { x: 0, y: 0 } })
      if (e.key === 'f' || e.key === 'F') setIsMax((m) => !m)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // 滚轮无级缩放 (原生非 passive 监听，以光标为锚点)
  useEffect(() => {
    const el = stageRef.current
    if (!el) return
    const onWheel = (e) => {
      e.preventDefault()
      setView((s) => {
        const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15
        const ns = clampScale(s.scale * factor)
        if (ns === s.scale) return s
        const rect = el.getBoundingClientRect()
        const cx = e.clientX - rect.left - rect.width / 2
        const cy = e.clientY - rect.top - rect.height / 2
        return {
          scale: ns,
          pan: {
            x: cx - (cx - s.pan.x) * (ns / s.scale),
            y: cy - (cy - s.pan.y) * (ns / s.scale),
          },
        }
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  const onDoubleClick = () => setView((s) =>
    s.scale > 1.1 ? { scale: 1, pan: { x: 0, y: 0 } }
      : { scale: 2.5, pan: { x: 0, y: 0 } })

  const onPointerDown = (e) => {
    if (view.scale <= 1.01) return
    dragRef.current = { x: e.clientX, y: e.clientY, pan: { ...view.pan } }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e) => {
    const d = dragRef.current
    if (!d) return
    setView((s) => ({ ...s, pan: { x: d.pan.x + (e.clientX - d.x), y: d.pan.y + (e.clientY - d.y) } }))
  }
  const onPointerUp = () => { dragRef.current = null }

  const b = fig.bbox || fig.bbox_2d
  const bboxStyle = useMemo(() => {
    if (!b || b.length < 4) return null
    const [x0, y0, x1, y1] = b
    const is1000 = x0 > 1 || x1 > 1 || y0 > 1 || y1 > 1
    const l = is1000 ? x0 / 10 : x0 * 100
    const t = is1000 ? y0 / 10 : y0 * 100
    const w = is1000 ? (x1 - x0) / 10 : (x1 - x0) * 100
    const h = is1000 ? (y1 - y0) / 10 : (y1 - y0) * 100
    return {
      left: `${l}%`,
      top: `${t}%`,
      width: `${w}%`,
      height: `${h}%`,
    }
  }, [b])

  return createPortal(
    <div
      onClick={dismissal.close}
      data-closing={dismissal.closing || undefined}
      className="animate-fade-in"
      style={{ position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 150, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        ref={dialogRef} data-closing={dismissal.closing || undefined} onAnimationEnd={dismissal.onAnimationEnd} onKeyDownCapture={dismissal.onKeyDownCapture} role="dialog" aria-modal="true" aria-label="研究图像" tabIndex={-1}
        className="animate-modal-in"
        data-component="figure-lightbox"
        style={{
          width: isMax ? '98vw' : 940,
          maxWidth: '98vw',
          height: isMax ? '96vh' : 'auto',
          maxHeight: '94vh',
          display: 'flex', flexDirection: 'column',
          background: 'var(--seed-surface)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-modal)',
          overflow: 'hidden',
          transition: 'width 0.2s ease, height 0.2s ease',
        }}
      >
        {/* 头部：标题 + 来源 + 缩放平移交互栏 + 全屏/关闭 */}
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--surface-border)', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, overflow: 'hidden' }}>
          <span style={{ fontSize: 'var(--text-note)', fontWeight: 550, color: 'var(--content-fg)', flexShrink: 0, whiteSpace: 'nowrap' }}>
            科学研究图像{fig.page != null ? ` · 第 ${fig.page} 页` : ''}
          </span>
          {fig.source_id && (
            <span className="font-mono" style={{ fontSize: 'var(--text-note)', color: 'var(--content-fg-tertiary)', minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {fig.source_id}
            </span>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0, marginLeft: 'auto' }}>
            <span style={{ fontSize: 'var(--text-note)', color: 'var(--content-fg-tertiary)', marginRight: 6 }}>
              滚轮缩放 · 拖拽平移 · 双击 1:1
            </span>
            <Button variant="ghost" size="icon" title="缩小 (-)" onClick={() => zoomBy(1 / 1.25)} style={{ width: 28, height: 28 }}>
              <Icon.Minus />
            </Button>
            <span className="font-mono" style={{ fontSize: 'var(--text-note)', color: 'var(--content-fg-secondary)', minWidth: 42, textAlign: 'center' }}>
              {Math.round(view.scale * 100)}%
            </span>
            <Button variant="ghost" size="icon" title="放大 (+)" onClick={() => zoomBy(1.25)} style={{ width: 28, height: 28 }}>
              <Icon.Plus />
            </Button>
            <Button variant="ghost" size="icon" title="复位 (0)" onClick={() => setView({ scale: 1, pan: { x: 0, y: 0 } })} style={{ width: 28, height: 28 }}>
              <Icon.Maximize />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title={isMax ? '恢复标准视口' : '最大化全屏比对 (F)'}
              onClick={() => setIsMax((m) => !m)}
              style={{ width: 28, height: 28, color: isMax ? 'var(--accent)' : 'inherit' }}
            >
              <Icon.PanelRight />
            </Button>
            <Button variant="ghost" size="icon" title="关闭 (Esc)" onClick={dismissal.close} style={{ width: 28, height: 28 }}>
              <Icon.Close />
            </Button>
          </div>
        </div>

        {/* 视口舞台区 */}
        <div
          ref={stageRef}
          onDoubleClick={onDoubleClick}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          style={{
            flex: 1, minHeight: isMax ? '60vh' : 380, maxHeight: isMax ? '80vh' : '65vh',
            background: 'var(--surface-secondary)',
            overflow: 'hidden', position: 'relative',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: view.scale > 1.01 ? (dragRef.current ? 'grabbing' : 'grab') : 'zoom-in',
            touchAction: 'none', userSelect: 'none',
          }}
        >
          {fig.image_url && !failed ? (
            <div
              style={{
                position: 'relative',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                maxWidth: '92%', maxHeight: '92%',
                transform: `translate(${view.pan.x}px, ${view.pan.y}px) scale(${view.scale})`,
                transformOrigin: 'center center',
                transition: dragRef.current ? 'none' : 'transform 0.08s ease-out',
              }}
            >
              <img
                src={fig.image_url}
                alt={fig.caption || ''}
                onError={() => setFailed(true)}
                draggable={false}
                style={{
                  display: 'block', maxWidth: '100%', maxHeight: isMax ? '74vh' : '58vh',
                  objectFit: 'contain', borderRadius: 'var(--radius-sm)',
                  boxShadow: 'var(--shadow-modal)',
                  pointerEvents: 'none',
                }}
              />
              {bboxStyle && (
                <div
                  style={{
                    position: 'absolute',
                    ...bboxStyle,
                    border: '2px solid var(--status-error)',
                    borderRadius: 2,
                    background: 'color-mix(in srgb, var(--status-error) 15%, transparent)',
                    pointerEvents: 'none',
                  }}
                />
              )}
            </div>
          ) : (
            <span className="hint-dim">该研究图像无可用图像文件</span>
          )}
        </div>

        {/* 图注 + 来源（Markdown 渲染） */}
        {fig.caption && (
          <div style={{ padding: '12px 18px 14px', borderTop: '1px solid var(--surface-border)', flexShrink: 0, maxHeight: 160, overflowY: 'auto' }}>
            <div style={{
              padding: '10px 14px', background: 'var(--surface-secondary)', borderRadius: 'var(--radius-md)',
              borderLeft: '1px solid var(--accent)', fontSize: 'var(--text-note)', lineHeight: 1.7,
              color: 'var(--content-fg-secondary)',
            }}>
              <Markdown>{fig.caption}</Markdown>
            </div>
            {fig.description && <p>{fig.description}</p>}
            {fig.relevance && <p>相关性：{fig.relevance}</p>}
            {fig.target_association && <p>目标定位：{fig.target_association}</p>}
            {fig.page_url && <p><a href={fig.page_url} target="_blank" rel="noreferrer">查看原页</a> · <a href={fig.pdf_url} target="_blank" rel="noreferrer">打开论文PDF</a> · {fig.version_grade === 'preprint' ? '预印本' : fig.version_grade === 'published' ? '正式版' : fig.version_grade === 'accepted' ? '接受稿' : '版本等级未确认'}</p>}
            {fig.source_id && (
              <div className="font-mono hint-dim" style={{ marginTop: 8, fontSize: 'var(--text-note)' }}>来源：{fig.source_id}</div>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
