import { useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useToast } from '@/components/ui/toast'
import RecordDetailDialog from './RecordDetail'
import ExportDialog from './ExportDialog'
import * as api from '@/services/api'
import { useWheelHorizontal } from '@/hooks/useWheelHorizontal'
import { journalLabel } from '@/lib/journal'

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
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 510,
    display: 'inline-block',
  }
  if (!vlm) {
    return <span style={{ ...style, background: 'var(--surface-secondary)', color: 'var(--content-fg-secondary)' }}>数据库</span>
  }
  if (m === 'vlm_table') {
    return <span style={{ ...style, background: 'var(--status-success-bg)', color: 'var(--status-success)' }}>VLM 表格</span>
  }
  // vlm_text / vlm 及未知 vlm 变体 → 文本类（蓝）
  return <span style={{ ...style, background: 'var(--status-progress-bg)', color: 'var(--status-progress)' }}>VLM 文本</span>
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

export function RecordsTable({ records, onRowClick, searchText = '', onDeleteRecord }) {
  const [fieldFilter, setFieldFilter] = useState('all')
  const [sourceFilter, setSourceFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)  // 用户重设计：默认 20 条/页
  const [menuFor, setMenuFor] = useState(null)  // 下拉菜单打开的 record_id
  // 记录表格：横向溢出时鼠标滚轮左右滚动
  const tableScrollRef = useRef(null)
  useWheelHorizontal(tableScrollRef)

  // 点击菜单外任意处关闭（2026-09-02：除再点三点外也能关闭）
  useEffect(() => {
    if (!menuFor) return
    const onDocClick = () => setMenuFor(null)
    document.addEventListener('click', onDocClick)
    return () => document.removeEventListener('click', onDocClick)
  }, [menuFor])

  const fields = useMemo(() => [...new Set(records.map((r) => r.field_name))], [records])
  const sources = useMemo(() => [...new Set(records.map((r) => r.source_id))], [records])

  const q = searchText.trim().toLowerCase()
  const filtered = records.filter(
    (r) =>
      (fieldFilter === 'all' || r.field_name === fieldFilter) &&
      (sourceFilter === 'all' || r.source_id === sourceFilter) &&
      (!q || [r.entity_name, r.field_name, r.field_value, r.source_id].some((v) => String(v ?? '').toLowerCase().includes(q)))
  )
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  // records 重拉后 totalPages 可能收缩（P0-2 兜底重拉翻页在末页时）——钳制当前页
  const cur = Math.min(page, totalPages)
  const pageRows = filtered.slice((cur - 1) * pageSize, cur * pageSize)

  const resetPage = (fn) => (v) => { setPage(1); fn(v) }
  const goto = (p) => setPage(Math.min(totalPages, Math.max(1, p)))

  return (
    <div>
      {/* 筛选栏 */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
        <select
          value={fieldFilter}
          onChange={(e) => resetPage(setFieldFilter)(e.target.value)}
          style={selectStyle}
        >
          <option value="all">全部性质 ({fields.length})</option>
          {fields.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
        <select
          value={sourceFilter}
          onChange={(e) => resetPage(setSourceFilter)(e.target.value)}
          style={selectStyle}
        >
          <option value="all">全部来源 ({sources.length})</option>
          {sources.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {/* 页脚信息（右上，用户重设计：第 X–Y 条，共 N 条） */}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--content-fg-tertiary)' }}>
          第 {filtered.length ? (cur - 1) * pageSize + 1 : 0}–{Math.min(cur * pageSize, filtered.length)} 条，共 {filtered.length} 条
        </span>
      </div>

      {/* 表格（用户重设计：无外框，行分隔线 + hover 左侧绿条） */}
      <div ref={tableScrollRef} style={{ borderRadius: 8, overflowX: 'auto' }}>
        <table style={{ width: '100%', minWidth: 760, borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--surface-secondary)' }}>
              {['实体', '性质', '值', '单位', '来源', '提取方式', '操作'].map((h) => (
                <th key={h} style={{ textAlign: 'left', padding: '10px 12px', fontWeight: 510, color: 'var(--content-fg-tertiary)', fontSize: 12, whiteSpace: 'nowrap' }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r) => (
              <tr
                key={r.record_id}
                className="record-row"
                onClick={() => onRowClick?.(r)}
                title="点击查看该记录的来源与处理详情"
                style={{ borderTop: '1px solid var(--surface-border-subtle)', cursor: 'pointer' }}
              >
                <td style={tdStyle}>{r.entity_name}</td>
                <td style={{ ...tdStyle, fontFamily: MONO, fontWeight: 510 }}>{r.field_name}</td>
                {/* 用户重设计：值列左对齐等宽 */}
                <td style={{ ...tdStyle, fontFamily: MONO, textAlign: 'left' }}>{r.field_value}</td>
                <td style={{ ...tdStyle, color: 'var(--content-fg-secondary)' }}>{r.field_unit}</td>
                <td style={{ ...tdStyle, color: 'var(--content-fg-secondary)', fontSize: 12 }}>
                  {/* 用户重设计：期刊缩写+年份（完整 bibcode 见 title） */}
                  <span title={r.source_id} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                    <Icon.FileText style={{ width: 11, height: 11, flexShrink: 0, color: 'var(--content-fg-tertiary)' }} />
                    <span className="font-mono" style={{ fontSize: 11 }}>{journalLabel(r.source_id)}</span>
                  </span>
                </td>
                <td style={{ ...tdStyle, fontSize: 12 }}>
                  <MethodBadge method={r.extraction_method} />
                </td>
                <td style={{ ...tdStyle, width: 32, color: 'var(--content-fg-tertiary)', textAlign: 'center' }}>
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
                          background: '#ffffff', border: '1px solid #e5e7eb',
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
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 分页条（用户重设计：‹ 上一页 | 页码窗口 | 下一页 › | 每页显示 N 条） */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
        <button className="pager-btn" style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '0 10px' }} disabled={cur <= 1} onClick={() => goto(cur - 1)}>
          <Icon.ChevronLeft style={{ width: 11, height: 11 }} />上一页
        </button>
        {pageItems(cur, totalPages).map((it, idx) =>
          it === '…' ? (
            <span key={`gap-${idx}`} style={{ padding: '0 4px', fontSize: 12, color: 'var(--content-fg-tertiary)' }}>…</span>
          ) : (
            <button key={it} className={`pager-btn${it === cur ? ' active' : ''}`} onClick={() => goto(it)}>{it}</button>
          )
        )}
        <button className="pager-btn" style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '0 10px' }} disabled={cur >= totalPages} onClick={() => goto(cur + 1)}>
          下一页 <Icon.ChevronRight style={{ width: 11, height: 11 }} />
        </button>
        <span style={{ flex: 1 }} />
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--content-fg-tertiary)' }}>
          每页显示
          <select
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
      style={{
        width: 30, height: 30, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        border: 'none', borderRadius: 6, background: active ? 'var(--sidebar-hover)' : 'transparent',
        cursor: onClick ? 'pointer' : 'default',
        color: active ? 'var(--accent-text)' : 'var(--content-fg-secondary)',
        padding: 0,
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

const tdStyle = { padding: '11px 12px', borderTop: '1px solid var(--surface-border-subtle)' }

export function SourcesList({ sources }) {
  const [typeFilter, setTypeFilter] = useState('all')
  const types = ['database', 'paper', 'supplementary']
  // 2026-08-13：字段名修正 s.type → s.source_type（后端契约字段，此前分类计数恒 0）
  const filtered = typeFilter === 'all' ? sources : sources.filter((s) => s.source_type === typeFilter)
  const typeLabel = { database: '数据库', paper: '论文', supplementary: '补充材料' }

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
        <FilterChip active={typeFilter === 'all'} onClick={() => setTypeFilter('all')}>全部（{sources.length}）</FilterChip>
        {types.map((t) => (
          <FilterChip key={t} active={typeFilter === t} onClick={() => setTypeFilter(t)}>
            {typeLabel[t]}（{sources.filter((s) => s.source_type === t).length}）
          </FilterChip>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {filtered.map((s) => (
          <div key={s.source_id} style={{ border: '1px solid var(--surface-border-subtle)', borderRadius: 8, padding: '10px 14px', background: 'var(--surface-bg)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={s.title}>
                {s.title}
              </span>
              <span style={{ flexShrink: 0, fontSize: 11, padding: '1px 8px', borderRadius: 4, background: 'var(--surface-secondary)', color: 'var(--content-fg-secondary)' }}>
                {typeLabel[s.source_type] || s.source_type}
              </span>
            </div>
            <div className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginTop: 4 }}>
              {s.source_id}{s.doi ? ` · ${s.doi}` : ''}{s.year ? ` · ${s.year}` : ''}{s.priority ? ` · 优先级 ${s.priority}` : ''}
            </div>
          </div>
        ))}
      </div>
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
            <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: 'var(--surface-secondary)', color: 'var(--content-fg-secondary)', flexShrink: 0 }}>{f.format}</span>
          </div>
          {/* 本地路径 */}
          <div className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginTop: 6, wordBreak: 'break-all', lineHeight: 1.5 }}>{f.path}</div>
          <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
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
export default function ResultTabs({ taskId, status, readOnly = false }) {
  // readOnly（2026-09-02）：演示样例本体——记录级删除不可用（后端 403 守卫，
  // 此处隐藏操作入口；回放副本与普通任务不受限）
  const { toast } = useToast()
  const [records, setRecords] = useState(null)
  const [detail, setDetail] = useState(null)          // 当前查看的记录
  const [quality, setQuality] = useState(null)        // GET /quality（血缘/轨迹/洞察）
  const [sources, setSources] = useState([])          // GET /sources（来源标题）
  const [detailLoading, setDetailLoading] = useState(false)
  const lineageLoaded = useRef(false)
  // 2026-09-02 用户重设计：搜索留在表格内；导出改专门弹窗（ExportDialog）
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [exportOpen, setExportOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)  // 待确认删除的记录
  const searchRef = useRef(null)

  const openSearch = () => {
    setSearchOpen((v) => !v)
    if (!searchOpen) setTimeout(() => searchRef.current?.focus(), 30)
  }

  // 记录删除（2026-09-02：不可逆，走 DELETE /records/{id}；确认弹窗后执行）
  const confirmDelete = async () => {
    const target = deleteTarget
    setDeleteTarget(null)
    if (!target || !taskId) return
    try {
      const r = await api.deleteRecord(taskId, target.record_id)
      toast(`已删除记录（剩余 ${r.remaining} 条）`, 'success')
      setRecords((prev) => (Array.isArray(prev) ? prev.filter((x) => x.record_id !== target.record_id) : prev))
    } catch (err) {
      toast(`删除失败：${err.message}`, 'error')
    }
  }

  useEffect(() => {
    if (!taskId) return
    let alive = true
    api.getRecords(taskId).then((r) => alive && setRecords(r || []))
    return () => { alive = false }
  }, [taskId])

  // P0-2：done 卡完成（挂载）先于 final_output 落库 → 首拉可能拿到空数组且永不重拉。
  // status 变为 completed 且 records 为空时延迟 600ms 重拉一次（alive 由 timer 清理保证）
  useEffect(() => {
    if (!taskId || status !== 'completed') return
    if (records && records.length > 0) return
    const timer = setTimeout(() => {
      api.getRecords(taskId).then((r) => setRecords((prev) => (Array.isArray(r) && r.length ? r : prev)))
    }, 600)
    return () => clearTimeout(timer)
  }, [taskId, status])

  // 任务切换时重置血缘缓存
  useEffect(() => {
    lineageLoaded.current = false
    setQuality(null)
    setSources([])
    setDetail(null)
  }, [taskId])

  const openDetail = (rec) => {
    setDetail(rec)
    if (lineageLoaded.current || !taskId) return
    lineageLoaded.current = true
    setDetailLoading(true)
    Promise.all([
      api.getQuality(taskId).catch(() => null),
      api.getSources(taskId).catch(() => []),
    ]).then(([q, s]) => {
      setQuality(q)
      setSources(Array.isArray(s) ? s : [])
    }).finally(() => setDetailLoading(false))
  }

  const total = records ? records.length : 0

  return (
    <div style={{ border: '1px solid var(--surface-border)', borderRadius: 10, background: 'var(--surface-bg)', overflow: 'hidden', marginBottom: 8 }}>
      {/* 头部（用户重设计：标题左 + 工具图标按钮右：搜索/筛选/下载/表格视图） */}
      <div style={{ display: 'flex', alignItems: 'center', padding: '10px 16px', borderBottom: '1px solid var(--surface-border)', gap: 8 }}>
        <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--content-fg)' }}>记录表格</span>
        <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
          {records === null ? '加载中…' : `${total} 条记录`}
        </span>
        <span style={{ flex: 1 }} />
        <ToolBtn icon={<Icon.Search />} title={searchOpen ? '收起搜索' : '搜索记录'} onClick={openSearch} active={searchOpen} />
        {/* 2026-09-02：导出按钮打开专门导出窗口（清理了两个无功能摆设按钮：筛选/表格视图） */}
        <ToolBtn icon={<Icon.Download />} title="导出数据（筛选/剔除后导出）" onClick={() => setExportOpen(true)} />
      </div>
      {/* 搜索输入行（点击搜索图标展开） */}
      {searchOpen && (
        <div style={{ padding: '10px 16px 0' }}>
          <input
            ref={searchRef}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="搜索实体 / 性质 / 值 / 来源…"
            style={{
              width: '100%', padding: '8px 12px', fontSize: 13, borderRadius: 8,
              border: '1px solid var(--surface-border)', background: 'var(--surface-bg)',
              color: 'var(--content-fg)', outline: 'none',
            }}
          />
        </div>
      )}
      <div style={{ padding: 16 }}>
        {records === null ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '6px 0' }}>
            {[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: 30 }} />)}
            <div style={{ textAlign: 'center', fontSize: 'var(--fs-sm)', color: 'var(--content-fg-tertiary)', paddingTop: 4 }}>加载记录…</div>
          </div>
        ) : records.length === 0 ? (
          <div className="empty-state" style={{ padding: '24px 16px' }}>
            <span style={{ fontSize: 'var(--fs-sm)' }}>本次任务未产生记录</span>
          </div>
        ) : (
          <RecordsTable records={records} onRowClick={openDetail} searchText={searchText} onDeleteRecord={readOnly ? undefined : setDeleteTarget} />
        )}
      </div>

      {/* 记录详情弹窗 */}
      {detail && (
        <RecordDetailDialog
          record={detail}
          quality={quality}
          sources={sources}
          loading={detailLoading}
          onClose={() => setDetail(null)}
        />
      )}

      {/* 导出窗口（2026-09-02 用户重设计：专门弹窗，与主表浏览分离） */}
      {exportOpen && (
        <ExportDialog
          open={exportOpen}
          taskId={taskId}
          records={records || []}
          onClose={() => setExportOpen(false)}
        />
      )}

      {/* 记录删除确认（不可逆，必须确认）——纯白不透明（2026-09-02） */}
      {deleteTarget && (
        <div className="animate-fade-in" style={{ position: 'fixed', inset: 0, zIndex: 220, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div onClick={() => setDeleteTarget(null)} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,.45)' }} />
          <div style={{ position: 'relative', width: 380, background: '#ffffff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 18, boxShadow: '0 20px 48px rgba(0,0,0,.3)', color: '#1f2937' }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>删除这条记录？</div>
            <div style={{ fontSize: 12.5, color: '#4b5563', lineHeight: 1.6, marginBottom: 14 }}>
              <span className="font-mono" style={{ color: 'var(--status-error)', fontWeight: 600 }}>{deleteTarget.field_name} = {deleteTarget.field_value} {deleteTarget.field_unit}</span>
              <br />删除后不可恢复，回放/重新导出将不再包含此记录。
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <Button variant="outline" size="sm" onClick={() => setDeleteTarget(null)} style={{ color: '#1f2937', borderColor: '#d1d5db', background: '#ffffff' }}>取消</Button>
              <Button variant="destructive" size="sm" onClick={confirmDelete}>确认删除</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
