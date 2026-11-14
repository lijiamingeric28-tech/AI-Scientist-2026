import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Icon } from '@/components/icons'
import { createGraphFrameScheduler, endpoint, fitGraphCamera, graphNeighbors, graphNodeAction, layoutKnowledgeGraph, nodeKind, resizeGraphCamera, selectGraphEdgeLabels, selectGraphLabels, zoomGraphCamera } from '@/lib/knowledgeGraph'
import { readGraphTheme, graphEdgeDash, graphCategoryColor } from '@/lib/graphTheme'
import './knowledgeGraph.css'

const EMPTY = { nodes: [], edges: [], categories: [] }
const validCamera = value => value && [value.x, value.y, value.scale].every(Number.isFinite) && value.scale > 0

export default function KnowledgeGraphView({
  graphData = EMPTY, loading = false, graphReady = true, selectedNodeId,
  onSelectNode, onEnterCategory, onEnterProperty, onFocus, onShowAllRelations,
  onBack, onOpenMatrix, canGoBack = false, sceneKey = 'overview', viewState, onViewStateChange,
  nodeBudget = 80, onBudgetChange, domain = 'knowledge',
}) {
  const containerRef = useRef(null), canvasRef = useRef(null)
  const openedAt = useRef(performance.now())
  const drawing = useRef({ nodes: [], edges: [], labels: [], colors: {}, categories: new Map() })
  const camera = useRef({ x: 0, y: 0, scale: 1 }), cameraScene = useRef(null), savedCamera = useRef(viewState)
  const viewport = useRef({ width: 0, height: 0 })
  savedCamera.current = viewState
  const selection = useRef({ selected: selectedNodeId, hovered: null })
  selection.current.selected = selectedNodeId
  const scheduler = useRef(null), entrance = useRef(0), cameraTimer = useRef(null)
  const callbacks = useRef({})
  callbacks.current = { onSelectNode, onEnterCategory, onEnterProperty, onOpenMatrix, onViewStateChange }
  const drag = useRef(null), sequence = useRef(0)
  const [layoutBusy, setLayoutBusy] = useState(false), [nodes, setNodes] = useState([])
  const [hoveredId, setHoveredId] = useState(null), [scale, setScale] = useState(1)
  const [directoryOpen, setDirectoryOpen] = useState(false)
  const data = graphData || EMPTY, meta = data.meta || {}
  const edges = useMemo(() => data.edges || [], [data.edges])

  const publishCamera = useCallback((immediate = false) => {
    clearTimeout(cameraTimer.current)
    const publish = () => { setScale(camera.current.scale); callbacks.current.onViewStateChange?.({ ...camera.current }) }
    if (immediate) publish(); else cameraTimer.current = setTimeout(publish, 120)
  }, [])
  const fit = useCallback(() => {
    const element = containerRef.current
    if (!element) return
    camera.current = fitGraphCamera(drawing.current.nodes, { width: element.clientWidth, height: element.clientHeight })
    scheduler.current?.invalidate(); publishCamera(true)
  }, [publishCamera])
  const activate = useCallback(node => {
    const action = graphNodeAction(node)
    if (!action) return
    if (action.type === 'matrix') callbacks.current.onOpenMatrix?.()
    else if (action.type === 'category') callbacks.current.onEnterCategory?.(action.id)
    else if (action.type === 'property') callbacks.current.onEnterProperty?.(action.id)
    else callbacks.current.onSelectNode?.(action.id)
    setDirectoryOpen(false)
  }, [])
  useEffect(() => { clearTimeout(cameraTimer.current); setHoveredId(null); selection.current.hovered = null; setDirectoryOpen(false) }, [sceneKey])

  useEffect(() => {
    const seq = ++sequence.current, input = data.nodes || []
    setLayoutBusy(Boolean(input.length))
    let worker, cancelled = false
    const focusId = meta.focus_id || (meta.view === 'focus' ? selectedNodeId : null)
    const finish = result => {
      if (cancelled || seq !== sequence.current) return
      Object.assign(drawing.current, { nodes: result, edges })
      setNodes(result); setLayoutBusy(false)
      if (import.meta.env.DEV && result.length && containerRef.current && !containerRef.current.dataset.readyMs) containerRef.current.dataset.readyMs = String(Math.round(performance.now() - openedAt.current))
      if (result.length && cameraScene.current !== sceneKey) {
        const element = containerRef.current
        camera.current = validCamera(savedCamera.current) ? { ...savedCamera.current } : fitGraphCamera(result, { width: element?.clientWidth || 900, height: element?.clientHeight || 600 })
        cameraScene.current = sceneKey; setScale(camera.current.scale)
      }
      entrance.current = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : performance.now()
      scheduler.current?.invalidate()
    }
    if (!input.length) finish([])
    else try {
      worker = new Worker(new URL('./knowledgeGraph.worker.js', import.meta.url), { type: 'module' })
      worker.onmessage = ({ data: result }) => { if (result.sequence === seq) finish(result.nodes) }
      worker.onerror = () => { worker.terminate(); finish(layoutKnowledgeGraph(input, edges, { focusId })) }
      worker.postMessage({ sequence: seq, nodes: input, edges, focusId })
    } catch { finish(layoutKnowledgeGraph(input, edges, { focusId })) }
    return () => { cancelled = true; worker?.terminate() }
    // Selection highlights the current scene without recomputing its layout.
  }, [data.nodes, edges, meta.view, meta.focus_id, sceneKey])

  useEffect(() => {
    drawing.current.categories = new Map((data.categories || []).map(c => [c.id, c]))
    scheduler.current?.invalidate()
  }, [data.categories])

  useEffect(() => {
    const container = containerRef.current, canvas = canvasRef.current, root = document.documentElement
    if (!container || !canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    let measuredPoints, frameCount = 0, frameSamples = []
    const readTheme = () => {
      drawing.current.colors = readGraphTheme(getComputedStyle(root))
      scheduler.current?.invalidate()
    }
    function render(time) {
      const { nodes: points, edges: links, categories, colors } = drawing.current
      const width = container.clientWidth, height = container.clientHeight
      if (width < 1 || height < 1) return false
      const started = performance.now(), dpr = Math.min(2, window.devicePixelRatio || 1)
      if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) { canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr) }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, width, height)
      const t = camera.current, focusId = selection.current.hovered || selection.current.selected
      const related = graphNeighbors(points, links, focusId)
      const reveal = entrance.current ? Math.max(0, Math.min(1, (time - entrance.current) / 280)) : 1
      const opacity = 1 - (1 - reveal) ** 3
      const byId = new Map(points.map(n => [n.id, n])), colorFor = n => n.color || categories.get(n.category)?.color || (n.category ? graphCategoryColor(n.category, colors) : colors.accent)
      const groups = new Map()
      for (const n of points) if (nodeKind(n) === 'entry') { const key = n.category || 'other'; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(n) }
      ctx.save(); ctx.translate(t.x, t.y); ctx.scale(t.scale, t.scale)
      for (const group of groups.values()) {
        const cx = group.reduce((s, n) => s + n.x, 0) / group.length, cy = group.reduce((s, n) => s + n.y, 0) / group.length
        const radius = Math.max(70, ...group.map(n => Math.hypot(n.x - cx, n.y - cy) + 35))
        const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius)
        gradient.addColorStop(0, colorFor(group[0])); gradient.addColorStop(1, colors.bg)
        ctx.globalAlpha = .065 * opacity; ctx.fillStyle = gradient; ctx.beginPath(); ctx.arc(cx, cy, radius, 0, Math.PI * 2); ctx.fill()
      }
      for (const link of links) {
        const a = byId.get(endpoint(link.source)), b = byId.get(endpoint(link.target))
        if (!a || !b) continue
        const active = focusId && (a.id === focusId || b.id === focusId)
        ctx.globalAlpha = opacity * (focusId ? active ? .68 : .07 : .25)
        ctx.strokeStyle = active ? colors.accent : colors.line; ctx.lineWidth = (active ? 1.5 : 1) / t.scale
        ctx.setLineDash(graphEdgeDash(link.relation_type, t.scale))
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke()
      }
      ctx.setLineDash([])
      for (const n of points) {
        const kind = nodeKind(n), focused = n.id === selection.current.selected || n.id === selection.current.hovered
        const alpha = opacity * (focusId && !related.has(n.id) ? .22 : 1), radius = n.radius * (.92 + .08 * opacity), c = colorFor(n)
        ctx.globalAlpha = alpha
        if (kind === 'category' || kind === 'aggregate') {
          ctx.fillStyle = c; ctx.globalAlpha = alpha * .075; ctx.beginPath(); ctx.arc(n.x, n.y, radius + 13, 0, Math.PI * 2); ctx.fill()
          ctx.globalAlpha = alpha; ctx.fillStyle = colors.surface; ctx.strokeStyle = c; ctx.lineWidth = 1.3 / t.scale
          ctx.beginPath(); ctx.arc(n.x, n.y, radius, 0, Math.PI * 2); ctx.fill(); ctx.stroke()
          ctx.fillStyle = colors.ink; ctx.font = `600 ${18 / Math.max(.7, t.scale)}px ${colors.font}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(String(n.count ?? ''), n.x, n.y)
        } else {
          ctx.fillStyle = kind === 'property' ? colors.surface : c; ctx.strokeStyle = focused || kind === 'property' ? colors.accent : c; ctx.lineWidth = (focused ? 2 : 1.3) / t.scale
          ctx.beginPath(); ctx.arc(n.x, n.y, radius, 0, Math.PI * 2); ctx.fill(); ctx.stroke()
          if (n.source_kind === 'type') {
            ctx.fillStyle = colors.ink; ctx.font = `600 ${12 / Math.max(.7, t.scale)}px ${colors.font}`
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(String(n.count ?? ''), n.x, n.y)
          } else if (kind === 'property') { ctx.fillStyle = colors.accent; ctx.beginPath(); ctx.arc(n.x, n.y, 3, 0, Math.PI * 2); ctx.fill() }
        }
        if (n.preferred && kind === 'entry') { ctx.strokeStyle = colors.gold; ctx.lineWidth = 1.2 / t.scale; ctx.beginPath(); ctx.arc(n.x, n.y, radius + 4 / t.scale, 0, Math.PI * 2); ctx.stroke() }
        if (focused) { ctx.globalAlpha = .22 * opacity; ctx.strokeStyle = colors.accent; ctx.lineWidth = 4 / t.scale; ctx.beginPath(); ctx.arc(n.x, n.y, radius + 5 / t.scale, 0, Math.PI * 2); ctx.stroke() }
      }
      ctx.restore()
      const labels = selectGraphLabels(points, links, { camera: t, width, height, selectedId: selection.current.selected, hoveredId: selection.current.hovered, measureText(text, size) { ctx.font = `500 ${size}px ${colors.font}`; return ctx.measureText(text).width } })
      drawing.current.labels = labels
      const edgeLabels = selectGraphEdgeLabels(points, links, { camera: t, width, height, selectedId: selection.current.selected, labels, measureText(text, size) { ctx.font = `500 ${size}px ${colors.font}`; return ctx.measureText(text).width } })
      for (const label of edgeLabels) {
        ctx.globalAlpha = opacity * .9; ctx.fillStyle = colors.surface; ctx.strokeStyle = colors.line; ctx.lineWidth = 1
        ctx.beginPath(); ctx.roundRect(label.x, label.y, label.width, label.height, 5); ctx.fill(); ctx.stroke()
        ctx.fillStyle = colors.accent; ctx.font = `500 10.5px ${colors.font}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
        ctx.fillText(label.text, label.x + label.width / 2, label.y + label.height / 2, label.width - 12)
      }
      for (const label of labels) {
        const n = byId.get(label.id)
        ctx.globalAlpha = opacity * (focusId && !related.has(n.id) ? .3 : 1); ctx.fillStyle = colors.surface; ctx.strokeStyle = colors.line; ctx.lineWidth = 1
        ctx.beginPath(); ctx.roundRect(label.x, label.y, label.width, label.height, 7); ctx.fill(); ctx.stroke()
        ctx.fillStyle = nodeKind(n) === 'entry' ? colors.ink : colors.accent; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.font = `500 ${label.fontSize}px ${colors.font}`
        ctx.fillText(label.text, label.x + label.width / 2, label.y + label.height / 2)
      }
      ctx.globalAlpha = 1
      if (performance.getEntriesByName('knowledge-graph-frame').length >= 120) performance.clearMeasures('knowledge-graph-frame')
      const ended = performance.now()
      performance.measure('knowledge-graph-frame', { start: started, end: ended })
      if (import.meta.env.DEV) {
        if (measuredPoints !== points) { measuredPoints = points; frameSamples = []; frameCount = 0 }
        frameSamples.push(ended - started); if (frameSamples.length > 120) frameSamples.shift()
        const sorted = [...frameSamples].sort((a, b) => a - b)
        canvas.dataset.nodeCount = String(points.length); canvas.dataset.frameCount = String(++frameCount)
        canvas.dataset.frameP95Ms = String(sorted[Math.max(0, Math.ceil(sorted.length * .95) - 1)].toFixed(2))
      }
      return reveal < 1
    }
    scheduler.current = createGraphFrameScheduler(requestAnimationFrame, cancelAnimationFrame, render); readTheme()
    const resize = new ResizeObserver(() => {
      const next = { width: container.clientWidth, height: container.clientHeight }
      if (drawing.current.nodes.length) {
        if (viewport.current.width > 0 && viewport.current.height > 0) {
          camera.current = resizeGraphCamera(camera.current, viewport.current, next)
          scheduler.current?.invalidate(); publishCamera(true)
        } else fit()
      } else scheduler.current?.invalidate()
      viewport.current = next
    }); resize.observe(container)
    const theme = new MutationObserver(readTheme); theme.observe(root, { attributes: true, attributeFilter: ['data-theme', 'data-contrast', 'style', 'class'] })
    const media = window.matchMedia('(prefers-reduced-motion: reduce)'), reduce = () => { if (media.matches) entrance.current = 0; scheduler.current?.invalidate() }; media.addEventListener('change', reduce)
    const wheel = e => {
      e.preventDefault(); const rect = canvas.getBoundingClientRect()
      camera.current = zoomGraphCamera(camera.current, Math.exp(-Math.max(-100, Math.min(100, e.deltaY)) * .0025), { x: e.clientX - rect.left, y: e.clientY - rect.top })
      selection.current.hovered = null; setHoveredId(null); scheduler.current.invalidate(); publishCamera()
    }
    canvas.addEventListener('wheel', wheel, { passive: false })
    return () => { scheduler.current.dispose(); resize.disconnect(); theme.disconnect(); media.removeEventListener('change', reduce); canvas.removeEventListener('wheel', wheel); clearTimeout(cameraTimer.current) }
  }, [fit, publishCamera])
  useEffect(() => { scheduler.current?.invalidate() }, [selectedNodeId])

  const hit = useCallback((x, y) => {
    const { nodes: points, labels } = drawing.current
    const label = labels.find(n => x >= n.x && x <= n.x + n.width && y >= n.y && y <= n.y + n.height)
    if (label) return points.find(n => n.id === label.id)
    const t = camera.current
    return [...points].reverse().find(n => Math.hypot(n.x * t.scale + t.x - x, n.y * t.scale + t.y - y) < Math.max(11, n.radius * t.scale + 4))
  }, [])
  const localPoint = event => { const rect = canvasRef.current.getBoundingClientRect(); return { x: event.clientX - rect.left, y: event.clientY - rect.top } }
  const onPointerDown = event => { if (event.button !== 0) return; drag.current = { ...localPoint(event), camera: { ...camera.current }, moved: false }; event.currentTarget.setPointerCapture(event.pointerId); event.currentTarget.focus({ preventScroll: true }) }
  const onPointerMove = event => {
    const point = localPoint(event)
    if (drag.current) {
      const dx = point.x - drag.current.x, dy = point.y - drag.current.y
      if (Math.hypot(dx, dy) > 4) drag.current.moved = true
      if (drag.current.moved) { camera.current = { ...drag.current.camera, x: drag.current.camera.x + dx, y: drag.current.camera.y + dy }; selection.current.hovered = null; setHoveredId(null); scheduler.current?.invalidate() }
    } else {
      const next = hit(point.x, point.y)?.id || null
      if (selection.current.hovered !== next) { selection.current.hovered = next; setHoveredId(next); scheduler.current?.invalidate() }
    }
  }
  const onPointerUp = event => {
    if (!drag.current) return
    const point = localPoint(event), moved = drag.current.moved; drag.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    if (moved) publishCamera(true); else activate(hit(point.x, point.y))
  }
  const zoom = factor => { const el = containerRef.current; camera.current = zoomGraphCamera(camera.current, factor, { x: el.clientWidth / 2, y: el.clientHeight / 2 }); scheduler.current?.invalidate(); publishCamera(true) }
  const onKeyDown = event => {
    if (event.key === 'Escape') { event.stopPropagation(); setDirectoryOpen(false); callbacks.current.onSelectNode?.(null); return }
    if (event.key === 'Home') { event.preventDefault(); fit(); return }
    if (['+', '=', '-'].includes(event.key)) { event.preventDefault(); zoom(event.key === '-' ? .8 : 1.25); return }
    const vector = { ArrowLeft: [45, 0], ArrowRight: [-45, 0], ArrowUp: [0, 45], ArrowDown: [0, -45] }[event.key]
    if (vector) { event.preventDefault(); camera.current = { ...camera.current, x: camera.current.x + vector[0], y: camera.current.y + vector[1] }; scheduler.current?.invalidate(); publishCamera(true) }
  }
  const hovered = nodes.find(n => n.id === hoveredId), busy = loading || layoutBusy || !graphReady
  return <section className="kg-atlas" aria-label={domain === 'registry' ? '天体类型与性质规范图谱' : '学术星系知识图谱'} onKeyDownCapture={event => { if (event.key === 'Escape' && directoryOpen) { event.preventDefault(); event.stopPropagation(); setDirectoryOpen(false) } }}>
    <div className="kg-scene-bar"><div className="kg-scene-location">
      {canGoBack && <button type="button" className="kg-back" onClick={onBack} aria-label="返回上一层图谱"><Icon.ArrowLeft /></button>}
      <span className="kg-scene-kicker">{domain === 'registry' ? '规范星系' : '知识星系'}</span><span className="kg-scene-separator" aria-hidden="true">/</span>
      <strong>{meta.view === 'focus' ? '关联聚焦' : meta.view === 'category' ? '分类探索' : meta.view === 'type' ? '类型适用性质' : meta.view === 'property' ? '性质适用范围' : '全库总览'}</strong>
    </div><div className="kg-scene-actions">{selectedNodeId && nodes.some(n => n.id === selectedNodeId && nodeKind(n) === 'entry') && <div className="kg-selected-actions"><button type="button" onClick={() => onFocus?.(selectedNodeId)}><Icon.Focus />聚焦关联</button><button type="button" onClick={() => onShowAllRelations?.(selectedNodeId)}>查看全部关联</button></div>}{onBudgetChange && <label className="kg-budget">展示上限<select aria-label="图谱展示上限" value={nodeBudget} onChange={event => onBudgetChange(Number(event.target.value))}>{[80, 120, 200].map(value => <option key={value} value={value}>{value} 节点</option>)}</select></label>}</div></div>
    <div className={`kg-canvas-area${hoveredId ? ' is-hovering' : ''}`} ref={containerRef}>
      <canvas ref={canvasRef} className="kg-canvas" tabIndex={0} aria-label="知识关系画布，可拖动和缩放；方向键平移，加减号缩放，Home适配；节点目录提供文字导航" onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={() => { drag.current = null; publishCamera(true) }} onPointerLeave={() => { if (!drag.current) { selection.current.hovered = null; setHoveredId(null); scheduler.current?.invalidate() } }} onKeyDownCapture={onKeyDown} />
      {busy && <div className="kg-loading" role="status"><span className="kg-loading-orbit" />正在整理知识星系…</div>}
      {!busy && !nodes.length && <div className="kg-empty"><Icon.Search /><strong>没有符合当前条件的知识</strong><p>调整分类或搜索关键词，再探索相关理论。</p></div>}
      {hovered && !drag.current && <div className="kg-hover-preview" role="status"><span>{domain === 'registry' ? ({type:'天体类型',property:'性质定义',aggregate:'聚合目录'}[hovered.source_kind] || '规范条目') : nodeKind(hovered) === 'category' ? '分类星系' : nodeKind(hovered) === 'property' ? '关联性质' : '理论知识'}</span><strong>{hovered.label || hovered.title}</strong><p>{hovered.count != null ? `${hovered.count} 个关联条目` : domain === 'registry' ? '点击阅读定义、适用关系与版本来源' : hovered.preferred ? '科研优选 · 点击阅读完整内容' : '点击阅读公式、适用条件与来源'}</p></div>}
      {Boolean(meta.truncated) && <p className="kg-coverage-note">当前展示为局部星系；全部匹配知识可在矩阵中浏览。</p>}
      <div className="kg-navigation" aria-label="图谱视角控制"><button type="button" onClick={() => zoom(1.25)} aria-label="放大图谱"><Icon.ZoomIn /></button><output aria-label="图谱缩放比例">{Math.round(scale * 100)}%</output><button type="button" onClick={() => zoom(.8)} aria-label="缩小图谱"><Icon.ZoomOut /></button><span /><button type="button" onClick={fit} aria-label="适配全部节点"><Icon.FitScreen /></button></div>
      <div className="kg-directory"><button type="button" onClick={() => setDirectoryOpen(value => !value)} aria-expanded={directoryOpen}>节点目录 <span>{nodes.length}</span></button>{directoryOpen && <div className="kg-directory-panel"><strong>当前星系中的节点</strong><div>{nodes.map(n => <button type="button" key={n.id} onClick={() => activate(n)}><i style={{ background: drawing.current.categories.get(n.category)?.color || 'var(--seed-accent)' }} /><span>{n.label || n.title || n.id}</span>{n.count != null && <small>{n.count}</small>}</button>)}</div></div>}</div>
    </div>
  </section>
}
