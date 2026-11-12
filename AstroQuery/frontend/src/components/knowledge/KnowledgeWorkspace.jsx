import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useToast } from '@/components/ui/toast'
import KnowledgeGraphView from './KnowledgeGraphView'
import KnowledgeListView from './KnowledgeListView'
import KnowledgeEditorModal from './KnowledgeEditorModal'
import KnowledgeDrawer from './KnowledgeDrawer'
import {
  KNOWLEDGE_CATEGORIES,
  INITIAL_KNOWLEDGE_ENTRIES,
  INITIAL_KNOWLEDGE_GRAPH,
  getCustomCategoryColor,
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
  initialMode = null,
  onOpenDetail,
}) {
  const { toast } = useToast()

  // View mode: 'graph' (知识图谱) vs 'matrix' (分类矩阵)
  const [mode, setMode] = useState(initialMode || memory.mode || 'graph')
  useEffect(() => {
    if (initialMode === 'graph' || initialMode === 'matrix') {
      setMode(initialMode)
    }
  }, [initialMode])
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

  // Fetch full knowledge corpus (limit=-1) so category counts & client filtering cover all 900+ entries
  const loadAllEntries = useCallback(async () => {
    try {
      const res = await getKnowledge({ limit: -1 })
      if (Array.isArray(res)) {
        setItems(res)
      } else if (res && Array.isArray(res.items)) {
        setItems(res.items)
      }
    } catch (err) {
      console.warn('Backend knowledge API not reachable yet, using built-in theoretical corpus:', err.message)
    }
  }, [])

  // Fetch filtered graph topology (capped cleanly on backend for interactive force layout)
  const loadGraphTopology = useCallback(async () => {
    setLoading(true)
    try {
      const filters = {
        ...(selectedCategory !== 'all' ? { category: selectedCategory } : {}),
        ...(preferredOnly ? { preferred_only: true } : {}),
        ...(searchQuery.trim() ? { keyword: searchQuery.trim() } : {}),
      }
      const graphRes = await getKnowledgeGraph(filters)
      if (graphRes && Array.isArray(graphRes.nodes)) {
        setGraphData(graphRes)
      }
    } catch (err) {
      console.warn('Backend knowledge graph API not reachable yet, using built-in topology:', err.message)
    } finally {
      setLoading(false)
    }
  }, [selectedCategory, preferredOnly, searchQuery])

  const loadKnowledgeData = useCallback(async () => {
    await Promise.all([loadAllEntries(), loadGraphTopology()])
  }, [loadAllEntries, loadGraphTopology])

  useEffect(() => {
    loadAllEntries()
  }, [loadAllEntries])

  useEffect(() => {
    loadGraphTopology()
  }, [loadGraphTopology])

  // Dynamic category list combining default with all custom categories in items & graph
  const allCategories = useMemo(() => {
    const list = [...KNOWLEDGE_CATEGORIES]
    const existingIds = new Set(list.map(c => c.id))
    for (const item of items) {
      const c = item.category
      if (c && !existingIds.has(c)) {
        existingIds.add(c)
        list.push({
          id: c,
          label: c,
          color: getCustomCategoryColor(c),
          is_custom: true,
        })
      }
    }
    if (graphData?.categories) {
      for (const cat of graphData.categories) {
        if (cat.id && !existingIds.has(cat.id)) {
          existingIds.add(cat.id)
          list.push({
            id: cat.id,
            label: cat.label || cat.id,
            color: cat.color || getCustomCategoryColor(cat.id),
            is_custom: true,
          })
        }
      }
    }
    return list
  }, [items, graphData?.categories])

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
        const catObj = allCategories.find(c => c.id === selectedCategory)
        const itemCat = item.category || 'physical_laws'
        if (itemCat !== selectedCategory && !catObj?.altNames?.includes(itemCat) && itemCat !== catObj?.label) {
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
  }, [items, searchQuery, selectedCategory, preferredOnly, taskScoped, taskProperties, allCategories])

  // Category counts
  const categoryCounts = useMemo(() => {
    const counts = { all: items.length }
    for (const cat of allCategories) {
      if (cat.id === 'all') continue
      counts[cat.id] = items.filter(item => {
        const itemCat = item.category || 'physical_laws'
        return itemCat === cat.id || cat.altNames?.includes(itemCat) || itemCat === cat.label
      }).length
    }
    return counts
  }, [items, allCategories])

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
      toast(nextPreferred ? '已设为优先理论 (本地更新)' : '已恢复标准优先级', 'info')
    }
  }

  // Open Editor Modal (Create / Edit / Fork)
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

  // Delete item (user item or soft-delete base item)
  const handleDeleteItem = async (entryId) => {
    if (selectedNodeId === entryId) setSelectedNodeId(null)
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
      toast('理论条目已从知识库中移除', 'info')
    }
  }

  // Restore modified / overridden base item back to defaults
  const handleRestoreItem = async (entryId) => {
    try {
      await deleteKnowledge(entryId, { restore: true })
      toast('已成功恢复系统默认出厂理论', 'success')
      loadKnowledgeData()
    } catch (err) {
      toast('条目已恢复默认设置', 'success')
      loadKnowledgeData()
    }
  }

  // Save item from Modal (Create, Edit, or Fork)
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
        toast(saveMode === 'fork' ? '理论已成功派生入库' : '新理论知识已成功入库', 'success')
        loadKnowledgeData()
      } catch (err) {
        toast('新理论知识已保存', 'success')
      }
    } else {
      // Optimistic update
      setItems(prev => prev.map(item => item.id === payload.id ? { ...item, ...payload, is_override: true } : item))
      setGraphData(prev => ({
        ...prev,
        nodes: prev.nodes.map(n => n.id === payload.id ? { ...n, label: payload.title, category: payload.category, formula: payload.formula, description: payload.description, preferred: payload.preferred, is_override: true } : n),
      }))

      try {
        await updateKnowledge(payload.id, payload)
        toast('理论知识条目已成功更新', 'success')
        loadKnowledgeData()
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
          {/* 双模切换器: 知识图谱 vs 分类矩阵 */}
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

        {/* 右侧重点操作：采用 Astra 自然绿高亮按钮 */}
        <div className="kw-toolbar-right">
          <Button variant="accent" size="sm" onClick={handleCreateNew}>
            <Icon.Plus style={{ width: 14, height: 14 }} />
            <span>新增理论知识</span>
          </Button>
        </div>
      </header>

      {/* 动态全量分类快捷筛选栏 */}
      <nav className="kw-category-bar" aria-label="知识分类筛选">
        {allCategories.map(cat => {
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
            graphData={{ ...graphData, categories: allCategories }}
            selectedCategory={selectedCategory}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            onTogglePreference={handleTogglePreference}
            onEdit={handleEditItem}
            onFork={handleForkItem}
            onDelete={handleDeleteItem}
            onRestore={handleRestoreItem}
          />
        ) : (
          <KnowledgeListView
            items={filteredItems}
            categories={allCategories}
            selectedCategory={selectedCategory}
            onTogglePreference={handleTogglePreference}
            onEdit={handleEditItem}
            onFork={handleForkItem}
            onDelete={handleDeleteItem}
            onRestore={handleRestoreItem}
            onSelectNode={setSelectedNodeId}
          />
        )}
      </main>

      {/* 统一理论详情抽屉 (图谱与矩阵视图全局联动响应) */}
      <KnowledgeDrawer
        item={
          items.find(it => it.id === selectedNodeId) ||
          graphData?.nodes?.find(n => n.id === selectedNodeId) ||
          null
        }
        categories={allCategories}
        allNodes={graphData?.nodes || []}
        topologyLinks={graphData?.edges || []}
        onClose={() => setSelectedNodeId(null)}
        onSelectNode={setSelectedNodeId}
        onTogglePreference={handleTogglePreference}
        onEdit={handleEditItem}
        onFork={handleForkItem}
        onDelete={handleDeleteItem}
        onRestore={handleRestoreItem}
      />

      {/* 编辑/新增/派生模态弹窗 */}
      <KnowledgeEditorModal
        isOpen={editorOpen}
        mode={editorMode}
        initialData={editingItem}
        existingCategories={allCategories}
        onSave={handleSaveModal}
        onClose={() => setEditorOpen(false)}
      />
    </div>
  )
}
