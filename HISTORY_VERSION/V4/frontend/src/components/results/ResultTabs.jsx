import { sourceType, SOURCE_TYPES, extractionLabel } from '@/lib/readableData'
import { useRememberedState } from '@/hooks/useViewMemory'
import { usePageTransition } from '@/hooks/usePageTransition'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { Pagination } from './AnalysisView'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useToast } from '@/components/ui/toast'
import * as api from '@/services/api'
import { useWheelHorizontal } from '@/hooks/useWheelHorizontal'
import { journalLabel } from '@/lib/journal'
import { sourceName } from '@/lib/readableData'
import { DUP_REASON_TEXT } from '@/lib/dupMarkers'
import { matchesRecordSearch } from '@/lib/recordSearch'

/* 结果组件库（契约 D7-1：主区只留记录表格；来源/质量/下载移右侧面板）
 * 导出：RecordsTable（主区全宽）/ SourcesList / OutputFiles（右侧面板）
 */

const PAGE_SIZES = [10, 20, 50]
const MONO = 'ui-monospace, Menlo, Consolas, monospace'

/* 提取方式 badge（用户重设计：VLM 文本=蓝 / VLM 表格=绿 / 其他=灰） */
function MethodBadge({ method }) {
  const m = typeof method === 'string' ? method : ''
  const vlm = m.startsWith('vlm')
  const style = {
    padding: '2px 9px',
    borderRadius: 8,
    fontSize: 11,
    fontWeight: 510,
    display: 'inline-block',
  }
  if (!vlm) {
    return <span style={{ ...style, background: 'var(--surface-secondary)', color: 'var(--content-fg-secondary)' }}>{extractionLabel(m)}</span>
  }
  if (m === 'vlm_table') {
    return <span style={{ ...style, background: 'var(--status-success-bg)', color: 'var(--status-success)' }}>VLM 表格</span>
  }
  return <span style={{ ...style, background: 'var(--status-progress-bg)', color: 'var(--status-progress)' }}>{extractionLabel(m)}</span>
}

/* 疑似重复徽标（2026-09-06，用户决策：重复组内仅标非代表成员行；代表行无徽标）
 * 颜色走 --status-warn 系列（明暗自适应）；hover title 说明与谁重复、代表是谁及选取原因 */
const DUP_BADGE_STYLE = {
  display: 'inline-block', marginLeft: 6, padding: '1px 7px',
  fontSize: 10, lineHeight: '15px', fontWeight: 600,
  borderRadius: 'var(--radius-pill)', whiteSpace: 'nowrap',
  background: 'var(--status-warn-bg)', color: 'var(--status-warn)',
  verticalAlign: '2px',
}

/* 徽标 hover 文案（原生 title 多行）：组内其余来源 + 代表 + 规则/原则；
 * 「共 N 条」读组对象原始规模（用户删除过的行不计入展示但口径不撒谎） */
function dupBadgeTitle(group, selfId) {
  const labels = []
  for (const m of group.members) {
    if (!m.isLive || m.recordId === selfId) continue
    const s = journalLabel(m.sourceId) || m.sourceId
    if (!labels.includes(s)) labels.push(s)
  }
  const others = labels.length > 4
    ? `${labels.slice(0, 4).join('、')} 等 ${group.recordIds.length - 1} 条`
    : labels.join('、')
  const lines = [
    `${group.entityName} · ${group.fieldName} = ${group.fieldValue}：共 ${group.recordIds.length} 条记录在 ${group.sourceCount} 个来源中完全一致（重复收录）`,
    `本行与 ${others} 疑似重复`,
  ]
  if (group.rep) {
    lines.push(`保留代表：${journalLabel(group.rep.sourceId) || group.rep.sourceId}（${DUP_REASON_TEXT[group.rep.reason] || group.rep.reason}）`)
  }
  lines.push('全量保留标注：未删除任何重复记录')
  return lines.join('\n')
}

function DupBadge({ group, recordId }) {
  return <span title={dupBadgeTitle(group, recordId)} style={DUP_BADGE_STYLE}>疑似重复</span>
}

/* 页码窗口：首尾 + 当前页 ±2，间隙以省略号折叠（1 2 3 4 5 … 11） */
function pageItems(page, totalPages) {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1)
  const want = new Set([1, totalPages, page - 2, page - 1, page, page + 1, page + 2])
  const sorted = [...want].filter((i) => i >= 1 && i <= totalPages).sort((a, b) => a - b)
  const items = []
  let prev = 0
  for (const i of sorted) {
    if (i - prev > 1) items.push('…')
    items.push(i)
    prev = i
  }
  return items
}

export function RecordsTable({ memory = {}, active = true, records, filterRecords = records, onRowClick, searchText = '', onResetFilters, externalFiltered = false, filterKey = '', onDeleteRecord, dupIndex = null, sources: allSources = [], onFilteredChange, forcedSource, forcedRecord, forcedField, toolbarExtra }) {
  const propertyLabel = usePropertyLabel()
  useEffect(() => { if (forcedField && memory.appliedField !== forcedField.seq) { memory.appliedField = forcedField.seq; setFieldFilter(forcedField.id); setSourceFilter('all'); setPage(1) } }, [forcedField])
  const [fieldFilter, setFieldFilter] = useRememberedState(memory, 'fieldFilter', 'all')
  const [sourceFilter, setSourceFilter] = useRememberedState(memory, 'sourceFilter', 'all')
  const [yearSort, setYearSort] = useRememberedState(memory, 'yearSort', 'none') // 'none' | 'desc' | 'asc'
  const [page, setPage] = useRememberedState(memory, 'page', 1)
  const [pageSize, setPageSize] = useRememberedState(memory, 'pageSize', 20)  // 用户重设计：默认 20 条/页
  const [menuFor, setMenuFor] = useState(null)  // 下拉菜单打开的 record_id
  useEffect(() => { if (forcedSource && memory.appliedSource !== forcedSource.seq) { memory.appliedSource = forcedSource.seq; setSourceFilter(forcedSource.id); setFieldFilter('all'); setPage(1) } }, [forcedSource])
  useEffect(() => { if (forcedRecord && memory.appliedRecord !== forcedRecord.seq) { memory.appliedRecord = forcedRecord.seq; setSourceFilter('all'); setFieldFilter('all'); setPage(1) } }, [forcedRecord])
  // 记录表格：横向溢出时鼠标滚轮左右滚动
  const tableScrollRef = useRef(null)
  const pageFeedback = usePageTransition()
  useWheelHorizontal(tableScrollRef)

  // 点击菜单外任意处关闭（2026-09-02：除再点三点外也能关闭）
  useEffect(() => {
    if (!menuFor) return
    const onDocClick = () => setMenuFor(null)
    document.addEventListener('click', onDocClick)
    return () => document.removeEventListener('click', onDocClick)
  }, [menuFor])

  const fields = useMemo(() => [...new Set(filterRecords.map((r) => r.field_name))], [filterRecords])
  const sources = useMemo(() => [...new Set(filterRecords.map((r) => r.source_id))], [filterRecords])
  const sourceMap = useMemo(() => new Map(allSources.map(source => [source.source_id, source])), [allSources])

  // 来源年份映射（优先读取 sources 接口中的 year 字段，兜底从 bibcode 中解析前四位年份）
  const sourceYearMap = useMemo(() => {
    const map = {}
    if (Array.isArray(allSources)) {
      for (const s of allSources) {
        if (s?.source_id && s.year) {
          map[s.source_id] = Number(s.year)
        }
      }
    }
    return map
  }, [allSources])

  const getRecordYear = (r) => {
    if (!r) return null
    if (sourceYearMap[r.source_id]) return sourceYearMap[r.source_id]
    if (typeof r.source_id === 'string') {
      const m = r.source_id.match(/^(\d{4})/)
      if (m) return parseInt(m[1], 10)
    }
    return null
  }

  const q = searchText.trim().toLowerCase()
  const previousSearch = useRef({ q, filterKey })
  useEffect(() => { if (previousSearch.current.q !== q || previousSearch.current.filterKey !== filterKey) { previousSearch.current = { q, filterKey }; setPage(1) } }, [q, filterKey])
  const hasFilters = !!q || fieldFilter !== 'all' || sourceFilter !== 'all' || externalFiltered
  const clearFilters = () => { setFieldFilter('all'); setSourceFilter('all'); setPage(1); onResetFilters?.() }
  const filtered = useMemo(() => records.filter(
    (r) =>
      (fieldFilter === 'all' || r.field_name === fieldFilter) &&
      (sourceFilter === 'all' || r.source_id === sourceFilter) &&
      matchesRecordSearch(r, q, sourceMap.get(r.source_id), propertyLabel)
  ), [records, fieldFilter, sourceFilter, q, sourceMap, propertyLabel])

  // 按来源年份排序（F3：支持无序、从新到旧最新优先、从旧到新早期优先）
  const sortedRows = useMemo(() => {
    if (yearSort === 'none') return filtered
    return [...filtered].sort((a, b) => {
      const yA = getRecordYear(a)
      const yB = getRecordYear(b)
      if (yA === yB) return 0
      if (yA == null) return 1  // 无年份记录靠后
      if (yB == null) return -1
      return yearSort === 'desc' ? yB - yA : yA - yB
    })
  }, [filtered, yearSort, sourceYearMap])

  const totalPages = Math.max(1, Math.ceil(sortedRows.length / pageSize))
  useEffect(() => { onFilteredChange?.(sortedRows) }, [sortedRows, onFilteredChange])
  // records 重拉后 totalPages 可能收缩（P0-2 兜底重拉翻页在末页时）——钳制当前页
  const cur = Math.min(page, totalPages)
  const pageRows = sortedRows.slice((cur - 1) * pageSize, cur * pageSize)
  const scrollKey = JSON.stringify([q, fieldFilter, sourceFilter, yearSort, filterKey, cur, pageSize])
  const previousScrollKey = useRef(scrollKey)
  const resetTablePosition = () => {
    const table = tableScrollRef.current
    if (!table) return
    table.scrollTop = 0
    memory.tableTop = 0
    const workbench = table.closest('.records-workbench')
    if (workbench && getComputedStyle(workbench).overflowY !== 'hidden') {
      const tableTop = table.getBoundingClientRect().top - workbench.getBoundingClientRect().top + workbench.scrollTop
      workbench.scrollTop = Math.min(workbench.scrollTop, Math.max(0, tableTop))
    }
  }
  useLayoutEffect(() => {
    if (!active || !tableScrollRef.current) return
    const changed = previousScrollKey.current !== scrollKey
    previousScrollKey.current = scrollKey
    if (changed) resetTablePosition()
    else tableScrollRef.current.scrollTop = memory.tableTop || 0
    tableScrollRef.current.scrollLeft = memory.tableLeft || 0
  }, [active, scrollKey])

  const resetPage = (fn) => (v) => { setPage(1); fn(v) }
  const goto = (p) => {
    const next = Math.min(totalPages, Math.max(1, p))
    if (next === cur) return
    pageFeedback(tableScrollRef.current, () => setPage(next))
    tableScrollRef.current?.focus({ preventScroll: true })
    resetTablePosition()
  }

  return (
    <div className="records-workspace">
      {/* 筛选与排序栏 */}
      <div className="filter-toolbar record-filters">
        {toolbarExtra}
        <select
          aria-label="按性质筛选"
          value={fieldFilter}
          onChange={(e) => resetPage(setFieldFilter)(e.target.value)}
          style={selectStyle}
        >
          <option value="all">全部性质 ({fields.length})</option>
          {fields.map((f) => <option key={f} value={f}>{propertyLabel(f)}</option>)}
        </select>
        <select
          aria-label="按来源筛选"
          title={sourceFilter === 'all' ? '按记录出处筛选' : sourceName(sourceMap.get(sourceFilter), sourceFilter)}
          value={sourceFilter}
          onChange={(e) => resetPage(setSourceFilter)(e.target.value)}
          style={selectStyle}
        >
          <option value="all">全部来源 ({sources.length})</option>
          {sources.map((s) => <option key={s} value={s} title={s}>{sourceName(sourceMap.get(s), s)}</option>)}
        </select>
        <select
          value={yearSort}
          onChange={(e) => resetPage(setYearSort)(e.target.value)}
          style={selectStyle}
          title="按文献来源发表年份排序"
        >
          <option value="none">来源年份：默认顺序</option>
          <option value="desc">来源年份：最新优先 (从新到旧)</option>
          <option value="asc">来源年份：早期优先 (从旧到新)</option>
        </select>
        {/* 页脚信息（右上，用户重设计：第 X–Y 条，共 N 条） */}
        {hasFilters && <Button className="clear-record-filters" variant="ghost" size="sm" onClick={clearFilters}>清除筛选</Button>}
        <span role="status" aria-live="polite" style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--content-fg-tertiary)' }}>
          第 {sortedRows.length ? (cur - 1) * pageSize + 1 : 0}–{Math.min(cur * pageSize, sortedRows.length)} 条，共 {sortedRows.length} 条
        </span>
      </div>

      {/* 表格（用户重设计：无外框，行分隔线 + hover 左侧绿条） */}
      <div ref={tableScrollRef} className="records-table-region" tabIndex={-1} aria-label="测量记录表格" onScroll={event => { if (active) { memory.tableTop = event.currentTarget.scrollTop; memory.tableLeft = event.currentTarget.scrollLeft } }}>
        <table className="records-table" style={{ width: '100%', minWidth: 760, borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--surface-secondary)' }}>
              {['实体', '性质', '值', '单位', '来源', '提取方式', ...(onDeleteRecord ? ['操作'] : [])].map((h) => {
                if (h === '来源') {
                  const sortIcon = yearSort === 'desc' ? ' ↓' : yearSort === 'asc' ? ' ↑' : ' ↕'
                  const sortTip = yearSort === 'none'
                    ? '点击按来源年份降序排序（最新优先）'
                    : yearSort === 'desc'
                    ? '当前最新优先，点击切换为早期优先'
                    : '当前早期优先，点击恢复默认排序'
                  const toggleSort = () => {
                    setPage(1)
                    setYearSort((curr) => (curr === 'none' ? 'desc' : curr === 'desc' ? 'asc' : 'none'))
                  }
                  return (
                    <th
                      key={h}
                      aria-sort={yearSort === 'asc' ? 'ascending' : yearSort === 'desc' ? 'descending' : 'none'}
                      title={sortTip}
                      style={{
                        textAlign: 'left', padding: '10px 12px', fontWeight: 510,
                        color: yearSort !== 'none' ? 'var(--accent)' : 'var(--content-fg-tertiary)',
                        fontSize: 12, whiteSpace: 'nowrap', cursor: 'pointer',
                        userSelect: 'none',
                      }}
                    >
                      <button className="table-sort" onClick={toggleSort} aria-label={sortTip}>来源{sortIcon}</button>
                    </th>
                  )
                }
                return (
                  <th key={h} style={{ textAlign: 'left', padding: '10px 12px', fontWeight: 510, color: 'var(--content-fg-tertiary)', fontSize: 12, whiteSpace: 'nowrap' }}>
                    {h}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody data-page-content>
            {!pageRows.length && <tr><td colSpan={onDeleteRecord ? 7 : 6} className="records-no-match"><p>没有找到符合当前条件的记录</p>{hasFilters && <Button variant="outline" size="sm" onClick={clearFilters}>清除筛选，查看全部记录</Button>}</td></tr>}
            {pageRows.map((r) => {
              const rowDup = dupIndex?.byRecordId?.[r.record_id] || null
              // 仅非代表成员行追加徽标；组散（现存成员 <2）后不再标注
              const showDupBadge = !!rowDup && !rowDup.isRepresentative && rowDup.group.liveCount >= 2
              return (
              <tr
                key={r.record_id}
                className="record-row"
                onClick={event => {
                  const sel = window.getSelection()
                  if (sel && sel.toString().trim().length > 0) return
                  event.currentTarget.focus({ preventScroll: true })
                  onRowClick?.(r)
                }}
                title="点击查看该记录的来源与处理详情"
                style={{ borderTop: '1px solid var(--surface-border-subtle)', cursor: 'pointer' }}
                tabIndex={0}
                onKeyDown={event => { if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onRowClick?.(r) } }}
              >
                <td style={tdStyle}>{r.entity_name}</td>
                <td style={{ ...tdStyle, fontFamily: 'inherit', fontWeight: 510 }} title={r.field_name}>{propertyLabel(r.field_name)}</td>
                {/* 用户重设计：值列左对齐等宽 */}
                <td style={{ ...tdStyle, fontFamily: MONO, textAlign: 'left' }}>
                  {r.field_value}
                  {showDupBadge && <DupBadge group={rowDup.group} recordId={r.record_id} />}
                </td>
                <td style={{ ...tdStyle, color: 'var(--content-fg-secondary)' }}>{r.field_unit}</td>
                <td style={{ ...tdStyle, color: 'var(--content-fg-secondary)', fontSize: 12 }}>
                  {/* 用户重设计：期刊缩写+年份（完整 bibcode 见 title） */}
                  <span className="record-source-cell" title={sourceName(sourceMap.get(r.source_id), r.source_id)}>
                    <Icon.FileText style={{ width: 11, height: 11, flexShrink: 0, color: 'var(--content-fg-tertiary)' }} />
                    <span>{sourceName(sourceMap.get(r.source_id), r.source_id, true)}</span>
                  </span>
                </td>
                <td style={{ ...tdStyle, fontSize: 12 }}>
                  <MethodBadge method={r.extraction_method} />
                </td>
                {onDeleteRecord && <td style={{ ...tdStyle, width: 32, color: 'var(--content-fg-tertiary)', textAlign: 'center' }}>
                  {/* 操作列：… 点击弹出下拉菜单（查看详情 / 删除）；菜单关闭即收起（2026-09-02）
                      readOnly（样例本体）不渲染入口——记录只读 */}
                  {onDeleteRecord && (
                  <div style={{ position: 'relative', display: 'inline-block' }}>
                    <button
                      onClick={(e) => { e.stopPropagation(); setMenuFor(menuFor === r.record_id ? null : r.record_id) }}
                      title="操作"
                      style={{ border: 'none', background: menuFor === r.record_id ? 'var(--surface-secondary)' : 'transparent', cursor: 'pointer', color: 'var(--content-fg-tertiary)', padding: 2, display: 'flex', borderRadius: 4 }}
                    >
                      <Icon.Ellipsis style={{ width: 14, height: 14 }} />
                    </button>
                    {menuFor === r.record_id && (
                      <div
                        onClick={(e) => e.stopPropagation()}
                        style={{
                          position: 'absolute', right: 0, top: '100%', zIndex: 30, minWidth: 110,
                          background: 'var(--surface-bg)', border: '1px solid var(--surface-border)',
                          borderRadius: 8, padding: 4, boxShadow: '0 6px 20px rgba(0,0,0,.18)',
                        }}
                      >
                        <button
                          onClick={(e) => { e.stopPropagation(); setMenuFor(null); onDeleteRecord?.(r) }}
                          style={{ ...menuItemStyle, color: 'var(--status-error)' }}
                        >
                          删除
                        </button>
                      </div>
                    )}
                  </div>
                  )}
                </td>}
              </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* 分页条（用户重设计：‹ 上一页 | 页码窗口 | 下一页 › | 每页显示 N 条） */}
      <div className="records-pagination" style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
        <button className="pager-btn" style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '0 10px' }} disabled={cur <= 1} onClick={() => goto(cur - 1)}>
          <Icon.ChevronLeft style={{ width: 11, height: 11 }} />上一页
        </button>
        {pageItems(cur, totalPages).map((it, idx) =>
          it === '…' ? (
            <span key={`gap-${idx}`} style={{ padding: '0 4px', fontSize: 12, color: 'var(--content-fg-tertiary)' }}>…</span>
          ) : (
            <button key={it} aria-current={it === cur ? 'page' : undefined} title={`第 ${it} 页`} className={`pager-btn${it === cur ? ' active' : ''}`} onClick={() => goto(it)}>{it}</button>
          )
        )}
        <button className="pager-btn" style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '0 10px' }} disabled={cur >= totalPages} onClick={() => goto(cur + 1)}>
          下一页 <Icon.ChevronRight style={{ width: 11, height: 11 }} />
        </button>
        <span style={{ flex: 1 }} />
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--content-fg-tertiary)' }}>
          每页显示
          <select
            aria-label="每页记录数"
            value={pageSize}
            onChange={(e) => { setPage(1); setPageSize(Number(e.target.value)) }}
            style={{ ...selectStyle, padding: '4px 8px', fontSize: 12, borderRadius: 6 }}
          >
            {PAGE_SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          条
        </span>
      </div>
    </div>
  )
}

/* 表格工具图标按钮（用户重设计：朴素小方块；hover 浅底） */
function ToolBtn({ icon, title, onClick, active }) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="active-press"
      style={{
        width: 30, height: 30, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        border: 'none', borderRadius: 6, background: active ? 'var(--sidebar-hover)' : 'transparent',
        cursor: onClick ? 'pointer' : 'default',
        color: active ? 'var(--accent-text)' : 'var(--content-fg-secondary)',
        padding: 0,
        transition: 'background-color 0.14s ease, transform 0.12s ease',
      }}
    >
      {icon}
    </button>
  )
}

const selectStyle = {
  padding: '8px 12px',
  fontSize: 13,
  border: '1px solid var(--surface-border)',
  borderRadius: 8,
  background: 'var(--surface-bg)',
  color: 'var(--content-fg)',
  outline: 'none',
}

/* 操作下拉菜单条目（2026-09-02） */
const menuItemStyle = {
  display: 'flex', alignItems: 'center', width: '100%',
  padding: '7px 10px', fontSize: 12.5, textAlign: 'left',
  border: 'none', borderRadius: 6, cursor: 'pointer',
  background: 'transparent', color: 'var(--content-fg-secondary)',
}

const tdStyle = {
  padding: '9px 12px',
  borderTop: '1px solid var(--surface-border-subtle)',
  userSelect: 'text',
  WebkitUserSelect: 'text',
}

export function SourcesList({ sources, onOpenSource }) {
  const [typeFilter, setTypeFilter] = useState('all')
  const [page, setPage] = useState(1)
  const current = Math.min(page, Math.max(1, Math.ceil((typeFilter === 'all' ? sources : sources.filter(source => sourceType(source.source_type) === typeFilter)).length / 20)))
  const types = [...new Set(['database', 'paper', 'supplement', ...sources.map(source => sourceType(source.source_type)).filter(Boolean)])]
  // 2026-08-13：字段名修正 s.type → s.source_type（后端契约字段，此前分类计数恒 0）
  const filtered = typeFilter === 'all' ? sources : sources.filter((s) => sourceType(s.source_type) === typeFilter)
  const typeLabel = SOURCE_TYPES

  return (
    <div data-page-region>
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        <FilterChip active={typeFilter === 'all'} onClick={() => { setTypeFilter('all'); setPage(1) }}>全部（{sources.length}）</FilterChip>
        {types.map((t) => (
          <FilterChip key={t} active={typeFilter === t} onClick={() => { setTypeFilter(t); setPage(1) }}>
            {typeLabel[t] || t}（{sources.filter((s) => sourceType(s.source_type) === t).length}）
          </FilterChip>
        ))}
      </div>
      <div data-page-content style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {filtered.slice((current - 1) * 20, current * 20).map((s) => (
          <div key={s.source_id} style={{ border: '1px solid var(--surface-border-subtle)', borderRadius: 8, padding: '10px 14px', background: 'var(--surface-bg)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button className="source-title" onClick={() => onOpenSource?.(s)} title={s.title}>{s.title || s.source_id}</button>
              <span style={{ flexShrink: 0, fontSize: 11, padding: '1px 8px', borderRadius: 8, background: 'var(--surface-secondary)', color: 'var(--content-fg-secondary)' }}>
                {typeLabel[s.source_type] || s.source_type}
              </span>
            </div>
            <div style={{ fontSize: 13, color: 'var(--content-fg-secondary)', marginTop: 8 }}>
              {sourceName(s, s.source_id, true)}
            </div>
          </div>
        ))}
      </div>
      <Pagination total={filtered.length} page={current} onPage={setPage} />
    </div>
  )
}

function FilterChip({ active, onClick, children }) {
  return (
    <button onClick={onClick} className={`filter-chip${active ? ' active' : ''}`}>
      {children}
    </button>
  )
}

/* 输出文件区（契约 D9：本地路径导向，无下载语义；复制路径 / 打开） */
export function OutputFiles({ files, taskId }) {
  const { toast } = useToast()

  const copyPath = async (path) => {
    try {
      await navigator.clipboard.writeText(path)
      toast('路径已复制', 'success')
    } catch {
      toast('复制失败，请手动选择', 'error')
    }
  }

  // L-13：契约 D9-3 真实端点（后端 os.startfile 打开本地文件）
  const openFile = async (name) => {
    if (!taskId) {
      toast('任务未就绪，无法打开文件', 'error')
      return
    }
    try {
      await api.openFile(taskId, name)
      toast(`已在本地打开 ${name}`, 'success')
    } catch (err) {
      toast(`打开失败：${err.message}`, 'error')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {files.map((f) => (
        <div key={f.name} style={{ border: '1px solid var(--surface-border-subtle)', borderRadius: 8, padding: '10px 12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 30, height: 30, borderRadius: 6, background: 'var(--surface-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--content-fg-tertiary)', flexShrink: 0 }}>
              <Icon.FileText style={{ width: 14, height: 14 }} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="font-mono" style={{ fontSize: 12, fontWeight: 510, color: 'var(--content-fg)' }}>{f.name}</div>
              <div style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginTop: 2 }}>{f.desc} · {f.size}</div>
            </div>
            <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 8, background: 'var(--surface-secondary)', color: 'var(--content-fg-secondary)', flexShrink: 0 }}>{f.format}</span>
          </div>
          {/* 本地路径 */}
          <div className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginTop: 6, wordBreak: 'break-all', lineHeight: 1.5 }}>{f.path}</div>
          <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
            <Button asChild variant="outline" size="sm"><a href={api.exportFileUrl(taskId, f.name)} download>下载文件</a></Button>
            <Button variant="outline" size="sm" onClick={() => copyPath(f.path)}>复制路径</Button>
            <Button variant="outline" size="sm" onClick={() => openFile(f.name)}>打开</Button>
          </div>
        </div>
      ))}
    </div>
  )
}

/* 主区记录表格容器（契约 D7-1：主区只放表格，全宽；数据走 HTTP 接口）
 * 点击行 → 记录详情弹窗：血缘数据（quality/sources）首次点开时惰性加载并缓存 */
