import { useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useToast } from '@/components/ui/toast'
import RecordDetailDialog from './RecordDetail'
import * as api from '@/services/api'

/* 结果组件库（契约 D7-1：主区只留记录表格；来源/质量/下载移右侧面板）
 * 导出：RecordsTable（主区全宽）/ SourcesList / OutputFiles（右侧面板）
 */

const PAGE_SIZE = 15

export function RecordsTable({ records, onRowClick }) {
  const [fieldFilter, setFieldFilter] = useState('all')
  const [sourceFilter, setSourceFilter] = useState('all')
  const [page, setPage] = useState(1)

  const fields = useMemo(() => [...new Set(records.map((r) => r.field_name))], [records])
  const sources = useMemo(() => [...new Set(records.map((r) => r.source_id))], [records])

  const filtered = records.filter(
    (r) =>
      (fieldFilter === 'all' || r.field_name === fieldFilter) &&
      (sourceFilter === 'all' || r.source_id === sourceFilter)
  )
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const resetPage = (fn) => (v) => { setPage(1); fn(v) }

  return (
    <div>
      {/* 筛选栏 */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <select
          value={fieldFilter}
          onChange={(e) => resetPage(setFieldFilter)(e.target.value)}
          style={selectStyle}
        >
          <option value="all">全部性质（{fields.length}）</option>
          {fields.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
        <select
          value={sourceFilter}
          onChange={(e) => resetPage(setSourceFilter)(e.target.value)}
          style={selectStyle}
        >
          <option value="all">全部来源（{sources.length}）</option>
          {sources.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <span style={{ fontSize: 12, color: 'var(--content-fg-tertiary)', marginLeft: 'auto' }}>
          共 {filtered.length} 条 · 第 {page}/{totalPages} 页
        </span>
      </div>

      {/* 表格 */}
      <div style={{ border: '1px solid var(--surface-border)', borderRadius: 8, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--surface-secondary)' }}>
              {['实体', '性质', '值', '单位', '来源', '提取方式'].map((h) => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 12px', fontWeight: 510, color: 'var(--content-fg-tertiary)', fontSize: 12, whiteSpace: 'nowrap' }}>
                  {h}
                </th>
              ))}
              <th style={{ width: 32 }} />
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
                <td style={{ ...tdStyle, fontWeight: 510 }}>{r.field_name}</td>
                {/* P1-8：数值列右对齐（视觉审查反馈） */}
                <td style={{ ...tdStyle, fontFamily: 'ui-monospace, Menlo, Consolas, monospace', textAlign: 'right' }}>{r.field_value}</td>
                <td style={{ ...tdStyle, color: 'var(--content-fg-secondary)' }}>{r.field_unit}</td>
                <td style={{ ...tdStyle, color: 'var(--content-fg-secondary)', fontSize: 12 }}>
                  <span className="font-mono" style={{ fontSize: 11 }}>{r.source_id}</span>
                </td>
                <td style={{ ...tdStyle, fontSize: 12 }}>
                  {(() => {
                    const isVlm = typeof r.extraction_method === 'string' && r.extraction_method.startsWith('vlm')
                    return (
                      <span
                        style={{
                          padding: '1px 8px',
                          borderRadius: 4,
                          fontSize: 11,
                          background: isVlm ? 'var(--status-progress-bg)' : 'var(--surface-secondary)',
                          color: isVlm ? 'var(--status-progress)' : 'var(--content-fg-secondary)',
                        }}
                      >
                        {isVlm ? (
                          r.extraction_method === 'vlm_table' ? 'VLM 表格'
                            : r.extraction_method === 'vlm_text' ? 'VLM 文本'
                              : 'VLM'
                        ) : '数据库'}
                      </span>
                    )
                  })()}
                </td>
                <td style={{ ...tdStyle, width: 32, color: 'var(--content-fg-tertiary)', textAlign: 'center' }}>
                  <Icon.ChevronRight style={{ width: 12, height: 12 }} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 分页 */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 12 }}>
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button>
        <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>下一页</Button>
      </div>
    </div>
  )
}

const selectStyle = {
  padding: '6px 10px',
  fontSize: 13,
  border: '1px solid var(--surface-border)',
  borderRadius: 6,
  background: 'var(--surface-bg)',
  color: 'var(--content-fg)',
  outline: 'none',
}

const tdStyle = { padding: '7px 12px', borderTop: '1px solid var(--surface-border-subtle)' }

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
              <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>{s.title}</span>
              <span style={{ marginLeft: 'auto', fontSize: 11, padding: '1px 8px', borderRadius: 4, background: 'var(--surface-secondary)', color: 'var(--content-fg-secondary)' }}>
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
export default function ResultTabs({ taskId, status }) {
  const [records, setRecords] = useState(null)
  const [detail, setDetail] = useState(null)          // 当前查看的记录
  const [quality, setQuality] = useState(null)        // GET /quality（血缘/轨迹/洞察）
  const [sources, setSources] = useState([])          // GET /sources（来源标题）
  const [detailLoading, setDetailLoading] = useState(false)
  const lineageLoaded = useRef(false)

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
      {/* 头部 */}
      <div style={{ display: 'flex', alignItems: 'center', padding: '10px 16px', borderBottom: '1px solid var(--surface-border)', gap: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>记录表格</span>
        <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
          {records === null ? '加载中…' : `${total} 条 · 点击行查看来源与处理详情`}
        </span>
      </div>
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
          <RecordsTable records={records} onRowClick={openDetail} />
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
    </div>
  )
}
