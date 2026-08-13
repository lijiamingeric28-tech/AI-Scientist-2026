import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useToast } from '@/components/ui/toast'
import * as api from '@/services/api'

/* 结果组件库（契约 D7-1：主区只留记录表格；来源/质量/下载移右侧面板）
 * 导出：RecordsTable（主区全宽）/ SourcesList / OutputFiles（右侧面板）
 */

const PAGE_SIZE = 15

export function RecordsTable({ records }) {
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
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r) => (
              <tr key={r.record_id} style={{ borderTop: '1px solid var(--surface-border-subtle)' }}>
                <td style={tdStyle}>{r.entity_name}</td>
                <td style={{ ...tdStyle, fontWeight: 510 }}>{r.field_name}</td>
                <td style={{ ...tdStyle, fontFamily: 'ui-monospace, Menlo, Consolas, monospace' }}>{r.field_value}</td>
                <td style={{ ...tdStyle, color: 'var(--content-fg-secondary)' }}>{r.field_unit}</td>
                <td style={{ ...tdStyle, color: 'var(--content-fg-secondary)', fontSize: 12 }}>
                  <span className="font-mono" style={{ fontSize: 11 }}>{r.source_id}</span>
                </td>
                <td style={{ ...tdStyle, fontSize: 12 }}>
                  <span
                    style={{
                      padding: '1px 8px',
                      borderRadius: 4,
                      fontSize: 11,
                      background: r.extraction_method === 'vlm_extraction' ? 'var(--status-progress-bg)' : 'var(--surface-secondary)',
                      color: r.extraction_method === 'vlm_extraction' ? 'var(--status-progress)' : 'var(--content-fg-secondary)',
                    }}
                  >
                    {r.extraction_method === 'vlm_extraction' ? 'VLM' : '数据库'}
                  </span>
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
  const filtered = typeFilter === 'all' ? sources : sources.filter((s) => s.type === typeFilter)
  const typeLabel = { database: '数据库', paper: '论文', supplementary: '补充材料' }

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
        <FilterChip active={typeFilter === 'all'} onClick={() => setTypeFilter('all')}>全部（{sources.length}）</FilterChip>
        {types.map((t) => (
          <FilterChip key={t} active={typeFilter === t} onClick={() => setTypeFilter(t)}>
            {typeLabel[t]}（{sources.filter((s) => s.type === t).length}）
          </FilterChip>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {filtered.map((s) => (
          <div key={s.source_id} style={{ border: '1px solid var(--surface-border-subtle)', borderRadius: 8, padding: '10px 14px', background: 'var(--surface-bg)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>{s.title}</span>
              <span style={{ marginLeft: 'auto', fontSize: 11, padding: '1px 8px', borderRadius: 4, background: 'var(--surface-secondary)', color: 'var(--content-fg-secondary)' }}>
                {typeLabel[s.type] || s.type}
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
    <button
      onClick={onClick}
      style={{
        padding: '4px 12px',
        fontSize: 12,
        borderRadius: 20,
        border: '1px solid var(--surface-border)',
        cursor: 'pointer',
        background: active ? 'var(--accent-light)' : 'var(--surface-bg)',
        color: active ? 'var(--accent-text)' : 'var(--content-fg-secondary)',
        fontWeight: active ? 510 : 400,
      }}
    >
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

/* 主区记录表格容器（契约 D7-1：主区只放表格，全宽；数据走 HTTP 接口） */
export default function ResultTabs({ taskId }) {
  const [records, setRecords] = useState(null)

  useEffect(() => {
    if (!taskId) return
    let alive = true
    api.getRecords(taskId).then((r) => alive && setRecords(r || []))
    return () => { alive = false }
  }, [taskId])

  const total = records ? records.length : 0

  return (
    <div style={{ border: '1px solid var(--surface-border)', borderRadius: 10, background: 'var(--surface-bg)', overflow: 'hidden', marginBottom: 8 }}>
      {/* 头部 */}
      <div style={{ display: 'flex', alignItems: 'center', padding: '10px 16px', borderBottom: '1px solid var(--surface-border)', gap: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>记录表格</span>
        <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
          {records === null ? '加载中…' : `${total} 条 · 来源 / 质量报告 / 下载见右侧面板`}
        </span>
      </div>
      <div style={{ padding: 16 }}>
        {records === null ? (
          <div style={{ textAlign: 'center', padding: 30, color: 'var(--content-fg-tertiary)', fontSize: 13 }}>加载记录…</div>
        ) : (
          <RecordsTable records={records} />
        )}
      </div>
    </div>
  )
}
