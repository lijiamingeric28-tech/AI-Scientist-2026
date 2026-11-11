import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react'
import { Icon } from '@/components/icons'
import { LatexMath, LatexText } from '@/components/results/LatexMath'
import { KNOWLEDGE_CATEGORIES, getCategoryInfo } from './knowledgeConstants'

export default function KnowledgeGraphView({
  graphData,
  selectedCategory = 'all',
  selectedNodeId = null,
  onSelectNode,
  onTogglePreference,
  onEdit,
  onFork,
}) {
  const canvasRef = useRef(null)
  const containerRef = useRef(null)

  // Camera transform: { x, y, scale }
  const transformRef = useRef({ x: 0, y: 0, scale: 1 })
  const [transformState, setTransformState] = useState({ scale: 1 })

  // Simulation state
  const simRunningRef = useRef(true)
  const [isSimRunning, setIsSimRunning] = useState(true)
  const [legendOpen, setLegendOpen] = useState(true)

  // Dragging state
  const dragRef = useRef({
    isDraggingNode: false,
    draggedNode: null,
    isPanning: false,
    startX: 0,
    startY: 0,
    lastPanX: 0,
    lastPanY: 0,
  })

  // Selected node in local state
  const [activeNode, setActiveNode] = useState(null)
  const [hoveredNode, setHoveredNode] = useState(null)

  // Simulation nodes and links
  const simNodesRef = useRef([])
  const simLinksRef = useRef([])

  // Prepare nodes and links based on filters
  const { filteredNodes, filteredLinks } = useMemo(() => {
    if (!graphData || !Array.isArray(graphData.nodes)) {
      return { filteredNodes: [], filteredLinks: [] }
    }

    let nodes = graphData.nodes
    if (selectedCategory !== 'all') {
      const cat = KNOWLEDGE_CATEGORIES.find(c => c.id === selectedCategory)
      nodes = nodes.filter(n => {
        if (n.is_property) return true // keep property connectors
        const cId = n.category || 'physical_laws'
        return cId === selectedCategory || cat?.altNames?.includes(cId)
      })
    }

    const nodeIds = new Set(nodes.map(n => n.id))
    const links = (graphData.edges || []).filter(
      e => nodeIds.has(e.source?.id || e.source) && nodeIds.has(e.target?.id || e.target)
    )

    return { filteredNodes: nodes, filteredLinks: links }
  }, [graphData, selectedCategory])

  // Initialize simulation nodes
  useEffect(() => {
    const existingMap = new Map(simNodesRef.current.map(n => [n.id, n]))
    const width = containerRef.current?.clientWidth || 800
    const height = containerRef.current?.clientHeight || 600

    const newSimNodes = filteredNodes.map((n, i) => {
      const existing = existingMap.get(n.id)
      if (existing) {
        return {
          ...n,
          x: existing.x,
          y: existing.y,
          vx: existing.vx,
          vy: existing.vy,
          radius: n.is_property ? 16 : 22,
        }
      }
      // Circular initial layout
      const angle = (i / Math.max(1, filteredNodes.length)) * 2 * Math.PI
      const dist = 120 + Math.random() * 180
      return {
        ...n,
        x: width / 2 + Math.cos(angle) * dist,
        y: height / 2 + Math.sin(angle) * dist,
        vx: 0,
        vy: 0,
        radius: n.is_property ? 16 : 22,
      }
    })

    simNodesRef.current = newSimNodes

    const simNodeMap = new Map(newSimNodes.map(n => [n.id, n]))
    simLinksRef.current = filteredLinks
      .map(l => ({
        source: simNodeMap.get(l.source?.id || l.source),
        target: simNodeMap.get(l.target?.id || l.target),
        label: l.label || l.relation || '',
      }))
      .filter(l => l.source && l.target)

    simRunningRef.current = true
    setIsSimRunning(true)
  }, [filteredNodes, filteredLinks])

  // Sync selected node with prop
  useEffect(() => {
    if (selectedNodeId) {
      const found = filteredNodes.find(n => n.id === selectedNodeId)
      if (found) setActiveNode(found)
    }
  }, [selectedNodeId, filteredNodes])

  // Render loop & physics step
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let animId

    const stepSimulation = () => {
      if (!simRunningRef.current) return
      const nodes = simNodesRef.current
      const links = simLinksRef.current
      const width = canvas.width / (window.devicePixelRatio || 1)
      const height = canvas.height / (window.devicePixelRatio || 1)
      const centerX = width / 2
      const centerY = height / 2

      // 1. Repulsion between all node pairs
      for (let i = 0; i < nodes.length; i++) {
        const n1 = nodes[i]
        for (let j = i + 1; j < nodes.length; j++) {
          const n2 = nodes[j]
          const dx = n2.x - n1.x
          const dy = n2.y - n1.y
          const distSq = dx * dx + dy * dy || 1
          const dist = Math.sqrt(distSq)
          const force = (n1.is_property || n2.is_property ? 800 : 1800) / distSq
          const fx = (dx / dist) * force
          const fy = (dy / dist) * force

          if (!n1.fixed) {
            n1.vx -= fx
            n1.vy -= fy
          }
          if (!n2.fixed) {
            n2.vx += fx
            n2.vy += fy
          }
        }
      }

      // 2. Spring attraction along links
      for (const link of links) {
        const s = link.source
        const t = link.target
        const dx = t.x - s.x
        const dy = t.y - s.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const idealDist = s.is_property || t.is_property ? 110 : 160
        const spring = (dist - idealDist) * 0.04
        const fx = (dx / dist) * spring
        const fy = (dy / dist) * spring

        if (!s.fixed) {
          s.vx += fx
          s.vy += fy
        }
        if (!t.fixed) {
          t.vx -= fx
          t.vy -= fy
        }
      }

      // 3. Center gravity and velocity update
      let totalVel = 0
      for (const n of nodes) {
        if (!n.fixed) {
          const gx = (centerX - n.x) * 0.005
          const gy = (centerY - n.y) * 0.005
          n.vx += gx
          n.vy += gy

          n.vx *= 0.85
          n.vy *= 0.85
          n.x += n.vx
          n.y += n.vy

          totalVel += Math.abs(n.vx) + Math.abs(n.vy)
        }
      }

      if (totalVel < 0.05) {
        simRunningRef.current = false
        setIsSimRunning(false)
      }
    }

    const render = () => {
      stepSimulation()

      const dpr = window.devicePixelRatio || 1
      const rect = containerRef.current?.getBoundingClientRect()
      if (rect) {
        if (canvas.width !== rect.width * dpr || canvas.height !== rect.height * dpr) {
          canvas.width = rect.width * dpr
          canvas.height = rect.height * dpr
        }
      }

      ctx.save()
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      const t = transformRef.current
      ctx.translate(t.x, t.y)
      ctx.scale(t.scale, t.scale)

      const nodes = simNodesRef.current
      const links = simLinksRef.current

      // Draw background grid dots
      ctx.fillStyle = 'rgba(128, 128, 128, 0.08)'
      const gridSize = 40
      const startX = Math.floor((-t.x / t.scale) / gridSize) * gridSize
      const endX = startX + ((rect?.width || 800) / t.scale) + gridSize * 2
      const startY = Math.floor((-t.y / t.scale) / gridSize) * gridSize
      const endY = startY + ((rect?.height || 600) / t.scale) + gridSize * 2

      for (let gx = startX; gx < endX; gx += gridSize) {
        for (let gy = startY; gy < endY; gy += gridSize) {
          ctx.beginPath()
          ctx.arc(gx, gy, 1, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      // 1. Draw Edges
      for (const link of links) {
        const s = link.source
        const target = link.target
        const isConnected =
          activeNode && (s.id === activeNode.id || target.id === activeNode.id)
        const isHovered =
          hoveredNode && (s.id === hoveredNode.id || target.id === hoveredNode.id)

        ctx.beginPath()
        ctx.moveTo(s.x, s.y)
        ctx.lineTo(target.x, target.y)

        if (isConnected || isHovered) {
          ctx.strokeStyle = 'var(--accent, #14b8a6)'
          ctx.lineWidth = 2.5
        } else {
          ctx.strokeStyle = 'rgba(128, 128, 128, 0.22)'
          ctx.lineWidth = 1.2
        }
        ctx.stroke()

        // Edge label (only if connected or high zoom)
        if (link.label && (isConnected || t.scale > 1.1)) {
          const midX = (s.x + target.x) / 2
          const midY = (s.y + target.y) / 2
          ctx.font = '10px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
          ctx.fillStyle = isConnected ? 'var(--accent, #14b8a6)' : 'rgba(128, 128, 128, 0.7)'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(link.label, midX, midY - 6)
        }
      }

      // 2. Draw Nodes
      for (const n of nodes) {
        const isSelected = activeNode?.id === n.id
        const isHovered = hoveredNode?.id === n.id
        const isPreferred = Boolean(n.preferred || n.user_preference === 'preferred')
        const catInfo = getCategoryInfo(n.category)

        // Preferred Gold Glow Ring
        if (isPreferred && !n.is_property) {
          ctx.beginPath()
          ctx.arc(n.x, n.y, n.radius + 6, 0, Math.PI * 2)
          ctx.strokeStyle = 'rgba(234, 179, 8, 0.45)'
          ctx.lineWidth = 2
          ctx.setLineDash([4, 2])
          ctx.stroke()
          ctx.setLineDash([])
        }

        // Selection Ring
        if (isSelected) {
          ctx.beginPath()
          ctx.arc(n.x, n.y, n.radius + (isPreferred ? 9 : 6), 0, Math.PI * 2)
          ctx.strokeStyle = 'var(--accent, #14b8a6)'
          ctx.lineWidth = 2.5
          ctx.stroke()
        }

        // Node Circle Body
        ctx.beginPath()
        ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2)
        ctx.fillStyle = n.is_property
          ? 'rgba(128, 128, 128, 0.15)'
          : `${catInfo.color}25`
        ctx.fill()

        ctx.strokeStyle = n.is_property
          ? 'rgba(128, 128, 128, 0.5)'
          : catInfo.color
        ctx.lineWidth = isSelected || isHovered ? 2.5 : 1.8
        ctx.stroke()

        // Inner marker: Star for preferred, dot for standard
        if (isPreferred && !n.is_property) {
          ctx.beginPath()
          ctx.arc(n.x, n.y, 4, 0, Math.PI * 2)
          ctx.fillStyle = '#eab308'
          ctx.fill()
        }

        // Node Label
        ctx.font = `${n.is_property ? 11 : 12}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
        ctx.fillStyle = isSelected ? 'var(--accent, #14b8a6)' : 'var(--content-fg, #e2e8f0)'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'

        const labelText = n.label || n.title || n.name || n.id
        // Truncate long labels
        const displayLabel = labelText.length > 16 ? labelText.slice(0, 15) + '…' : labelText
        ctx.fillText(displayLabel, n.x, n.y + n.radius + 4)
      }

      ctx.restore()
      animId = requestAnimationFrame(render)
    }

    animId = requestAnimationFrame(render)
    return () => cancelAnimationFrame(animId)
  }, [activeNode, hoveredNode])

  // Mouse / Pointer handlers
  const screenToWorld = useCallback((clientX, clientY) => {
    const rect = canvasRef.current.getBoundingClientRect()
    const t = transformRef.current
    const screenX = clientX - rect.left
    const screenY = clientY - rect.top
    const worldX = (screenX - t.x) / t.scale
    const worldY = (screenY - t.y) / t.scale
    return { worldX, worldY }
  }, [])

  const findNodeAt = useCallback(
    (clientX, clientY) => {
      const { worldX, worldY } = screenToWorld(clientX, clientY)
      for (const n of simNodesRef.current) {
        const dx = worldX - n.x
        const dy = worldY - n.y
        if (dx * dx + dy * dy <= (n.radius + 6) * (n.radius + 6)) {
          return n
        }
      }
      return null
    },
    [screenToWorld]
  )

  const handlePointerDown = (e) => {
    if (e.button !== 0) return // only left click
    const hit = findNodeAt(e.clientX, e.clientY)

    if (hit) {
      dragRef.current.isDraggingNode = true
      dragRef.current.draggedNode = hit
      hit.fixed = true
      simRunningRef.current = true
      setIsSimRunning(true)
    } else {
      dragRef.current.isPanning = true
      dragRef.current.startX = e.clientX
      dragRef.current.startY = e.clientY
      dragRef.current.lastPanX = transformRef.current.x
      dragRef.current.lastPanY = transformRef.current.y
    }
  }

  const handlePointerMove = (e) => {
    if (dragRef.current.isDraggingNode && dragRef.current.draggedNode) {
      const { worldX, worldY } = screenToWorld(e.clientX, e.clientY)
      const node = dragRef.current.draggedNode
      node.x = worldX
      node.y = worldY
      node.vx = 0
      node.vy = 0
      simRunningRef.current = true
      return
    }

    if (dragRef.current.isPanning) {
      const dx = e.clientX - dragRef.current.startX
      const dy = e.clientY - dragRef.current.startY
      transformRef.current.x = dragRef.current.lastPanX + dx
      transformRef.current.y = dragRef.current.lastPanY + dy
      return
    }

    // Hover detection
    const hit = findNodeAt(e.clientX, e.clientY)
    setHoveredNode(hit)
  }

  const handlePointerUp = (e) => {
    if (dragRef.current.isDraggingNode && dragRef.current.draggedNode) {
      const node = dragRef.current.draggedNode
      node.fixed = false
      dragRef.current.isDraggingNode = false
      dragRef.current.draggedNode = null

      // Select node on click/drop
      setActiveNode(node)
      onSelectNode?.(node.id)
    }

    dragRef.current.isPanning = false
  }

  // Zoom via wheel
  const handleWheel = (e) => {
    e.preventDefault()
    const rect = canvasRef.current.getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    const mouseY = e.clientY - rect.top

    const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87
    const t = transformRef.current
    const newScale = Math.min(3.5, Math.max(0.25, t.scale * zoomFactor))

    // Zoom centered around mouse
    t.x = mouseX - (mouseX - t.x) * (newScale / t.scale)
    t.y = mouseY - (mouseY - t.y) * (newScale / t.scale)
    t.scale = newScale

    setTransformState({ scale: newScale })
  }

  // Control button actions
  const zoomIn = () => {
    const rect = canvasRef.current.getBoundingClientRect()
    const cx = rect.width / 2
    const cy = rect.height / 2
    const t = transformRef.current
    const newScale = Math.min(3.5, t.scale * 1.25)
    t.x = cx - (cx - t.x) * (newScale / t.scale)
    t.y = cy - (cy - t.y) * (newScale / t.scale)
    t.scale = newScale
    setTransformState({ scale: newScale })
  }

  const zoomOut = () => {
    const rect = canvasRef.current.getBoundingClientRect()
    const cx = rect.width / 2
    const cy = rect.height / 2
    const t = transformRef.current
    const newScale = Math.max(0.25, t.scale * 0.8)
    t.x = cx - (cx - t.x) * (newScale / t.scale)
    t.y = cy - (cy - t.y) * (newScale / t.scale)
    t.scale = newScale
    setTransformState({ scale: newScale })
  }

  const resetView = () => {
    const width = containerRef.current?.clientWidth || 800
    const height = containerRef.current?.clientHeight || 600
    transformRef.current = { x: 0, y: 0, scale: 1 }
    setTransformState({ scale: 1 })
    simRunningRef.current = true
    setIsSimRunning(true)
  }

  const togglePhysics = () => {
    simRunningRef.current = !simRunningRef.current
    setIsSimRunning(simRunningRef.current)
  }

  return (
    <div className="kw-graph-container" ref={containerRef}>
      <canvas
        ref={canvasRef}
        className="kw-graph-canvas"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onWheel={handleWheel}
      />

      {/* 悬浮图例 (Legend) */}
      {legendOpen && (
        <div className="kw-graph-legend">
          <header className="kw-legend-header">
            <span>图谱知识分类</span>
            <button
              type="button"
              className="kw-icon-btn"
              style={{ width: 18, height: 18 }}
              onClick={() => setLegendOpen(false)}
              aria-label="收起图例"
            >
              <Icon.Close style={{ width: 12, height: 12 }} />
            </button>
          </header>
          <div className="kw-legend-list">
            {KNOWLEDGE_CATEGORIES.filter(c => c.id !== 'all').map(c => (
              <div key={c.id} className="kw-legend-item">
                <span className="kw-cat-dot" style={{ background: c.color }} />
                <span>{c.label}</span>
              </div>
            ))}
            <div className="kw-legend-item" style={{ borderTop: '1px dashed var(--surface-border)', paddingTop: 4, marginTop: 4 }}>
              <span className="kw-cat-dot" style={{ background: '#eab308', boxShadow: '0 0 6px #eab308' }} />
              <span>科研优先理论 (金光环)</span>
            </div>
          </div>
        </div>
      )}

      {/* 悬浮操作控制器 */}
      <div className="kw-floating-controls">
        <button
          type="button"
          className="kw-control-btn"
          onClick={zoomIn}
          title="放大"
          aria-label="放大"
        >
          <Icon.ZoomIn style={{ width: 16, height: 16 }} />
        </button>
        <button
          type="button"
          className="kw-control-btn"
          onClick={zoomOut}
          title="缩小"
          aria-label="缩小"
        >
          <Icon.ZoomOut style={{ width: 16, height: 16 }} />
        </button>
        <button
          type="button"
          className="kw-control-btn"
          onClick={resetView}
          title="重置视角并居中"
          aria-label="重置视角"
        >
          <Icon.FitScreen style={{ width: 16, height: 16 }} />
        </button>
        <button
          type="button"
          className={`kw-control-btn ${isSimRunning ? 'active' : ''}`}
          onClick={togglePhysics}
          title={isSimRunning ? '暂停力导引物理布局' : '继续力导引物理布局'}
          aria-label="物理布局控制"
        >
          {isSimRunning ? (
            <Icon.Pause style={{ width: 14, height: 14 }} />
          ) : (
            <Icon.Play style={{ width: 14, height: 14 }} />
          )}
        </button>
        {!legendOpen && (
          <button
            type="button"
            className="kw-control-btn"
            onClick={() => setLegendOpen(true)}
            title="展开图例"
            aria-label="展开图例"
          >
            <Icon.Layers style={{ width: 14, height: 14 }} />
          </button>
        )}
      </div>

      {/* 选中节点详情抽屉 (Inspector Sheet) */}
      {activeNode && (
        <aside className="kw-graph-drawer" aria-label="知识节点详情">
          <header className="kw-drawer-header">
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <span
                  className="kw-badge"
                  style={{
                    background: `${getCategoryInfo(activeNode.category).color}25`,
                    color: getCategoryInfo(activeNode.category).color,
                    border: `1px solid ${getCategoryInfo(activeNode.category).color}40`,
                  }}
                >
                  {getCategoryInfo(activeNode.category).label}
                </span>
                {activeNode.preferred && (
                  <span
                    className="kw-badge"
                    style={{ background: 'rgba(234, 179, 8, 0.2)', color: '#eab308', border: '1px solid #eab308' }}
                  >
                    科研优选
                  </span>
                )}
              </div>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: 'var(--content-fg)' }}>
                {activeNode.label || activeNode.title || activeNode.name}
              </h3>
            </div>
            <button
              type="button"
              className="kw-icon-btn"
              onClick={() => setActiveNode(null)}
              aria-label="关闭详情"
            >
              <Icon.Close style={{ width: 16, height: 16 }} />
            </button>
          </header>

          <div className="kw-drawer-body">
            {/* Action Bar */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                type="button"
                className={`kw-filter-pref-btn ${activeNode.preferred ? 'active' : ''}`}
                style={{ flex: 1, justifyContent: 'center' }}
                onClick={() => {
                  const nextPref = !activeNode.preferred
                  setActiveNode(prev => ({ ...prev, preferred: nextPref }))
                  onTogglePreference?.(activeNode.id, nextPref)
                }}
              >
                {activeNode.preferred ? (
                  <Icon.StarFilled style={{ width: 14, height: 14 }} />
                ) : (
                  <Icon.Star style={{ width: 14, height: 14 }} />
                )}
                <span>{activeNode.preferred ? '已设为科研优选' : '设为科研优选'}</span>
              </button>

              <button
                type="button"
                className="kw-filter-pref-btn"
                onClick={() => onFork?.(activeNode)}
                title="以此为基础派生新理论"
              >
                <Icon.Fork style={{ width: 14, height: 14 }} />
                <span>派生</span>
              </button>

              {activeNode.is_user && (
                <button
                  type="button"
                  className="kw-filter-pref-btn"
                  onClick={() => onEdit?.(activeNode)}
                  title="编辑理论"
                >
                  <Icon.Edit style={{ width: 14, height: 14 }} />
                  <span>编辑</span>
                </button>
              )}
            </div>

            {/* LaTeX Formula */}
            {activeNode.formula && (
              <div className="kw-formula-box">
                <LatexMath math={activeNode.formula} displayMode />
              </div>
            )}

            {/* Description */}
            {activeNode.description && (
              <div>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--content-fg-secondary)', display: 'block', marginBottom: 4 }}>
                  核心理论机制阐述
                </span>
                <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6, color: 'var(--content-fg)' }}>
                  <LatexText text={activeNode.description} />
                </p>
              </div>
            )}

            {/* Properties */}
            {Array.isArray(activeNode.properties) && activeNode.properties.length > 0 && (
              <div>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--content-fg-secondary)', display: 'block', marginBottom: 6 }}>
                  关联物理量与天体性质
                </span>
                <div className="kw-tag-list">
                  {activeNode.properties.map((prop, i) => (
                    <span key={i} className="kw-tag">
                      <Icon.Tag style={{ width: 10, height: 10 }} />
                      <span>{prop}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Connected Relations */}
            <div>
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--content-fg-secondary)', display: 'block', marginBottom: 6 }}>
                图谱拓扑关联
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
                {simLinksRef.current
                  .filter(l => l.source?.id === activeNode.id || l.target?.id === activeNode.id)
                  .map((link, idx) => {
                    const other = link.source?.id === activeNode.id ? link.target : link.source
                    const isOut = link.source?.id === activeNode.id
                    return (
                      <div
                        key={idx}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          padding: '6px 10px',
                          borderRadius: 6,
                          background: 'var(--surface-secondary, rgba(255,255,255,0.03))',
                          border: '1px solid var(--surface-border)',
                          cursor: 'pointer',
                        }}
                        onClick={() => {
                          if (other) {
                            setActiveNode(other)
                            onSelectNode?.(other.id)
                          }
                        }}
                      >
                        <span style={{ color: 'var(--content-fg-secondary)' }}>
                          {isOut ? '指向' : '来自'}：{link.label || '关联'}
                        </span>
                        <span style={{ fontWeight: 500, color: 'var(--accent)' }}>
                          {other?.label || other?.title || other?.id}
                        </span>
                      </div>
                    )
                  })}
              </div>
            </div>
          </div>
        </aside>
      )}
    </div>
  )
}
