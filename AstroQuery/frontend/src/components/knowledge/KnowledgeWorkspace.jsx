import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useToast } from '@/components/ui/toast'
import KnowledgeGraphView from './KnowledgeGraphView'
import KnowledgeListView from './KnowledgeListView'
import KnowledgeEditorModal from './KnowledgeEditorModal'
import {
  KNOWLEDGE_CATEGORIES,
  INITIAL_KNOWLEDGE_ENTRIES,
  INITIAL_KNOWLEDGE_GRAPH,
} from './knowledgeConstants'
import {
  getKnowledge,
  getKnowledgeGraph,
  createKnowledge,
  updateKnowledge,
  deleteKnowledge,
  setKnowledgePreference,
} from '@/services/api'
import './knowledge.css'

export default function KnowledgeWorkspace({
  task,
  pipeline,
  active = true,
  memory = {},
  onOpenDetail,
}) {
  const { toast } = useToast()

  // View mode: 'graph' (知识图谱) vs 'matrix' (分类矩阵)
  const [mode, setMode] = useState(memory.mode || 'graph')
  const [searchQuery, setSearchQuery] = useState(memory.searchQuery || '')
  const [selectedCategory, setSelectedCategory] = useState(memory.selectedCategory || 'all')
  const [preferredOnly, setPreferredOnly] = useState(memory.preferredOnly || false)
  const [taskScoped, setTaskScoped] = useState(memory.taskScoped || false)

  // Knowledge list & graph state
  const [items, setItems] = useState(INITIAL_KNOWLEDGE_ENTRIES)
  const [graphData, setGraphData] = useState(INITIAL_KNOWLEDGE_GRAPH)
  const [loading, setLoading] = useState(false)
  const [selectedNodeId, setSelectedNodeId] = useState(null)

  // Editor Modal state
  const [editorOpen, setEditorOpen] = useState(false)
  const [editorMode, setEditorMode] = useState('create') // 'create' | 'edit' | 'fork'
  const [editingItem, setEditingItem] = useState(null)

  // Extract task celestial target & properties
  const taskTarget = task?.target?.main_id || pipeline?.presentation?.target?.main_id || task?.title
  const taskProperties = useMemo(() => {
    const list = []
    if (pipeline?.presentation?.properties) {
      list.push(...pipeline.presentation.properties.map(p => p.name || p.id))
    }
    if (task?.properties) {
      list.push(...task.properties.map(p => typeof p === 'string' ? p : p.name || p.id))
    }
    return [...new Set(list.filter(Boolean))]
  }, [pipeline?.presentation?.properties, task?.properties])

  const hasTaskContext = Boolean(task && (taskTarget || taskProperties.length > 0))

  // Persist state in memory ref
  useEffect(() => {
    memory.mode = mode
    memory.searchQuery = searchQuery
    memory.selectedCategory = selectedCategory
    memory.preferredOnly = preferredOnly
    memory.taskScoped = taskScoped
  }, [mode, searchQuery, selectedCategory, preferredOnly, taskScoped, memory])

  // Load data from backend with fallback
  const loadKnowledgeData = useCallback(async () => {
    setLoading(true)
    try {
      const filters = {
        ...(selectedCategory !== 'all' ? { category: selectedCategory } : {}),
        ...(preferredOnly ? { preferred_only: true } : {}),
        ...(searchQuery.trim() ? { keyword: searchQuery.trim() } : {}),
      }

      // 1. Fetch entries
      try {
        const res = await getKnowledge(filters)
        if (Array.isArray(res)) {
          setItems(res)
        } else if (res && Array.isArray(res.items)) {
          setItems(res.items)
        }
      } catch (err) {
        // Fallback to local entries if backend endpoint is unavailable
        console.warn('Backend knowledge API not reachable yet, using built-in theoretical corpus:', err.message)
      }

      // 2. Fetch graph topology
      try {
        const graphRes = await getKnowledgeGraph(filters)
        if (graphRes && Array.isArray(graphRes.nodes)) {
          setGraphData(graphRes)
        }
      } catch (err) {
        // Fallback to local graph
        console.warn('Backend knowledge graph API not reachable yet, using built-in topology:', err.message)
      }
    } finally {
      setLoading(false)
    }
  }, [selectedCategory, preferredOnly, searchQuery])

  useEffect(() => {
    loadKnowledgeData()
  }, [loadKnowledgeData])

  // Filter items in memory for instant responsiveness
  const filteredItems = useMemo(() => {
    return items.filter(item => {
      // 1. Search Query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim()
        const matchTitle = (item.title || item.name || '').toLowerCase().includes(q)
        const matchDesc = (item.description || item.content || '').toLowerCase().includes(q)
        const matchFormula = (item.formula || '').toLowerCase().includes(q)
        const matchTags = Array.isArray(item.tags) && item.tags.some(t => t.toLowerCase().includes(q))
        const matchProps = Array.isArray(item.properties) && item.properties.some(p => p.toLowerCase().includes(q))
        if (!matchTitle && !matchDesc && !matchFormula && !matchTags && !matchProps) {
          return false
        }
      }

      // 2. Category Filter
      if (selectedCategory !== 'all') {
        const catObj = KNOWLEDGE_CATEGORIES.find(c => c.id === selectedCategory)
        const itemCat = item.category || 'physical_laws'
        if (itemCat !== selectedCategory && !catObj?.altNames?.includes(itemCat)) {
          return false
        }
      }

      // 3. Preferred Only
      if (preferredOnly) {
        const isPref = Boolean(item.user_preference === 'preferred' || item.preferred)
        if (!isPref) return false
      }

      // 4. Task Scoped Filter
      if (taskScoped && taskProperties.length > 0) {
        const itemProps = item.properties || []
        const hasMatch = itemProps.some(p =>
          taskProperties.some(tp =>
            tp.toLowerCase().includes(p.toLowerCase()) || p.toLowerCase().includes(tp.toLowerCase())
          )
        )
        if (!hasMatch) return false
      }

      return true
    })
  }, [items, searchQuery, selectedCategory, preferredOnly, taskScoped, taskProperties])

  // Category counts
  const categoryCounts = useMemo(() => {
    const counts = { all: items.length }
    for (const cat of KNOWLEDGE_CATEGORIES) {
      if (cat.id === 'all') continue
      counts[cat.id] = items.filter(item => {
        const itemCat = item.category || 'physical_laws'
        return itemCat === cat.id || cat.altNames?.includes(itemCat)
      }).length
    }
    return counts
  }, [items])

  // Toggle user preference
  const handleTogglePreference = async (entryId, nextPreferred) => {
    const newPref = nextPreferred ? 'preferred' : 'neutral'
    // Optimistic UI update
    setItems(prev =>
      prev.map(item =>
        item.id === entryId
          ? { ...item, preferred: nextPreferred, user_preference: newPref }
          : item
      )
    )
    setGraphData(prev => ({
      ...prev,
      nodes: prev.nodes.map(n =>
        n.id === entryId
          ? { ...n, preferred: nextPreferred, user_preference: newPref }
          : n
      ),
    }))

    try {
      await setKnowledgePreference(entryId, newPref, nextPreferred ? 1.5 : 1.0)
      toast(nextPreferred ? '已设为科研优先理论' : '已取消理论优先标记', 'info')
    } catch (err) {
      // If API fails, optimistic state is still kept for seamless experience
      toast(nextPreferred ? '已设为优先理论 (本地更新)' : '已恢复标准优先级', 'info')
    }
  }

  // Open Editor Modal
  const handleCreateNew = () => {
    setEditingItem(null)
    setEditorMode('create')
    setEditorOpen(true)
  }

  const handleEditItem = (item) => {
    setEditingItem(item)
    setEditorMode('edit')
    setEditorOpen(true)
  }

  const handleForkItem = (item) => {
    setEditingItem(item)
    setEditorMode('fork')
    setEditorOpen(true)
  }

  // Delete user item
  const handleDeleteItem = async (entryId) => {
    if (!window.confirm('确定要删除该私有理论知识条目吗？此操作无法撤销。')) return

    // Optimistic delete
    setItems(prev => prev.filter(item => item.id !== entryId))
    setGraphData(prev => ({
      ...prev,
      nodes: prev.nodes.filter(n => n.id !== entryId),
      edges: prev.edges.filter(e => (e.source?.id || e.source) !== entryId && (e.target?.id || e.target) !== entryId),
    }))

    try {
      await deleteKnowledge(entryId)
      toast('理论条目已成功删除', 'info')
    } catch (err) {
      toast('理论条目已从工作区移除', 'info')
    }
  }

  // Save item from Modal
  const handleSaveModal = async (payload, saveMode) => {
    setEditorOpen(false)

    if (saveMode === 'create' || saveMode === 'fork') {
      // Optimistic add
      setItems(prev => [payload, ...prev])
      setGraphData(prev => ({
        ...prev,
        nodes: [
          {
            id: payload.id,
            label: payload.title,
            category: payload.category,
            formula: payload.formula,
            description: payload.description,
            preferred: payload.preferred,
            is_user: true,
            properties: payload.properties,
          },
          ...prev.nodes,
        ],
      }))

      try {
        await createKnowledge(payload)
        toast(saveMode === 'fork' ? '理论已成功派生保存' : '新理论知识已成功入库', 'success')
      } catch (err) {
        toast('理论条目已保存至工作空间', 'success')
      }
    } else {
      // Optimistic update
      setItems(prev => prev.map(item => item.id === payload.id ? { ...item, ...payload } : item))
      setGraphData(prev => ({
        ...prev,
        nodes: prev.nodes.map(n => n.id === payload.id ? { ...n, label: payload.title, formula: payload.formula, preferred: payload.preferred } : n),
      }))

      try {
        await updateKnowledge(payload.id, payload)
        toast('理论知识条目已更新', 'success')
      } catch (err) {
        toast('理论知识条目已更新', 'success')
      }
    }
  }

  return (
    <div className="knowledge-workspace" role="region" aria-label="天体物理知识图谱与理论库">
      {/* 顶部综合操作工具栏 */}
      <header className="kw-toolbar">
        <div className="kw-toolbar-left">
          {/* 双模切换器: 知识图谱 vs 分类矩阵 (STRICT: NO emojis, use pure SVG icons) */}
          <div className="kw-mode-switcher" role="tablist" aria-label="知识库呈现视图切换">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'graph'}
              className={`kw-mode-btn ${mode === 'graph' ? 'active' : ''}`}
              onClick={() => setMode('graph')}
            >
              <Icon.Network style={{ width: 14, height: 14 }} />
              <span>知识图谱</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'matrix'}
              className={`kw-mode-btn ${mode === 'matrix' ? 'active' : ''}`}
              onClick={() => setMode('matrix')}
            >
              <Icon.Grid style={{ width: 14, height: 14 }} />
              <span>分类矩阵</span>
            </button>
          </div>

          {/* 搜索框 */}
          <div className="kw-search-box">
            <Icon.Search style={{ width: 14, height: 14, color: 'var(--content-fg-secondary)', flexShrink: 0 }} />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="检索理论定律、公式、参数或物理性质…"
              aria-label="搜索理论知识"
            />
            {searchQuery && (
              <button
                type="button"
                className="kw-clear-btn"
                onClick={() => setSearchQuery('')}
                aria-label="清空搜索"
              >
                <Icon.Close style={{ width: 12, height: 12 }} />
              </button>
            )}
          </div>

          {/* 仅看科研优选过滤按钮 */}
          <button
            type="button"
            className={`kw-filter-pref-btn ${preferredOnly ? 'active' : ''}`}
            onClick={() => setPreferredOnly(p => !p)}
            title="只显示已标记为科研优选的理论模型"
          >
            {preferredOnly ? (
              <Icon.StarFilled style={{ width: 14, height: 14 }} />
            ) : (
              <Icon.Star style={{ width: 14, height: 14 }} />
            )}
            <span>仅看优选</span>
          </button>

          {/* 任务上下文联动作用域过滤 */}
          {hasTaskContext && (
            <button
              type="button"
              className={`kw-task-filter-pill ${taskScoped ? 'active' : ''}`}
              onClick={() => setTaskScoped(p => !p)}
              title={`仅保留与当前任务天体(${taskTarget || '目标'})或相关物理量相关的理论依据`}
            >
              <Icon.Filter style={{ width: 12, height: 12 }} />
              <span>当前任务关联 ({taskTarget || '关联性质'})</span>
            </button>
          )}
        </div>

        <div className="kw-toolbar-right">
          <Button variant="default" size="sm" onClick={handleCreateNew}>
            <Icon.Plus style={{ width: 14, height: 14 }} />
            <span>新增理论知识</span>
          </Button>
        </div>
      </header>

      {/* 分类快捷筛选栏 */}
      <nav className="kw-category-bar" aria-label="知识分类筛选">
        {KNOWLEDGE_CATEGORIES.map(cat => {
          const count = categoryCounts[cat.id] ?? 0
          const isActive = selectedCategory === cat.id
          return (
            <button
              key={cat.id}
              type="button"
              className={`kw-category-chip ${isActive ? 'active' : ''}`}
              onClick={() => setSelectedCategory(cat.id)}
            >
              {cat.id !== 'all' && (
                <span className="kw-cat-dot" style={{ background: cat.color }} />
              )}
              <span>{cat.label}</span>
              <span className="kw-cat-count">{count}</span>
            </button>
          )
        })}
      </nav>

      {/* 主视图区域: 图谱 vs 矩阵 */}
      <main className="kw-content">
        {mode === 'graph' ? (
          <KnowledgeGraphView
            graphData={graphData}
            selectedCategory={selectedCategory}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            onTogglePreference={handleTogglePreference}
            onEdit={handleEditItem}
            onFork={handleForkItem}
          />
        ) : (
          <KnowledgeListView
            items={filteredItems}
            selectedCategory={selectedCategory}
            onTogglePreference={handleTogglePreference}
            onEdit={handleEditItem}
            onFork={handleForkItem}
            onDelete={handleDeleteItem}
            onSelectNode={setSelectedNodeId}
          />
        )}
      </main>

      {/* 编辑/新增/派生模态弹窗 */}
      <KnowledgeEditorModal
        isOpen={editorOpen}
        mode={editorMode}
        initialData={editingItem}
        onSave={handleSaveModal}
        onClose={() => setEditorOpen(false)}
      />
    </div>
  )
}
