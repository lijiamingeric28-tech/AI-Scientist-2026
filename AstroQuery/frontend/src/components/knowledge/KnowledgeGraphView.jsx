import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react'
import { Icon } from '@/components/icons'
import { LatexMath, LatexText } from '@/components/results/LatexMath'
import { KNOWLEDGE_CATEGORIES, getCategoryInfo, isValidFormula } from './knowledgeConstants'

export default function KnowledgeGraphView({
  graphData,
  selectedCategory = 'all',
  selectedNodeId = null,
  onSelectNode,
  onTogglePreference,
  onEdit,
  onFork,
  onDelete,
  onRestore,
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
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)

  // Simulation nodes and links
  const simNodesRef = useRef([])
  const simLinksRef = useRef([])

  // Dynamic categories from graph data
  const dynamicCategories = useMemo(() => {
    return Array.isArray(graphData?.categories) ? graphData.categories : KNOWLEDGE_CATEGORIES
  }, [graphData?.categories])

  // Prepare nodes and links based on filters
  const { filteredNodes, filteredLinks } = useMemo(() => {
    if (!graphData || !Array.isArray(graphData.nodes)) {
      return { filteredNodes: [], filteredLinks: [] }
    }

    let nodes = graphData.nodes
    if (selectedCategory !== 'all') {
      const cat = dynamicCategories.find(c => c.id === selectedCategory)
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
  }, [graphData, selectedCategory, dynamicCategories])

  // Step physics simulation by 1 tick
  const stepPhysicsTick = useCallback((nodes, links, width, height, clusterAnchors) => {
    const centerX = width / 2
    const centerY = height / 2

    // 1. Repulsion between node pairs (Barnes-Hut approximation via distance cut)
    for (let i = 0; i < nodes.length; i++) {
      const n1 = nodes[i]
      for (let j = i + 1; j < nodes.length; j++) {
        const n2 = nodes[j]
        const dx = n2.x - n1.x
        const dy = n2.y - n1.y
        const distSq = dx * dx + dy * dy || 1
        if (distSq > 360000) continue // Distance cutoff for performance
        const dist = Math.sqrt(distSq)
        const repulsionK = n1.is_property || n2.is_property ? 900 : 2200
        const force = repulsionK / distSq
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
      if (!s || !t) continue
      const dx = t.x - s.x
      const dy = t.y - s.y
      const dist = Math.sqrt(dx * dx + dy * dy) || 1
      const idealDist = s.is_property || t.is_property ? 100 : 150
      const spring = (dist - idealDist) * 0.035
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

    // 3. Category Galactic Cluster Gravitation
    let totalVel = 0
    for (const n of nodes) {
      if (!n.fixed) {
        // Attract toward category anchor
        const anchor = clusterAnchors[n.category] || { x: centerX, y: centerY }
        const cfx = (anchor.x - n.x) * 0.007
        const cfy = (anchor.y - n.y) * 0.007
        n.vx += cfx
        n.vy += cfy

        // Global center gravity
        const gx = (centerX - n.x) * 0.003
        const gy = (centerY - n.y) * 0.003
        n.vx += gx
        n.vy += gy

        // Damping
        n.vx *= 0.82
        n.vy *= 0.82
        n.x += n.vx
        n.y += n.vy

        totalVel += Math.abs(n.vx) + Math.abs(n.vy)
      }
    }
    return totalVel
  }, [])

  // Initialize simulation with galactic cluster layout & offline pre-warming
  useEffect(() => {
    const existingMap = new Map(simNodesRef.current.map(n => [n.id, n]))
    const width = containerRef.current?.clientWidth || 900
    const height = containerRef.current?.clientHeight || 650
    const centerX = width / 2
    const centerY = height / 2

    // Compute radial galactic anchors for each category
    const validCats = dynamicCategories.filter(c => c.id !== 'all')
    const clusterAnchors = {}
    validCats.forEach((cat, idx) => {
      const angle = (idx / validCats.length) * 2 * Math.PI - Math.PI / 2
      const radius = Math.min(width, height) * 0.38
      clusterAnchors[cat.id] = {
        x: centerX + Math.cos(angle) * radius,
        y: centerY + Math.sin(angle) * radius,
      }
    })

    const newSimNodes = filteredNodes.map((n, i) => {
      const existing = existingMap.get(n.id)
      if (existing) {
        return {
          ...n,
          x: existing.x,
          y: existing.y,
          vx: existing.vx,
          vy: existing.vy,
          radius: n.is_property ? 14 : (n.preferred ? 20 : 16),
        }
      }
      // Place near category anchor with gentle scatter
      const anchor = clusterAnchors[n.category] || { x: centerX, y: centerY }
      const scatterAngle = Math.random() * Math.PI * 2
      const scatterDist = 20 + Math.random() * 90
      return {
        ...n,
        x: anchor.x + Math.cos(scatterAngle) * scatterDist,
        y: anchor.y + Math.sin(scatterAngle) * scatterDist,
        vx: 0,
        vy: 0,
        radius: n.is_property ? 14 : (n.preferred ? 20 : 16),
      }
    })

    const simNodeMap = new Map(newSimNodes.map(n => [n.id, n]))
    const links = filteredLinks
      .map(l => ({
        source: simNodeMap.get(l.source?.id || l.source),
        target: simNodeMap.get(l.target?.id || l.target),
        label: l.label || l.relation || '',
      }))
      .filter(l => l.source && l.target)

    // Calculate node degrees (connections) to determine hierarchy
    const degreeMap = new Map()
    for (const link of links) {
      degreeMap.set(link.source.id, (degreeMap.get(link.source.id) || 0) + 1)
      degreeMap.set(link.target.id, (degreeMap.get(link.target.id) || 0) + 1)
    }
    for (const n of newSimNodes) {
      n.degree = degreeMap.get(n.id) || 0
      if (!n.is_property) {
        n.radius = n.preferred ? 22 : (n.degree >= 3 ? 19 : 15)
      }
    }

    // Offline pre-warming: pre-compute 80 ticks in memory to achieve calm, stable layout
    for (let tick = 0; tick < 80; tick++) {
      stepPhysicsTick(newSimNodes, links, width, height, clusterAnchors)
    }

    simNodesRef.current = newSimNodes
    simLinksRef.current = links
    simRunningRef.current = true
    setIsSimRunning(true)
  }, [filteredNodes, filteredLinks, dynamicCategories, stepPhysicsTick])

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

    const width = canvas.width / (window.devicePixelRatio || 1)
    const height = canvas.height / (window.devicePixelRatio || 1)
    const validCats = dynamicCategories.filter(c => c.id !== 'all')
    const clusterAnchors = {}
    validCats.forEach((cat, idx) => {
      const angle = (idx / validCats.length) * 2 * Math.PI - Math.PI / 2
      const radius = Math.min(width, height) * 0.38
      clusterAnchors[cat.id] = {
        x: width / 2 + Math.cos(angle) * radius,
        y: height / 2 + Math.sin(angle) * radius,
      }
    })

    const render = () => {
      if (simRunningRef.current) {
        const vel = stepPhysicsTick(
          simNodesRef.current,
          simLinksRef.current,
          width,
          height,
          clusterAnchors
        )
        if (vel < 0.08) {
          simRunningRef.current = false
          setIsSimRunning(false)
        }
      }

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

      // Spotlight focus set
      const focusTarget = hoveredNode || activeNode
      const connectedNodeIds = new Set()
      if (focusTarget) {
        connectedNodeIds.add(focusTarget.id)
        for (const l of links) {
          if (l.source.id === focusTarget.id) connectedNodeIds.add(l.target.id)
          if (l.target.id === focusTarget.id) connectedNodeIds.add(l.source.id)
        }
      }

      // Draw celestial background grid dots
      ctx.fillStyle = 'rgba(128, 128, 128, 0.09)'
      const gridSize = 44
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
        const isConnected = focusTarget && (s.id === focusTarget.id || target.id === focusTarget.id)
        const isInSpotlight = !focusTarget || isConnected

        ctx.beginPath()
        ctx.moveTo(s.x, s.y)
        ctx.lineTo(target.x, target.y)

        if (isConnected) {
          ctx.strokeStyle = 'var(--accent, #14b8a6)'
          ctx.lineWidth = 2.4
          ctx.globalAlpha = 0.95
        } else {
          ctx.strokeStyle = 'rgba(148, 163, 184, 0.28)'
          ctx.lineWidth = 1.2
          ctx.globalAlpha = isInSpotlight ? 0.7 : 0.12
        }
        ctx.stroke()
        ctx.globalAlpha = 1.0

        // Edge label (only if connected or high zoom)
        if (link.label && (isConnected || t.scale > 1.25)) {
          const midX = (s.x + target.x) / 2
          const midY = (s.y + target.y) / 2
          ctx.font = '10.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
          ctx.fillStyle = isConnected ? 'var(--accent, #14b8a6)' : 'rgba(100, 116, 139, 0.85)'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(link.label, midX, midY - 6)
        }
      }

      // 2. Draw Nodes
      for (const n of nodes) {
        const isSelected = activeNode?.id === n.id
        const isHovered = hoveredNode?.id === n.id
        const isFocus = isSelected || isHovered
        const isPreferred = Boolean(n.preferred || n.user_preference === 'preferred')
        const catInfo = getCategoryInfo(n.category, dynamicCategories)
        const inSpotlight = !focusTarget || connectedNodeIds.has(n.id)

        ctx.globalAlpha = inSpotlight ? 1.0 : 0.16

        // Preferred Gold Glow Ring
        if (isPreferred && !n.is_property) {
          ctx.beginPath()
          ctx.arc(n.x, n.y, n.radius + 6, 0, Math.PI * 2)
          ctx.strokeStyle = 'rgba(234, 179, 8, 0.55)'
          ctx.lineWidth = 2
          ctx.setLineDash([4, 2])
          ctx.stroke()
          ctx.setLineDash([])
        }

        // Selection / Spotlight Focus Ring
        if (isFocus) {
          ctx.beginPath()
          ctx.arc(n.x, n.y, n.radius + (isPreferred ? 9 : 6), 0, Math.PI * 2)
          ctx.strokeStyle = 'var(--accent, #14b8a6)'
          ctx.lineWidth = 2.8
          ctx.stroke()
        }

        // Node Circle Body with refined translucent fill
        ctx.beginPath()
        ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2)
        ctx.fillStyle = n.is_property
          ? 'rgba(148, 163, 184, 0.18)'
          : `${catInfo.color}44`
        ctx.fill()

        ctx.strokeStyle = n.is_property
          ? 'rgba(148, 163, 184, 0.7)'
          : catInfo.color
        ctx.lineWidth = isFocus ? 2.8 : 1.8
        ctx.stroke()

        // Inner marker: Golden Star for preferred, dot for standard
        if (isPreferred && !n.is_property) {
          ctx.beginPath()
          ctx.arc(n.x, n.y, 4, 0, Math.PI * 2)
          ctx.fillStyle = '#eab308'
          ctx.fill()
        }

        // Smart LOD Labels with Capsule Backdrop (Prevent Text Overlap)
        const showLabel =
          isFocus ||
          isPreferred ||
          n.degree >= 3 ||
          t.scale >= 1.15 ||
          nodes.length < 35

        if (showLabel) {
          const labelText = n.label || n.title || n.name || n.id
          const displayLabel = labelText.length > 15 ? labelText.slice(0, 14) + '…' : labelText
          const fontSize = n.is_property ? 11 : (isFocus ? 12.5 : 11.5)
          ctx.font = `${isFocus ? '600 ' : '500 '}${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`

          // Measure text to draw protective background capsule
          const textMetrics = ctx.measureText(displayLabel)
          const padX = 6
          const padY = 2.5
          const textW = textMetrics.width + padX * 2
          const textH = fontSize + padY * 2
          const rectX = n.x - textW / 2
          const rectY = n.y + n.radius + 5

          // Capsule background
          ctx.beginPath()
          if (ctx.roundRect) {
            ctx.roundRect(rectX, rectY, textW, textH, 4)
          } else {
            ctx.rect(rectX, rectY, textW, textH)
          }
          ctx.fillStyle = isFocus
            ? 'var(--surface-bg, rgba(255, 255, 255, 0.96))'
            : 'var(--surface-bg, rgba(255, 255, 255, 0.88))'
          ctx.fill()
          ctx.strokeStyle = isFocus ? 'var(--accent, #14b8a6)' : 'var(--surface-border, rgba(0,0,0,0.08))'
          ctx.lineWidth = 1
          ctx.stroke()

          // Text content
          ctx.fillStyle = isFocus ? 'var(--accent, #14b8a6)' : 'var(--content-fg, #1e293b)'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(displayLabel, n.x, rectY + textH / 2)
        }

        ctx.globalAlpha = 1.0
      }

      ctx.restore()
      animId = requestAnimationFrame(render)
    }

    animId = requestAnimationFrame(render)
    return () => cancelAnimationFrame(animId)
  }, [activeNode, hoveredNode, dynamicCategories, stepPhysicsTick])

  // Mouse event handlers: Pan, Zoom & Node Dragging
  const handleWheel = useCallback((e) => {
    e.preventDefault()
    const rect = canvasRef.current.getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    const mouseY = e.clientY - rect.top

    const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89
    const currentScale = transformRef.current.scale
    const newScale = Math.min(Math.max(currentScale * zoomFactor, 0.35), 3.2)

    const newX = mouseX - (mouseX - transformRef.current.x) * (newScale / currentScale)
    const newY = mouseY - (mouseY - transformRef.current.y) * (newScale / currentScale)

    transformRef.current = { x: newX, y: newY, scale: newScale }
    setTransformState({ scale: newScale })
  }, [])

  const getNodeAtPosition = useCallback((x, y) => {
    const t = transformRef.current
    const worldX = (x - t.x) / t.scale
    const worldY = (y - t.y) / t.scale

    for (let i = simNodesRef.current.length - 1; i >= 0; i--) {
      const n = simNodesRef.current[i]
      const dx = worldX - n.x
      const dy = worldY - n.y
      if (dx * dx + dy * dy <= (n.radius + 4) * (n.radius + 4)) {
        return n
      }
    }
    return null
  }, [])

  const handleMouseDown = useCallback((e) => {
    if (e.button !== 0) return
    const rect = canvasRef.current.getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    const mouseY = e.clientY - rect.top

    const hitNode = getNodeAtPosition(mouseX, mouseY)
    if (hitNode) {
      dragRef.current.isDraggingNode = true
      dragRef.current.draggedNode = hitNode
      hitNode.fixed = true
      simRunningRef.current = true
      setIsSimRunning(true)
    } else {
      dragRef.current.isPanning = true
      dragRef.current.startX = e.clientX
      dragRef.current.startY = e.clientY
      dragRef.current.lastPanX = transformRef.current.x
      dragRef.current.lastPanY = transformRef.current.y
    }
  }, [getNodeAtPosition])

  const handleMouseMove = useCallback((e) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return
    const mouseX = e.clientX - rect.left
    const mouseY = e.clientY - rect.top

    if (dragRef.current.isDraggingNode && dragRef.current.draggedNode) {
      const t = transformRef.current
      const worldX = (mouseX - t.x) / t.scale
      const worldY = (mouseY - t.y) / t.scale
      dragRef.current.draggedNode.x = worldX
      dragRef.current.draggedNode.y = worldY
      dragRef.current.draggedNode.vx = 0
      dragRef.current.draggedNode.vy = 0
      simRunningRef.current = true
      setIsSimRunning(true)
      return
    }

    if (dragRef.current.isPanning) {
      const dx = e.clientX - dragRef.current.startX
      const dy = e.clientY - dragRef.current.startY
      transformRef.current.x = dragRef.current.lastPanX + dx
      transformRef.current.y = dragRef.current.lastPanY + dy
      return
    }

    const hit = getNodeAtPosition(mouseX, mouseY)
    if (hit !== hoveredNode) {
      setHoveredNode(hit)
    }
  }, [getNodeAtPosition, hoveredNode])

  const handleMouseUp = useCallback((e) => {
    if (dragRef.current.isDraggingNode && dragRef.current.draggedNode) {
      dragRef.current.draggedNode.fixed = false
      dragRef.current.isDraggingNode = false
      dragRef.current.draggedNode = null
      return
    }

    if (dragRef.current.isPanning) {
      const dist = Math.hypot(
        e.clientX - dragRef.current.startX,
        e.clientY - dragRef.current.startY
      )
      dragRef.current.isPanning = false
      if (dist < 4) {
        const rect = canvasRef.current.getBoundingClientRect()
        const hit = getNodeAtPosition(e.clientX - rect.left, e.clientY - rect.top)
        setActiveNode(hit)
        onSelectNode?.(hit?.id || null)
      }
    }
  }, [getNodeAtPosition, onSelectNode])

  // Camera reset
  const handleResetView = useCallback(() => {
    transformRef.current = { x: 0, y: 0, scale: 1 }
    setTransformState({ scale: 1 })
    simRunningRef.current = true
    setIsSimRunning(true)
  }, [])

  const handleZoom = useCallback((delta) => {
    const currentScale = transformRef.current.scale
    const newScale = Math.min(Math.max(currentScale + delta, 0.35), 3.2)
    const rect = canvasRef.current.getBoundingClientRect()
    const centerX = rect.width / 2
    const centerY = rect.height / 2
    const newX = centerX - (centerX - transformRef.current.x) * (newScale / currentScale)
    const newY = centerY - (centerY - transformRef.current.y) * (newScale / currentScale)

    transformRef.current = { x: newX, y: newY, scale: newScale }
    setTransformState({ scale: newScale })
  }, [])

  return (
    <div
      ref={containerRef}
      className="kw-graph-container"
      style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}
    >
      <canvas
        ref={canvasRef}
        className="kw-graph-canvas"
        style={{ width: '100%', height: '100%', display: 'block', cursor: hoveredNode ? 'pointer' : 'grab' }}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
      />

      {/* Floating Controls (Astra Light Glass Theme) */}
      <div className="kw-floating-controls">
        <button
          type="button"
          className="kw-control-btn"
          onClick={() => handleZoom(0.2)}
          title="放大视口"
          aria-label="放大"
        >
          <Icon.Plus style={{ width: 15, height: 15 }} />
        </button>
        <button
          type="button"
          className="kw-control-btn"
          onClick={() => handleZoom(-0.2)}
          title="缩小视口"
          aria-label="缩小"
        >
          <Icon.Minus style={{ width: 15, height: 15 }} />
        </button>
        <button
          type="button"
          className="kw-control-btn"
          onClick={handleResetView}
          title="重置视角与坐标原点"
          aria-label="重置视角"
        >
          <Icon.Focus style={{ width: 15, height: 15 }} />
        </button>
        <button
          type="button"
          className={`kw-control-btn ${isSimRunning ? 'active' : ''}`}
          onClick={() => {
            simRunningRef.current = !simRunningRef.current
            setIsSimRunning(simRunningRef.current)
          }}
          title={isSimRunning ? '冻结物理引力布局' : '恢复物理引力布局'}
          aria-label="引力控制"
        >
          {isSimRunning ? (
            <Icon.Stop style={{ width: 14, height: 14 }} />
          ) : (
            <Icon.Play style={{ width: 14, height: 14 }} />
          )}
        </button>
      </div>

      {/* Graph Legend (Astra Glass Theme) */}
      {legendOpen && (
        <div className="kw-graph-legend">
          <header className="kw-legend-header">
            <span>星系分类图例</span>
            <button
              type="button"
              className="kw-icon-btn"
              onClick={() => setLegendOpen(false)}
              aria-label="折叠图例"
            >
              <Icon.Close style={{ width: 12, height: 12 }} />
            </button>
          </header>
          <div className="kw-legend-list">
            {dynamicCategories
              .filter(c => c.id !== 'all')
              .map(c => {
                const info = getCategoryInfo(c.id, dynamicCategories)
                return (
                  <div key={c.id} className="kw-legend-item">
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        background: info.color,
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {info.label || c.label}
                    </span>
                  </div>
                )
              })}
            <div
              className="kw-legend-item"
              style={{ borderTop: '1px dashed var(--surface-border)', paddingTop: 4, marginTop: 4 }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: '#eab308',
                  boxShadow: '0 0 6px #eab308',
                  flexShrink: 0,
                }}
              />
              <span>科研优先理论 (金光环)</span>
            </div>
            <div className="kw-legend-item">
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: 'rgba(148, 163, 184, 0.6)',
                  flexShrink: 0,
                }}
              />
              <span>关联性质连线枢纽</span>
            </div>
          </div>
        </div>
      )}

      {/* Legend Reopen Pill Button */}
      {!legendOpen && (
        <button
          type="button"
          onClick={() => setLegendOpen(true)}
          style={{
            position: 'absolute',
            top: 16,
            left: 20,
            background: 'var(--surface-bg)',
            border: '1px solid var(--surface-border)',
            borderRadius: 20,
            padding: '5px 12px',
            fontSize: 12,
            color: 'var(--content-fg)',
            boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            zIndex: 15,
            backdropFilter: 'blur(8px)',
          }}
        >
          <Icon.Tag style={{ width: 12, height: 12, color: 'var(--accent)' }} />
          <span>查看图例</span>
        </button>
      )}

      {/* Unified Context Drawer & Fullscreen Backdrop */}
      {activeNode && (
        <>
          <div
            className="kw-drawer-backdrop"
            onClick={() => setActiveNode(null)}
            aria-label="关闭侧边栏"
          />
          <aside
            className="kw-graph-drawer"
            role="dialog"
            aria-label={activeNode.label || activeNode.title || '理论详情'}
          >
            <header className="kw-drawer-header">
              <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <span
                    className="kw-badge"
                    style={{
                      background: `${getCategoryInfo(activeNode.category, dynamicCategories).color}22`,
                      color: getCategoryInfo(activeNode.category, dynamicCategories).color,
                      border: `1px solid ${getCategoryInfo(activeNode.category, dynamicCategories).color}44`,
                    }}
                  >
                    {getCategoryInfo(activeNode.category, dynamicCategories).label}
                  </span>
                  {activeNode.preferred && (
                    <span
                      className="kw-badge"
                      style={{ background: 'rgba(234, 179, 8, 0.15)', color: '#d97706', border: '1px solid rgba(234, 179, 8, 0.35)' }}
                    >
                      科研优选
                    </span>
                  )}
                  {activeNode.is_override && (
                    <span
                      className="kw-badge"
                      style={{ background: 'rgba(59, 130, 246, 0.15)', color: '#2563eb', border: '1px solid rgba(59, 130, 246, 0.35)' }}
                    >
                      用户自定义已修改
                    </span>
                  )}
                </div>
                <h3 style={{ margin: 0, fontSize: 16, fontWeight: 650, color: 'var(--content-fg)', lineHeight: 1.4 }}>
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
              {/* Universal Action Buttons: Preferred, Edit (ALL items), Fork, Delete, Restore */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className={`kw-filter-pref-btn ${activeNode.preferred ? 'active' : ''}`}
                  style={{ flex: 1, minWidth: 140, justifyContent: 'center' }}
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

                {/* Direct Edit Button for ALL entries */}
                <button
                  type="button"
                  className="kw-filter-pref-btn"
                  onClick={() => onEdit?.(activeNode)}
                  title="直接修改该理论内容与分类"
                >
                  <Icon.Edit style={{ width: 14, height: 14 }} />
                  <span>编辑理论</span>
                </button>

                <button
                  type="button"
                  className="kw-filter-pref-btn"
                  onClick={() => onFork?.(activeNode)}
                  title="以此理论为模板派生新知识"
                >
                  <Icon.Fork style={{ width: 14, height: 14 }} />
                  <span>派生</span>
                </button>

                {/* Delete Entry Button */}
                <button
                  type="button"
                  className="kw-filter-pref-btn"
                  style={{ color: 'var(--status-error, #ef4444)' }}
                  onClick={() => setDeleteConfirmOpen(true)}
                  title="从个人理论知识库中删除此条目"
                >
                  <Icon.Trash style={{ width: 14, height: 14 }} />
                  <span>删除</span>
                </button>

                {/* Restore Default Button for Overridden Base Entries */}
                {(activeNode.is_override || activeNode.is_user === false) && (
                  <button
                    type="button"
                    className="kw-filter-pref-btn"
                    onClick={() => {
                      onRestore?.(activeNode.id)
                      setActiveNode(null)
                    }}
                    title="清除全部修改，重置为系统出厂预置状态"
                  >
                    <Icon.History style={{ width: 14, height: 14 }} />
                    <span>恢复默认</span>
                  </button>
                )}
              </div>

              {/* Delete Confirmation Modal */}
              {deleteConfirmOpen && (
                <div
                  style={{
                    padding: 12,
                    background: 'rgba(239, 68, 68, 0.08)',
                    border: '1px solid rgba(239, 68, 68, 0.3)',
                    borderRadius: 8,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                  }}
                >
                  <div style={{ fontSize: 13, color: 'var(--content-fg)', fontWeight: 500 }}>
                    确定要从知识库中删除「{activeNode.label || activeNode.title}」吗？
                  </div>
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                    <button
                      type="button"
                      className="kw-mode-btn"
                      style={{ padding: '4px 10px', fontSize: 12 }}
                      onClick={() => setDeleteConfirmOpen(false)}
                    >
                      取消
                    </button>
                    <button
                      type="button"
                      style={{
                        padding: '4px 12px',
                        fontSize: 12,
                        background: 'var(--status-error, #ef4444)',
                        color: '#fff',
                        border: 'none',
                        borderRadius: 6,
                        cursor: 'pointer',
                      }}
                      onClick={() => {
                        setDeleteConfirmOpen(false)
                        onDelete?.(activeNode.id)
                        setActiveNode(null)
                      }}
                    >
                      确认删除
                    </button>
                  </div>
                </div>
              )}

              {/* LaTeX Formula with Validity Check to prevent truncation / squashing */}
              {activeNode.formula && isValidFormula(activeNode.formula) && (
                <div className="kw-formula-box">
                  <LatexMath math={activeNode.formula} displayMode />
                </div>
              )}

              {/* Core Theoretical Description */}
              {(activeNode.description || (activeNode.formula && !isValidFormula(activeNode.formula))) && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--content-fg-secondary)' }}>
                    核心理论机制阐述
                  </span>
                  <div style={{ margin: 0, fontSize: 13, lineHeight: 1.68, color: 'var(--content-fg)' }}>
                    <LatexText
                      text={
                        activeNode.description ||
                        activeNode.formula
                      }
                    />
                  </div>
                </div>
              )}

              {/* Scientific Conditions / Assumptions */}
              {Array.isArray(activeNode.conditions) && activeNode.conditions.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--content-fg-secondary)' }}>
                    适用物理条件与边界假定
                  </span>
                  <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.6, color: 'var(--content-fg)' }}>
                    {activeNode.conditions.map((cond, ci) => (
                      <li key={ci}>{cond}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Associated Properties & Celestial Parameters */}
              {Array.isArray(activeNode.properties) && activeNode.properties.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--content-fg-secondary)' }}>
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

              {/* Topology Links */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--content-fg-secondary)' }}>
                  图谱拓扑关联
                </span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
                  {simLinksRef.current
                    .filter(l => l.source?.id === activeNode.id || l.target?.id === activeNode.id)
                    .map((link, idx) => {
                      const other = link.source?.id === activeNode.id ? link.target : link.source
                      return (
                        <div
                          key={idx}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            padding: '6px 10px',
                            borderRadius: 6,
                            background: 'var(--surface-secondary, rgba(0,0,0,0.02))',
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
                          <span style={{ fontWeight: 500, color: 'var(--content-fg)' }}>
                            {other.label || other.id}
                          </span>
                          <span style={{ fontSize: 11, color: 'var(--accent)' }}>
                            {link.label || '相互约束'} →
                          </span>
                        </div>
                      )
                    })}
                </div>
              </div>
            </div>
          </aside>
        </>
      )}
    </div>
  )
}
