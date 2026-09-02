import { useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'

/* 溯源图全屏查看器（图片浏览器式 lightbox）：
 * - 整页大图 + bbox 标注 (细红框 / 整表卡片 / 虚线兜底, 与缩略图同款样式)
 * - 滚轮缩放 (以光标为锚点, 1x–8x)、拖拽平移、双击 1:1、Esc/按钮/背板关闭
 * - 标注层与图片同处一个 transform 容器, 缩放平移时严格对齐
 */

const MIN_SCALE = 1
const MAX_SCALE = 8

function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)) }

export default function SourceImageLightbox({ url, bbox, source, onClose }) {
  const [failed, setFailed] = useState(false)
  const [view, setView] = useState({ scale: 1, pan: { x: 0, y: 0 } })
  const stageRef = useRef(null)   // 视口容器 (缩放锚点计算用)
  const dragRef = useRef(null)
  // 2026-09-01 bbox 漂移修复：给图片盒显式像素尺寸（fit 计算）。
  // 此前用 maxHeight:100%（wrapper↔img 互为基准的 % 自引用链），窗口/图比例变化时
  // 浏览器解析出不同布局尺寸 → bbox 百分比基准与 img 显示网格脱钩 → 放大后红框漂移。
  const [nat, setNat] = useState(null)          // {nw, nh} 原图尺寸（onLoad）
  const [stageBox, setStageBox] = useState(null) // {w, h} 舞台视口尺寸（ResizeObserver）
  useEffect(() => {
    const el = stageRef.current
    if (!el) return
    const apply = () => {
      const r = el.getBoundingClientRect()
      setStageBox({ w: r.width, h: r.height })
    }
    apply()
    const ro = new ResizeObserver(apply)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const fit = useMemo(() => {
    if (!nat || !stageBox || !stageBox.w || !stageBox.h) return null
    const s = Math.min(stageBox.w / nat.nw, stageBox.h / nat.nh, 1)  // ≤1：只缩不放
    return { w: Math.max(1, Math.round(nat.nw * s)), h: Math.max(1, Math.round(nat.nh * s)) }
  }, [nat, stageBox])

  const [x0, y0, x1, y1] = bbox
  const isTable = source === 'full_table'
  const isFallback = source === 'fallback'
  const overlay = isTable ? {
    border: '2.5px solid var(--accent)',
    background: 'color-mix(in srgb, var(--accent) 10%, transparent)',
    boxShadow: '0 0 0 9999px color-mix(in srgb, var(--overlay) 55%, transparent)',
  } : isFallback ? {
    border: '2.5px dashed var(--content-fg-tertiary)',
    background: 'transparent',
  } : {
    border: '2.5px solid var(--status-error)',
    background: 'color-mix(in srgb, var(--status-error) 14%, transparent)',
  }

  // Esc 关闭
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // 滚轮缩放 (原生非 passive 监听, 以光标为锚点)
  useEffect(() => {
    const el = stageRef.current
    if (!el) return
    const onWheel = (e) => {
      e.preventDefault()
      setView((s) => {
        const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15
        const ns = clamp(s.scale * factor, MIN_SCALE, MAX_SCALE)
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

  const zoomBy = (factor) => setView((s) => {
    const ns = clamp(s.scale * factor, MIN_SCALE, MAX_SCALE)
    return { scale: ns, pan: ns === 1 ? { x: 0, y: 0 } : s.pan }
  })

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

  if (failed) return null

  return (
    <div
      onClick={onClose}
      className="animate-fade-in"
      style={{
        position: 'fixed', inset: 0, zIndex: 220,
        background: 'var(--overlay)',
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* 工具条 (玻璃风格, 与 RecordDetail 弹窗统一) */}
      <div className="glass" style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px',
        flexShrink: 0,
        borderLeft: 'none', borderRight: 'none', borderTop: 'none',
        borderRadius: 0,
      }} onClick={(e) => e.stopPropagation()}>
        <span style={{ fontSize: 12, color: 'var(--content-fg-secondary)', flex: 1 }}>
          滚轮缩放 · 拖拽平移 · 双击 1:1 · Esc 关闭
          {isTable && ' · 表格整表定位'}
        </span>
        <Button variant="ghost" size="icon" title="缩小" onClick={() => zoomBy(1 / 1.25)}><Icon.Minus /></Button>
        <span className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg-secondary)', minWidth: 44, textAlign: 'center' }}>
          {Math.round(view.scale * 100)}%
        </span>
        <Button variant="ghost" size="icon" title="放大" onClick={() => zoomBy(1.25)}><Icon.Plus /></Button>
        <Button variant="ghost" size="icon" title="复位" onClick={() => setView({ scale: 1, pan: { x: 0, y: 0 } })}><Icon.Maximize /></Button>
        <Button variant="ghost" size="icon" title="关闭" onClick={onClose}><Icon.Close /></Button>
      </div>

      {/* 舞台: 图片 + 标注层 */}
      <div
        ref={stageRef}
        onClick={(e) => e.stopPropagation()}
        onDoubleClick={onDoubleClick}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        style={{
          flex: 1, minHeight: 0, overflow: 'hidden', position: 'relative',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: view.scale > 1.01 ? 'grab' : 'zoom-in', touchAction: 'none',
        }}
      >
        <div style={{
          // 显式像素尺寸（fit 计算，无 % 循环）——bbox 百分比绑定到与 img 完全一致的
          // 网格；缩放/平移仍作用于本容器（transform），红框与图永远整齐同动
          position: 'relative',
          width: fit ? `${fit.w}px` : '100%',
          height: fit ? `${fit.h}px` : '100%',
          maxWidth: '100%', maxHeight: '100%',
          transform: `translate(${view.pan.x}px, ${view.pan.y}px) scale(${view.scale})`,
          boxShadow: 'var(--shadow-modal)',
          borderRadius: 'var(--radius-md)',
          overflow: 'hidden',
          flexShrink: 0,
        }}>
          <img
            src={url}
            alt="溯源定位大图"
            onError={() => setFailed(true)}
            onLoad={(e) => {
              const im = e.target
              if (im.naturalWidth && im.naturalHeight) setNat({ nw: im.naturalWidth, nh: im.naturalHeight })
            }}
            style={{ display: 'block', width: '100%', height: '100%', objectFit: 'fill' }}
            draggable={false}
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
                position: 'absolute', left: `${x0 / 10}%`, top: `calc(${y0 / 10}% - 26px)`,
                fontSize: 12, padding: '2px 10px', borderRadius: 'var(--radius-pill)',
                color: 'var(--accent)', background: 'var(--surface-primary)',
                border: '1px solid var(--accent)', whiteSpace: 'nowrap',
              }}>
                表格定位 · 整表
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
