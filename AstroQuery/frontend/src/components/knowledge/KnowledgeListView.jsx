import React, { useState } from 'react'
import { Icon } from '@/components/icons'
import { LatexText } from '@/components/results/LatexMath'
import { KNOWLEDGE_CATEGORIES, getCategoryInfo } from './knowledgeConstants'
import { readingPage, sourceRecords } from './knowledgeReading'
import { EntryActions, EntryBadges, Formula, PropertyTags, DeleteConfirmation } from './knowledgeReadingParts'
import './knowledgeReading.css'

export default function KnowledgeListView({
  items = [], categories = KNOWLEDGE_CATEGORIES, mode = 'cards', onModeChange,
  selectedId, total = items.length, offset = 0, limit = mode === 'table' ? 50 : 24,
  onPageChange, onPageSizeChange, sort = 'name', onSortChange, loading = false,
  readOnly = false, pendingIds = [], onTogglePreference, onEdit, onFork, onDelete, onRestore, onSelectNode,
}) {
  const [deleteItem, setDeleteItem] = useState(null)
  const [error, setError] = useState('')
  const page = readingPage({ total, offset, limit, count: items.length })
  const pending = id => pendingIds instanceof Set ? pendingIds.has(id) : Array.isArray(pendingIds) ? pendingIds.includes(id) : Boolean(pendingIds[id])
  const actions = item => <EntryActions item={item} readOnly={readOnly} pending={pending(item.id)} onTogglePreference={onTogglePreference}
    onEdit={onEdit} onFork={onFork} onDelete={onDelete ? setDeleteItem : undefined} onRestore={onRestore} onError={setError} />
  return <div className="kr-reading" aria-busy={loading}>
    <div className="kr-reading-toolbar">
      <div className="kr-mode-switch" aria-label="阅读布局">
        <button type="button" className="kr-button" aria-pressed={mode === 'cards'} onClick={() => onModeChange?.('cards')}><Icon.Grid />卡片</button>
        <button type="button" className="kr-button" aria-pressed={mode === 'table'} onClick={() => onModeChange?.('table')}><Icon.Table />表格</button>
      </div>
      <label className="kr-sort-label">排序<select className="kr-select" value={sort} onChange={event => onSortChange?.(event.target.value)}>
        <option value="name">名称</option><option value="relevance">相关度</option><option value="preferred">科研优选</option><option value="updated">最近更新</option>
      </select></label>
    </div>
    {error && <div className="kr-error" role="alert">{error}<button className="kr-icon-button" type="button" aria-label="关闭操作错误" onClick={() => setError('')}><Icon.Close /></button></div>}
    <div className="kr-reading-content">
      {!items.length ? <div className="kr-empty" role="status"><Icon.Search /><h3>{loading ? '正在载入知识条目…' : '未找到匹配的知识条目'}</h3>
        <p>{loading ? '正在查询当前筛选范围。' : '请调整关键词、分类或过滤条件。'}</p></div> : mode === 'table' ?
        <div className="kr-table-scroll"><table className="kr-table"><caption className="kr-sr-only">知识条目矩阵</caption>
          <thead><tr><th scope="col">名称</th><th scope="col">公式</th><th scope="col">关联物理量</th><th scope="col">来源</th><th scope="col">科研优选</th><th scope="col">更新</th><th scope="col"><span className="kr-sr-only">操作</span></th></tr></thead>
          <tbody>{items.map(item => <tr key={item.id} data-entry-id={item.id} aria-selected={selectedId === item.id} onClick={() => onSelectNode?.(item.id)}>
            <td><button type="button" className="kr-title-button" onClick={event => { event.stopPropagation(); onSelectNode?.(item.id) }}>{item.title || item.name || item.label || item.id}</button><span className="kr-table-category">{getCategoryInfo(item.category, categories).label}</span></td>
            <td><Formula compact formula={item.formula} /></td><td><PropertyTags values={item.properties} limit={2} onMore={() => onSelectNode?.(item.id)} /></td>
            <td><EntryBadges item={item} showCategory={false} /><span className="kr-table-source">{sourceRecords(item.sources)[0]?.title || '未提供来源'}</span></td>
            <td><span className={item.preferred || item.user_preference === 'preferred' ? 'kr-preferred' : 'kr-missing'}>{item.preferred || item.user_preference === 'preferred' ? '已优选' : '未优选'}</span></td>
            <td><time dateTime={item.updated_at || undefined}>{item.updated_at ? new Date(item.updated_at).toLocaleDateString('zh-CN') : '未提供'}</time></td><td>{actions(item)}</td>
          </tr>)}</tbody></table></div> :
        <div className="kr-card-grid">{items.map(item => <article className={`kr-card ${selectedId === item.id ? 'kr-card-selected' : ''}`} key={item.id} data-entry-id={item.id} onClick={() => onSelectNode?.(item.id)}>
          <header className="kr-card-header"><EntryBadges item={item} categories={categories} />{actions(item)}</header>
          <h3><button className="kr-title-button" type="button" onClick={event => { event.stopPropagation(); onSelectNode?.(item.id) }}>{item.title || item.name || item.label || item.id}</button></h3>
          <Formula formula={item.formula} compact /><p className="kr-card-summary">{item.description ? <LatexText text={item.description} /> : <span className="kr-missing">未提供描述</span>}</p>
          <PropertyTags values={item.properties} limit={3} onMore={() => onSelectNode?.(item.id)} /><footer className="kr-card-source"><Icon.BookOpen /><span>{sourceRecords(item.sources)[0]?.title || '未提供来源'}</span></footer>
        </article>)}</div>}
    </div>
    <footer className="kr-pagination">
      <span role="status">{page.start}–{page.end} / {page.total} 条</span>
      <div className="kr-pagination-actions">{mode === 'table' ? <label>每页<select className="kr-select" value={limit} onChange={event => onPageSizeChange?.(Number(event.target.value))}>{[25, 50, 100].map(size => <option key={size} value={size}>{size}</option>)}</select></label> : <span>24 条 / 页</span>}
        <button type="button" className="kr-icon-button" aria-label="上一页" disabled={!page.hasPrevious || loading} onClick={() => onPageChange?.(page.previous)}><Icon.ChevronLeft /></button>
        <button type="button" className="kr-icon-button" aria-label="下一页" disabled={!page.hasNext || loading} onClick={() => onPageChange?.(page.next)}><Icon.ChevronRight /></button>
      </div>
    </footer>
    {deleteItem && <DeleteConfirmation item={deleteItem} pending={pending(deleteItem.id)} onCancel={() => setDeleteItem(null)} onConfirm={async id => { if (readOnly) throw new Error('当前知识库为只读状态'); await onDelete?.(id) }} />}
  </div>
}
