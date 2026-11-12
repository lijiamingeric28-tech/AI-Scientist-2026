import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react'
import { Icon } from '@/components/icons'
import { KNOWLEDGE_CATEGORIES, getCategoryInfo } from './knowledgeConstants'

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5))

function toAlphaColor(colorStr, alpha = 0.25) {
  if (!colorStr) return `rgba(20, 184, 166, ${alpha})`
  const str = String(colorStr).trim()
  if (str.startsWith('#')) {
    let hex = str.slice(1)
    if (hex.length === 3) hex = hex.split('').map(c => c + c).join('')
    if (hex.length >= 6) {
      const r = parseInt(hex.slice(0, 2), 16)
      const g = parseInt(hex.slice(2, 4), 16)
      const b = parseInt(hex.slice(4, 6), 16)
      return `rgba(${r}, ${g}, ${b}, ${alpha})`
    }
  }
  if (str.startsWith('hsl')) {
    if (str.startsWith('hsla')) {
      return str.replace(/,\s*[\d.]+\)$/, `, ${alpha})`)
    }
    return str.replace(/^hsl\((.+)\)$/, `hsla($1, ${alpha})`)
  }
  if (str.startsWith('rgb')) {
    if (str.startsWith('rgba')) {
      return str.replace(/,\s*[\d.]+\)$/, `, ${alpha})`)
    }
    return str.replace(/^rgb\((.+)\)$/, `rgba($1, ${alpha})`)
  }
  return str
}

function easeOutCubic(t) {
  const clamped = Math.max(0, Math.min(1, t))
  return 1 - Math.pow(1 - clamped, 3)
}

function boxesOverlap(a, b, pad = 6) {
  return !(
    a.x + a.w + pad < b.x ||
    b.x + b.w + pad < a.x ||
    a.y + a.h + pad < b.y ||
    b.y + b.h + pad < a.y
  )
}

function computeFitTransform(nodes, viewportWidth, viewportHeight, legendOpen) {
  const w = Math.max(viewportWidth || 900, 320)
  const h = Math.max(viewportHeight || 620, 260)
  if (!nodes || nodes.length === 0) {
    return { x: 0, y: 0, scale: 1 }
  }

  let minX = Infinity
  let maxX = -Infinity
  let minY = Infinity
  let maxY = -Infinity
  for (const n of nodes) {
    if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) continue
    const pad = (n.radius || 16) + 28
    if (n.x - pad < minX) minX = n.x - pad
    if (n.x + pad > maxX) maxX = n.x + pad
    if (n.y - pad < minY) minY = n.y - pad
    if (n.y + pad > maxY) maxY = n.y + pad
  }
  if (!Number.isFinite(minX)) return { x: 0, y: 0, scale: 1 }

  const leftPad = legendOpen ? Math.min(220, w * 0.24) : 44
  const rightPad = 68
  const topPad = 62
  const bottomPad = 48
  const availW = Math.max(200, w - leftPad - rightPad)
  const availH = Math.max(180, h - topPad - bottomPad)

  const boxW = Math.max(120, maxX - minX)
  const boxH = Math.max(120, maxY - minY)
  const scale = Math.min(1.18, Math.max(0.32, Math.min(availW / boxW, availH / boxH)))

  const worldCenterX = (minX + maxX) / 2
  const worldCenterY = (minY + maxY) / 2
  const screenCenterX = leftPad + availW / 2
  const screenCenterY = topPad + availH / 2

  return {
    x: screenCenterX - worldCenterX * scale,
    y: screenCenterY - worldCenterY * scale,
    scale,
  }
}

export default function KnowledgeGraphView({
  graphData,
  loading = false,
  graphReady = true,
  selectedCategory = 'all',
  selectedNodeId = null,
  onSelectNode,
}) {
  const canvasRef = useRef(null)
  const containerRef = useRef(null)

  const transformRef = useRef({ x: 0, y: 0, scale: 1 })
  const fitTransformRef = useRef({ x: 0, y: 0, scale: 1 })
  const [, setTransformState] = useState({ scale: 1 })

  const simRunningRef = useRef(false)
  const [isSimRunning, setIsSimRunning] = useState(false)
  const [legendOpen, setLegendOpen] = useState(true)

  const dragRef = useRef({
    isDraggingNode: false,
    draggedNode: null,
    isPanning: false,
    startX: 0,
    startY: 0,
    lastPanX: 0,
    lastPanY: 0,
  })

  const [activeNode, setActiveNode] = useState(null)
  const [hoveredNode, setHoveredNode] = useState(null)
  const activeNodeRef = useRef(null)
  const hoveredNodeRef = useRef(null)
  const legendOpenRef = useRef(legendOpen)
  legendOpenRef.current = legendOpen

  const simNodesRef = useRef([])
  const simLinksRef = useRef([])
  const clusterMetaRef = useRef([])
  const revealStartRef = useRef(0)

  const dynamicCategories = useMemo(() => {
    return Array.isArray(graphData?.categories) ? graphData.categories : KNOWLEDGE_CATEGORIES
  }, [graphData?.categories])
  const dynamicCategoriesRef = useRef(dynamicCategories)
  dynamicCategoriesRef.current = dynamicCategories

  const { filteredNodes, filteredLinks } = useMemo(() => {
    if (!graphData || !Array.isArray(graphData.nodes)) {
      return { filteredNodes: [], filteredLinks: [] }
    }

    let nodes = graphData.nodes
    if (selectedCategory !== 'all') {
      const cat = dynamicCategories.find(c => c.id === selectedCategory)
      nodes = nodes.filter(n => {
        if (n.is_property) return true
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

  // Physics step with hard non-overlap separation + ring/sector tethering
  const stepPhysicsTick = useCallback((nodes, links, centerX, centerY, isLiveDrag = false) => {
    for (let i = 0; i < nodes.length; i++) {
      const n1 = nodes[i]
      for (let j = i + 1; j < nodes.length; j++) {
        const n2 = nodes[j]
        const dx = n2.x - n1.x
        const dy = n2.y - n1.y
        const distSq = dx * dx + dy * dy
        if (distSq > 260000) continue

        const minSep = n1.radius + n2.radius + (n1.is_property || n2.is_property ? 22 : 30)
        if (distSq < 0.09) {
          const angle = ((i * 7 + j * 13) % 360) * (Math.PI / 180)
          n2.x += Math.cos(angle) * minSep * 0.5
          n2.y += Math.sin(angle) * minSep * 0.5
          continue
        }

        const dist = Math.sqrt(distSq)
        // Soft repulsion
        const repulsionK = n1.is_property || n2.is_property ? 1400 : 2800
        let force = repulsionK / distSq

        // Strong anti-overlap separation when circles come too close
        if (dist < minSep) {
          const push = ((minSep - dist) / minSep) * (isLiveDrag ? 0.25 : 0.48)
          const px = (dx / dist) * (minSep - dist) * push
          const py = (dy / dist) * (minSep - dist) * push
          if (!n1.fixed) {
            n1.x -= px
            n1.y -= py
          }
          if (!n2.fixed) {
            n2.x += px
            n2.y += py
          }
          force += (minSep - dist) * 0.08
        }

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

    // Spring attraction along topology edges
    for (const link of links) {
      const s = link.source
      const t = link.target
      if (!s || !t) continue
      const dx = t.x - s.x
      const dy = t.y - s.y
      const dist = Math.sqrt(dx * dx + dy * dy) || 1
      const idealDist = s.is_property || t.is_property ? 185 : 215
      const spring = (dist - idealDist) * 0.022
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

    // Anchor tethering + velocity damping
    let totalVel = 0
    for (const n of nodes) {
      if (!n.fixed) {
        const anchorX = Number.isFinite(n.anchorX) ? n.anchorX : centerX
        const anchorY = Number.isFinite(n.anchorY) ? n.anchorY : centerY
        const pull = n.is_property ? 0.024 : 0.015
        n.vx += (anchorX - n.x) * pull
        n.vy += (anchorY - n.y) * pull

        n.vx *= 0.78
        n.vy *= 0.78
        n.x += n.vx
        n.y += n.vy
        totalVel += Math.abs(n.vx) + Math.abs(n.vy)
      }
    }
    return totalVel
  }, [])

  // Deterministic dual-ring constellation layout + full pre-convergence + auto-fit
  useEffect(() => {
    if (!graphReady || filteredNodes.length === 0) {
      simNodesRef.current = []
      simLinksRef.current = []
      clusterMetaRef.current = []
      return
    }

    const width = containerRef.current?.clientWidth || 960
    const height = containerRef.current?.clientHeight || 640
    const centerX = width / 2
    const centerY = height / 2

    // Build adjacency & degree counts deterministically
    const degreeMap = new Map()
    const neighbors = new Map()
    for (const edge of filteredLinks) {
      const sid = edge.source?.id || edge.source
      const tid = edge.target?.id || edge.target
      degreeMap.set(sid, (degreeMap.get(sid) || 0) + 1)
      degreeMap.set(tid, (degreeMap.get(tid) || 0) + 1)
      if (!neighbors.has(sid)) neighbors.set(sid, new Set())
      if (!neighbors.has(tid)) neighbors.set(tid, new Set())
      neighbors.get(sid).add(tid)
      neighbors.get(tid).add(sid)
    }

    const rawNodeById = new Map(filteredNodes.map(n => [n.id, n]))
    const propertyRaw = []
    const theoryByCat = new Map()

    for (const n of filteredNodes) {
      if (n.is_property) {
        propertyRaw.push(n)
      } else {
        const catId = n.category || 'physical_laws'
        if (!theoryByCat.has(catId)) theoryByCat.set(catId, [])
        theoryByCat.get(catId).push(n)
      }
    }

    // Order active categories cleanly according to dynamicCategories order
    const catEntries = []
    for (const cat of dynamicCategories) {
      if (cat.id === 'all') continue
      const list = theoryByCat.get(cat.id)
      if (list && list.length > 0) {
        catEntries.push({ cat, nodes: list })
        theoryByCat.delete(cat.id)
      }
    }
    for (const [catId, list] of theoryByCat.entries()) {
      catEntries.push({ cat: getCategoryInfo(catId, dynamicCategories), nodes: list })
    }

    // Allocate proportional angular sectors for active categories
    const totalWeight = catEntries.reduce((acc, item) => acc + Math.max(1.2, Math.sqrt(item.nodes.length)), 0) || 1
    const baseRadius = Math.max(360, Math.sqrt(filteredNodes.length) * 58)
    const propRingRadius = propertyRaw.length > 0
      ? Math.max(120, Math.min(baseRadius * 0.42, 95 + propertyRaw.length * 10))
      : 0

    let cursorAngle = -Math.PI / 2
    const categoryAngleMap = new Map()
    const clusterMetas = []
    const placedNodes = []

    for (const { cat, nodes: catList } of catEntries) {
      const weight = Math.max(1.2, Math.sqrt(catList.length))
      const sweep = (weight / totalWeight) * Math.PI * 2
      const midAngle = cursorAngle + sweep / 2
      cursorAngle += sweep
      categoryAngleMap.set(cat.id, midAngle)

      // Single-category view fans gently around center instead of clustering on one rim
      const clusterRadius = catEntries.length === 1 ? 0 : baseRadius * 0.92
      const anchorX = centerX + Math.cos(midAngle) * clusterRadius
      const anchorY = centerY + Math.sin(midAngle) * clusterRadius

      // Sort nodes: preferred + higher degree closer to core, rest spiral outward
      const sorted = [...catList].sort((a, b) => {
        const ap = a.preferred || a.user_preference === 'preferred' ? 0 : 1
        const bp = b.preferred || b.user_preference === 'preferred' ? 0 : 1
        if (ap !== bp) return ap - bp
        const ad = degreeMap.get(a.id) || 0
        const bd = degreeMap.get(b.id) || 0
        if (ad !== bd) return bd - ad
        return String(a.id).localeCompare(String(b.id))
      })

      const spreadFactor = catEntries.length === 1 ? 46 : 38
      sorted.forEach((n, idx) => {
        const deg = degreeMap.get(n.id) || 0
        const isPref = Boolean(n.preferred || n.user_preference === 'preferred')
        const radius = isPref ? 21 : (deg >= 3 ? 18 : 15)
        const r = Math.sqrt(idx + 0.6) * spreadFactor
        const theta = idx * GOLDEN_ANGLE + midAngle
        placedNodes.push({
          ...n,
          x: anchorX + Math.cos(theta) * r,
          y: anchorY + Math.sin(theta) * r,
          vx: 0,
          vy: 0,
          anchorX,
          anchorY,
          degree: deg,
          radius,
          ringOrder: 1 + r / Math.max(baseRadius, 200),
        })
      })

      clusterMetas.push({
        id: cat.id,
        label: cat.label,
        color: cat.color,
        x: anchorX,
        y: anchorY,
        count: catList.length,
        midAngle,
      })
    }

    // Order property hub nodes by their dominant connected category angle to minimize crossings
    const propWithAngle = propertyRaw.map((p, idx) => {
      const nbIds = neighbors.get(p.id) || new Set()
      let sinSum = 0
      let cosSum = 0
      let hits = 0
      for (const nid of nbIds) {
        const nb = rawNodeById.get(nid)
        if (nb && !nb.is_property) {
          const ang = categoryAngleMap.get(nb.category || 'physical_laws')
          if (Number.isFinite(ang)) {
            sinSum += Math.sin(ang)
            cosSum += Math.cos(ang)
            hits++
          }
        }
      }
      const targetAngle = hits > 0 ? Math.atan2(sinSum, cosSum) : (idx / Math.max(1, propertyRaw.length)) * Math.PI * 2
      return { node: p, targetAngle }
    })
    propWithAngle.sort((a, b) => a.targetAngle - b.targetAngle)

    propWithAngle.forEach(({ node: p }, idx) => {
      const deg = degreeMap.get(p.id) || 0
      const angle = (idx / Math.max(1, propWithAngle.length)) * Math.PI * 2 - Math.PI / 2
      const ringFactor = propWithAngle.length > 16 && idx % 2 === 1 ? 0.66 : 1.0
      const r = propRingRadius * ringFactor
      const ax = centerX + Math.cos(angle) * r
      const ay = centerY + Math.sin(angle) * r
      placedNodes.push({
        ...p,
        x: ax,
        y: ay,
        vx: 0,
        vy: 0,
        anchorX: ax,
        anchorY: ay,
        degree: deg,
        radius: deg >= 4 ? 15 : 13,
        ringOrder: 0.2,
      })
    })

    const simNodeMap = new Map(placedNodes.map(n => [n.id, n]))
    const links = filteredLinks
      .map(l => ({
        source: simNodeMap.get(l.source?.id || l.source),
        target: simNodeMap.get(l.target?.id || l.target),
        label: l.label || l.relation || '',
      }))
      .filter(l => l.source && l.target)

    // Pre-converge completely in memory BEFORE rendering frame 1 (calm, zero jitter)
    const ticks = placedNodes.length > 220 ? 120 : 180
    for (let tick = 0; tick < ticks; tick++) {
      stepPhysicsTick(placedNodes, links, centerX, centerY, false)
    }

    // Recompute exact cluster centroids from settled positions
    for (const meta of clusterMetas) {
      const members = placedNodes.filter(n => !n.is_property && (n.category || 'physical_laws') === meta.id)
      if (members.length > 0) {
        meta.x = members.reduce((s, m) => s + m.x, 0) / members.length
        meta.y = members.reduce((s, m) => s + m.y, 0) / members.length
        let maxR = 90
        for (const m of members) {
          const d = Math.hypot(m.x - meta.x, m.y - meta.y) + m.radius + 32
          if (d > maxR) maxR = d
        }
        meta.haloRadius = maxR
      }
    }

    simNodesRef.current = placedNodes
    simLinksRef.current = links
    clusterMetaRef.current = clusterMetas
    simRunningRef.current = false
    setIsSimRunning(false)

    // Auto-fit entire constellation neatly inside viewport & trigger calm radial reveal
    const fit = computeFitTransform(placedNodes, width, height, legendOpenRef.current)
    fitTransformRef.current = fit
    transformRef.current = { ...fit }
    setTransformState({ scale: fit.scale })
    revealStartRef.current = performance.now()
  }, [filteredNodes, filteredLinks, dynamicCategories, graphReady, stepPhysicsTick])

  // Sync selected node with prop
  useEffect(() => {
    if (selectedNodeId) {
      const found = simNodesRef.current.find(n => n.id === selectedNodeId) || filteredNodes.find(n => n.id === selectedNodeId) || null
      setActiveNode(found)
      activeNodeRef.current = found
    } else {
      setActiveNode(null)
      activeNodeRef.current = null
    }
  }, [selectedNodeId, filteredNodes])

  // Stable 60fps canvas render loop (never restarts on hover)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let animId

    const render = (now) => {
      const rect = containerRef.current?.getBoundingClientRect()
      const viewW = Math.max(rect?.width || 900, 300)
      const viewH = Math.max(rect?.height || 620, 220)
      const dpr = window.devicePixelRatio || 1

      if (canvas.width !== Math.round(viewW * dpr) || canvas.height !== Math.round(viewH * dpr)) {
        canvas.width = Math.round(viewW * dpr)
        canvas.height = Math.round(viewH * dpr)
      }

      if (simRunningRef.current && simNodesRef.current.length > 0) {
        const vel = stepPhysicsTick(
          simNodesRef.current,
          simLinksRef.current,
          viewW / 2,
          viewH / 2,
          true
        )
        if (!dragRef.current.isDraggingNode && vel < 0.12) {
          simRunningRef.current = false
          setIsSimRunning(false)
        }
      }

      const isDark = document.documentElement.getAttribute('data-theme') === 'dark'
      const elapsed = Math.max(0, (now || performance.now()) - revealStartRef.current)
      const revealRaw = revealStartRef.current > 0 ? Math.min(1, elapsed / 460) : 1
      const reveal = easeOutCubic(revealRaw)

      ctx.save()
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, viewW, viewH)

      const t = transformRef.current
      const nodes = simNodesRef.current
      const links = simLinksRef.current
      const clusters = clusterMetaRef.current
      const active = activeNodeRef.current
      const hovered = hoveredNodeRef.current
      const focusTarget = hovered || active

      // Subtle background dot grid in world space
      ctx.save()
      ctx.translate(t.x, t.y)
      ctx.scale(t.scale, t.scale)

      ctx.fillStyle = isDark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(100, 116, 139, 0.11)'
      const gridSize = 48
      const startX = Math.floor((-t.x / t.scale) / gridSize) * gridSize
      const endX = startX + viewW / t.scale + gridSize * 2
      const startY = Math.floor((-t.y / t.scale) / gridSize) * gridSize
      const endY = startY + viewH / t.scale + gridSize * 2
      for (let gx = startX; gx < endX; gx += gridSize) {
        for (let gy = startY; gy < endY; gy += gridSize) {
          ctx.beginPath()
          ctx.arc(gx, gy, 1 / Math.sqrt(t.scale), 0, Math.PI * 2)
          ctx.fill()
        }
      }

      if (nodes.length === 0) {
        ctx.restore()
        ctx.restore()
        animId = requestAnimationFrame(render)
        return
      }

      // Spotlight neighbor set
      const connectedNodeIds = new Set()
      if (focusTarget) {
        connectedNodeIds.add(focusTarget.id)
        for (const l of links) {
          if (l.source.id === focusTarget.id) connectedNodeIds.add(l.target.id)
          if (l.target.id === focusTarget.id) connectedNodeIds.add(l.source.id)
        }
      }

      // 0. Category Nebula Halos (airy spatial grouping)
      const haloAlpha = easeOutCubic(Math.min(1, reveal * 1.4)) * (focusTarget ? 0.35 : 1)
      if (clusters.length > 1 && haloAlpha > 0.01) {
        for (const meta of clusters) {
          const r = meta.haloRadius || 120
          const grad = ctx.createRadialGradient(meta.x, meta.y, 12, meta.x, meta.y, r)
          grad.addColorStop(0, toAlphaColor(meta.color, (isDark ? 0.11 : 0.065) * haloAlpha))
          grad.addColorStop(1, toAlphaColor(meta.color, 0))
          ctx.beginPath()
          ctx.arc(meta.x, meta.y, r, 0, Math.PI * 2)
          ctx.fillStyle = grad
          ctx.fill()
        }
      }

      // 1. Edges (calm gentle alpha, stronger on focus)
      const edgeStage = easeOutCubic(Math.max(0, (reveal - 0.08) / 0.85))
      if (edgeStage > 0.01) {
        for (const link of links) {
          const s = link.source
          const target = link.target
          if (!s || !target) continue
          const isConnected = focusTarget && (s.id === focusTarget.id || target.id === focusTarget.id)

          ctx.beginPath()
          ctx.moveTo(s.x, s.y)
          ctx.lineTo(target.x, target.y)

          if (isConnected) {
            ctx.strokeStyle = isDark ? '#34d399' : '#0f766e'
            ctx.lineWidth = 2.1 / Math.sqrt(t.scale)
            ctx.globalAlpha = 0.9 * edgeStage
          } else {
            ctx.strokeStyle = isDark ? 'rgba(148, 163, 184, 0.24)' : 'rgba(100, 116, 139, 0.22)'
            ctx.lineWidth = 1.0 / Math.sqrt(t.scale)
            ctx.globalAlpha = (focusTarget ? 0.08 : 0.55) * edgeStage
          }
          ctx.stroke()
        }
        ctx.globalAlpha = 1
      }

      // 2. Nodes (staggered bloom from inner ring outward)
      const cats = dynamicCategoriesRef.current
      for (const n of nodes) {
        if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) continue
        const localProgress = easeOutCubic(Math.max(0, Math.min(1, (reveal - (n.ringOrder || 0) * 0.16) / 0.72)))
        if (localProgress <= 0.01) continue

        const isSelected = active?.id === n.id
        const isHovered = hovered?.id === n.id
        const isFocus = isSelected || isHovered
        const isPreferred = Boolean(n.preferred || n.user_preference === 'preferred')
        const catInfo = getCategoryInfo(n.category, cats)
        const inSpotlight = !focusTarget || connectedNodeIds.has(n.id)

        const nodeScale = 0.8 + 0.2 * localProgress
        const drawR = n.radius * nodeScale
        ctx.globalAlpha = (inSpotlight ? 1 : 0.16) * localProgress

        if (isPreferred && !n.is_property) {
          ctx.beginPath()
          ctx.arc(n.x, n.y, drawR + 5, 0, Math.PI * 2)
          ctx.strokeStyle = 'rgba(234, 179, 8, 0.6)'
          ctx.lineWidth = 1.8
          ctx.setLineDash([4, 2.5])
          ctx.stroke()
          ctx.setLineDash([])
        }

        if (isFocus) {
          ctx.beginPath()
          ctx.arc(n.x, n.y, drawR + (isPreferred ? 8 : 5), 0, Math.PI * 2)
          ctx.strokeStyle = isDark ? '#34d399' : '#0f766e'
          ctx.lineWidth = 2.6
          ctx.stroke()
        }

        ctx.beginPath()
        ctx.arc(n.x, n.y, drawR, 0, Math.PI * 2)
        ctx.fillStyle = n.is_property
          ? (isDark ? 'rgba(148, 163, 184, 0.22)' : 'rgba(148, 163, 184, 0.18)')
          : toAlphaColor(catInfo.color, isDark ? 0.34 : 0.22)
        ctx.fill()

        ctx.strokeStyle = n.is_property
          ? (isDark ? 'rgba(148, 163, 184, 0.75)' : 'rgba(100, 116, 139, 0.65)')
          : catInfo.color
        ctx.lineWidth = isFocus ? 2.6 : 1.7
        ctx.stroke()

        if (isPreferred && !n.is_property) {
          ctx.beginPath()
          ctx.arc(n.x, n.y, 3.6, 0, Math.PI * 2)
          ctx.fillStyle = '#eab308'
          ctx.fill()
        }
      }

      ctx.globalAlpha = 1
      ctx.restore() // exit world space to draw crisp screen-space collision-free labels

      // 3. Screen-Space Collision-Free Labels + Cluster Headings
      const labelAlpha = easeOutCubic(Math.max(0, (reveal - 0.38) / 0.62))
      if (labelAlpha > 0.02) {
        const placedBoxes = []

        // Reserve space for floating legend, top-right stats badge & bottom-right controls
        if (legendOpenRef.current) {
          placedBoxes.push({ x: 16, y: 12, w: 196, h: 310 })
        }
        placedBoxes.push({ x: viewW - 295, y: 12, w: 285, h: 44 })
        placedBoxes.push({ x: viewW - 68, y: viewH - 180, w: 60, h: 170 })

        // Draw subtle Category Cluster Title Pills at overview zoom
        if (!focusTarget && clusters.length > 1 && t.scale < 1.25) {
          ctx.save()
          ctx.globalAlpha = labelAlpha * 0.92
          ctx.font = '600 11.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
          for (const meta of clusters) {
            const sx = meta.x * t.scale + t.x
            const sy = (meta.y - Math.min(meta.haloRadius || 100, 130) * 0.72) * t.scale + t.y
            if (sx < 40 || sx > viewW - 40 || sy < 24 || sy > viewH - 24) continue
            const text = `${meta.label} · ${meta.count}`
            const m = ctx.measureText(text)
            const w = m.width + 18
            const h = 22
            const box = { x: sx - w / 2, y: sy - h / 2, w, h }
            if (placedBoxes.some(b => boxesOverlap(b, box, 8))) continue
            placedBoxes.push(box)

            ctx.beginPath()
            if (ctx.roundRect) ctx.roundRect(box.x, box.y, box.w, box.h, 11)
            else ctx.rect(box.x, box.y, box.w, box.h)
            ctx.fillStyle = isDark ? 'rgba(24, 32, 28, 0.88)' : 'rgba(255, 255, 255, 0.92)'
            ctx.fill()
            ctx.strokeStyle = toAlphaColor(meta.color, 0.5)
            ctx.lineWidth = 1
            ctx.stroke()

            ctx.beginPath()
            ctx.arc(box.x + 10, box.y + box.h / 2, 3.2, 0, Math.PI * 2)
            ctx.fillStyle = meta.color
            ctx.fill()

            ctx.fillStyle = isDark ? '#e2e8f0' : '#1e293b'
            ctx.textAlign = 'left'
            ctx.textBaseline = 'middle'
            ctx.fillText(text, box.x + 17, box.y + box.h / 2)
          }
          ctx.restore()
        }

        // Rank candidate node labels cleanly so higher-priority items never lose to noise
        const candidates = []
        for (const n of nodes) {
          if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) continue
          const sx = n.x * t.scale + t.x
          const sy = n.y * t.scale + t.y
          if (sx < -40 || sx > viewW + 40 || sy < -30 || sy > viewH + 30) continue

          const isSelected = active?.id === n.id
          const isHovered = hovered?.id === n.id
          const isFocus = isSelected || isHovered
          const isNeighbor = focusTarget ? connectedNodeIds.has(n.id) : false
          const isPref = Boolean(n.preferred || n.user_preference === 'preferred')

          if (!isFocus && !isNeighbor && !isPref && n.degree < 2 && t.scale < 0.95 && nodes.length > 30) {
            continue
          }

          let priority = n.degree || 0
          if (isHovered) priority += 10000
          else if (isSelected) priority += 9000
          else if (isNeighbor) priority += 5000
          else if (isPref && !n.is_property) priority += 1200
          else if (!n.is_property) priority += 100

          candidates.push({ n, sx, sy, isFocus, isNeighbor, priority })
        }

        candidates.sort((a, b) => b.priority - a.priority)

        const maxLabels = focusTarget ? 28 : (t.scale >= 1.15 ? 48 : 18)
        let drawnCount = 0

        for (const item of candidates) {
          if (drawnCount >= maxLabels && !item.isFocus) break
          const { n, sx, sy, isFocus, isNeighbor } = item
          const rawLabel = n.label || n.title || n.name || n.id
          const displayLabel = isFocus
            ? (rawLabel.length > 24 ? rawLabel.slice(0, 23) + '…' : rawLabel)
            : (rawLabel.length > 15 ? rawLabel.slice(0, 14) + '…' : rawLabel)

          const fontSize = isFocus ? 12 : 11
          ctx.font = `${isFocus ? '600 ' : '500 '}${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
          const textW = ctx.measureText(displayLabel).width + 12
          const textH = fontSize + 7
          const box = {
            x: sx - textW / 2,
            y: sy + n.radius * t.scale + 5,
            w: textW,
            h: textH,
          }

          // Strict non-overlap culling (hovered/selected node is always drawn)
          if (!isFocus && placedBoxes.some(b => boxesOverlap(b, box, 5))) {
            continue
          }
          placedBoxes.push(box)
          drawnCount++

          ctx.save()
          ctx.globalAlpha = labelAlpha * (!focusTarget || isFocus || isNeighbor ? 1 : 0.45)
          ctx.beginPath()
          if (ctx.roundRect) ctx.roundRect(box.x, box.y, box.w, box.h, 5)
          else ctx.rect(box.x, box.y, box.w, box.h)
          ctx.fillStyle = isDark
            ? (isFocus ? 'rgba(22, 33, 27, 0.96)' : 'rgba(24, 30, 27, 0.88)')
            : (isFocus ? 'rgba(255, 255, 255, 0.98)' : 'rgba(255, 255, 255, 0.90)')
          ctx.fill()
          ctx.strokeStyle = isFocus
            ? (isDark ? '#34d399' : '#0f766e')
            : (isDark ? 'rgba(255, 255, 255, 0.14)' : 'rgba(203, 213, 225, 0.85)')
          ctx.lineWidth = isFocus ? 1.4 : 1
          ctx.stroke()

          ctx.fillStyle = isFocus
            ? (isDark ? '#34d399' : '#0f766e')
            : (isDark ? '#e2e8f0' : '#1e293b')
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(displayLabel, sx, box.y + box.h / 2)
          ctx.restore()
        }

        // Edge relation label on spotlight focus only
        if (focusTarget) {
          ctx.save()
          ctx.font = '500 10.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
          for (const link of links) {
            if (!link.label) continue
            const isConnected = link.source.id === focusTarget.id || link.target.id === focusTarget.id
            if (!isConnected) continue
            const mx = ((link.source.x + link.target.x) / 2) * t.scale + t.x
            const my = ((link.source.y + link.target.y) / 2) * t.scale + t.y
            ctx.fillStyle = isDark ? '#34d399' : '#0f766e'
            ctx.textAlign = 'center'
            ctx.textBaseline = 'middle'
            ctx.fillText(link.label, mx, my - 7)
          }
          ctx.restore()
        }
      }

      ctx.restore()
      animId = requestAnimationFrame(render)
    }

    animId = requestAnimationFrame(render)
    return () => cancelAnimationFrame(animId)
  }, [stepPhysicsTick])

  const handleWheel = useCallback((e) => {
    e.preventDefault()
    const rect = canvasRef.current.getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    const mouseY = e.clientY - rect.top

    const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89
    const currentScale = transformRef.current.scale
    const newScale = Math.min(Math.max(currentScale * zoomFactor, 0.25), 3.2)

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
      if (dx * dx + dy * dy <= (n.radius + 5) * (n.radius + 5)) {
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

    dragRef.current.startX = e.clientX
    dragRef.current.startY = e.clientY

    const hitNode = getNodeAtPosition(mouseX, mouseY)
    if (hitNode) {
      dragRef.current.isDraggingNode = true
      dragRef.current.draggedNode = hitNode
      hitNode.fixed = true
    } else {
      dragRef.current.isPanning = true
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
      dragRef.current.draggedNode.x = (mouseX - t.x) / t.scale
      dragRef.current.draggedNode.y = (mouseY - t.y) / t.scale
      dragRef.current.draggedNode.vx = 0
      dragRef.current.draggedNode.vy = 0
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
    if (hit !== hoveredNodeRef.current) {
      hoveredNodeRef.current = hit
      setHoveredNode(hit)
    }
  }, [getNodeAtPosition])

  const handleMouseUp = useCallback((e) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    const mouseX = rect ? e.clientX - rect.left : 0
    const mouseY = rect ? e.clientY - rect.top : 0
    const dist = Math.hypot(
      e.clientX - dragRef.current.startX,
      e.clientY - dragRef.current.startY
    )

    if (dragRef.current.isDraggingNode && dragRef.current.draggedNode) {
      const node = dragRef.current.draggedNode
      node.fixed = false
      dragRef.current.isDraggingNode = false
      dragRef.current.draggedNode = null

      if (dist < 6) {
        activeNodeRef.current = node
        setActiveNode(node)
        onSelectNode?.(node.id)
      }
      return
    }

    if (dragRef.current.isPanning) {
      dragRef.current.isPanning = false
      if (dist < 6 && rect) {
        const hit = getNodeAtPosition(mouseX, mouseY)
        activeNodeRef.current = hit
        setActiveNode(hit)
        onSelectNode?.(hit?.id || null)
      }
    }
  }, [getNodeAtPosition, onSelectNode])

  const handleResetView = useCallback(() => {
    const width = containerRef.current?.clientWidth || 960
    const height = containerRef.current?.clientHeight || 640
    const fit = computeFitTransform(simNodesRef.current, width, height, legendOpenRef.current)
    fitTransformRef.current = fit
    transformRef.current = { ...fit }
    setTransformState({ scale: fit.scale })
  }, [])

  const handleZoom = useCallback((delta) => {
    const currentScale = transformRef.current.scale
    const newScale = Math.min(Math.max(currentScale + delta, 0.25), 3.2)
    const rect = canvasRef.current.getBoundingClientRect()
    const centerX = rect.width / 2
    const centerY = rect.height / 2
    const newX = centerX - (centerX - transformRef.current.x) * (newScale / currentScale)
    const newY = centerY - (centerY - transformRef.current.y) * (newScale / currentScale)

    transformRef.current = { x: newX, y: newY, scale: newScale }
    setTransformState({ scale: newScale })
  }, [])

  const theoryCount = filteredNodes.filter(n => !n.is_property).length
  const propCount = filteredNodes.length - theoryCount

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

      {/* 平滑加载态遮罩 */}
      {loading && (
        <div className="kw-graph-loading-overlay" role="status" aria-live="polite">
          <div className="kw-graph-loading-card">
            <span className="kw-graph-orbit" aria-hidden="true" />
            <span>正在编排星系知识拓扑…</span>
          </div>
        </div>
      )}

      {/* 右上角轻量拓扑摘要徽标 */}
      {graphReady && !loading && filteredNodes.length > 0 && (
        <div className="kw-graph-stats-badge">
          <span className="kw-graph-stats-dot" aria-hidden="true" />
          <span>{theoryCount} 条理论 · {propCount} 个性质枢纽 · {filteredLinks.length} 条关联</span>
        </div>
      )}

      {/* Floating Controls */}
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
          title="自适应居中全图"
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
          title={isSimRunning ? '锁定静态拓扑' : '启用动态引力微调'}
          aria-label="引力控制"
        >
          {isSimRunning ? (
            <Icon.Stop style={{ width: 14, height: 14 }} />
          ) : (
            <Icon.Play style={{ width: 14, height: 14 }} />
          )}
        </button>
      </div>

      {/* Graph Legend */}
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
    </div>
  )
}
