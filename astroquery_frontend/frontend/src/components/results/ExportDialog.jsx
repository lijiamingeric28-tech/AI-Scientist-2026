import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useToast } from '@/components/ui/toast'
import { journalLabel } from '@/lib/journal'

/* 导出窗口（2026-09-02 用户重设计 v2）：
 * - 白色不透明大弹窗 · 左筛选（性质 checkbox 多选 / 来源分组单选）右预览
 * - 选择交互：左侧筛选后默认全选，预览表格每行 checkbox，用户点掉不需要的即可导出
 *   （无剔除、无 localStorage 记忆）
 * - 格式：长表（CSV）/ JSON
 * - 保存：showSaveFilePicker 系统另存为（WebView2 支持）；不支持时降级浏览器下载
 */

const SOURCE_GROUPS = [
  { key: 'all', label: '全部来源' },
  { key: 'database', label: '仅星表' },
  { key: 'paper', label: '仅论文' },
  { key: 'supplementary', label: '仅补充材料' },
]

/* 来源类型推断：records 接口无 source_type 字段，按 source_id 前缀判型
 * SRC_DB_* → 星表（database）；SRC_SUPPL_* → 补充材料；其余 bibcode → 论文
 */
function sourceKindOf(sourceId) {
  const s = String(sourceId || '')
  if (s.startsWith('SRC_SUPPL')) return 'supplementary'
  if (s.startsWith('SRC_DB')) return 'database'
  return 'paper'
}

/* 系统另存为（File System Access API）：WebView2/Edge 支持；不支持时降级 a[download] */
async function saveAsDefault(blob, filename) {
  try {
    if (window.showSaveFilePicker) {
      const handle = await window.showSaveFilePicker({ suggestedName: filename })
      const writable = await handle.createWritable()
      await writable.write(blob)
      await writable.close()
      return true
    }
  } catch (err) {
    if (err && err.name === 'AbortError') return 'cancelled'  // 用户取消另存为
    // 其他错误（权限/不支持）：降级下载
  }
  // 降级：浏览器主动下载到默认目录
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
  return 'fallback'
}

export default function ExportDialog({ open, taskId, records, onClose }) {
  const { toast } = useToast()
  const [fields, setFields] = useState(null)         // null=全选，Set=勾选子集
  const [sourceGroup, setSourceGroup] = useState('all')
  const [searchText, setSearchText] = useState('')
  const [format, setFormat] = useState('wide')       // wide=长表 | json
  // 选中集：默认全选（null=全选，Set=用户点掉后的子集）
  const [selected, setSelected] = useState(null)

  // 任务/弹窗打开时重置
  useEffect(() => {
    if (!open || !taskId) return
    setFields(null)
    setSourceGroup('all')
    setSearchText('')
    setFormat('wide')
    setSelected(null)
  }, [open, taskId])

  const allFields = useMemo(() => [...new Set((records || []).map((r) => r.field_name))], [records])
  const byField = useMemo(() => {
    const m = {}
    for (const r of records || []) m[r.field_name] = (m[r.field_name] || 0) + 1
    return m
  }, [records])

  const isFieldOn = (f) => fields === null || fields.has(f)
  const toggleField = (f) => {
    setFields((prev) => {
      const next = prev === null ? new Set(allFields) : new Set(prev)
      if (next.has(f)) next.delete(f)
      else next.add(f)
      return next.size === allFields.length ? null : next
    })
  }
  const toggleAll = () => setFields((prev) => (prev === null ? new Set() : null))

  const q = searchText.trim().toLowerCase()
  // 先按左侧条件筛选（性质的种类/来源/搜索）→ 结果记录集
  const filtered = useMemo(() => (records || []).filter((r) => {
    if (!isFieldOn(r.field_name)) return false
    if (sourceGroup !== 'all' && sourceKindOf(r.source_id) !== sourceGroup) return false
    if (q && ![r.entity_name, r.field_name, r.field_value, r.source_id].some((v) => String(v ?? '').toLowerCase().includes(q))) return false
    return true
  }), [records, fields, sourceGroup, q, allFields])

  // 选中状态：null=全选（随筛选变化整体全选）；用户点掉某行后变 Set
  const isRowOn = (rid) => selected === null || selected.has(rid)
  const toggleRow = (rid) => {
    setSelected((prev) => {
      const base = prev === null ? new Set(filtered.map((r) => r.record_id)) : new Set(prev)
      if (base.has(rid)) base.delete(rid)
      else base.add(rid)
      return base
    })
  }
  // 全选/全不选（针对当前筛选结果）
  const filteredIds = filtered.map((r) => r.record_id)
  const allOn = filtered.length > 0 && filtered.every((r) => isRowOn(r.record_id))
  const toggleAllRows = () => {
    setSelected((prev) => {
      if (allOn) {
        // 全不选：从基础集去掉所有 filtered 行
        const next = prev === null ? new Set() : new Set(prev)
        filteredIds.forEach((id) => next.delete(id))
        return next
      }
      // 全选：合并 filtered 进入选中集（新基础 = 此前的 null + filtered）
      if (prev === null) return null
      const next = new Set(prev)
      filteredIds.forEach((id) => next.add(id))
      return next
    })
  }

  const exportCount = useMemo(() => filtered.filter((r) => isRowOn(r.record_id)).length, [filtered, selected])

  /* 长表 CSV 头部：与后端导出的 records_long 全列对齐（实体/性质/值/单位/来源/页/定位/置信度/方法/溯源） */
  const LONG_HEAD = ['实体', '性质', '值', '单位', '来源', '页码', '定位框', '置信度', '提取方式']

  const exportFile = async () => {
    const chosen = filtered.filter((r) => isRowOn(r.record_id))
    if (!chosen.length) {
      toast('没有选中的记录可导出', 'info')
      return
    }
    const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '')
    const base = `astroquery_${(taskId || '').slice(0, 8) || 'export'}_${stamp}`
    let blob, filename, kindLabel
    if (format === 'json') {
      // JSON：完整记录对象（含 provenance/上下文/原文摘录，与后端 final_output.records 同构）
      blob = new Blob([JSON.stringify(chosen, null, 2)], { type: 'application/json;charset=utf-8' })
      filename = `${base}.json`
      kindLabel = 'JSON'
    } else {
      const lines = [LONG_HEAD.join(',')]
      for (const r of chosen) {
        const prov = r.provenance || {}
        const cells = [
          r.entity_name, r.field_name, r.field_value, r.field_unit, r.source_id,
          prov.page ?? '', prov.bbox ? JSON.stringify(prov.bbox) : '',
          r.confidence ?? r.extraction_confidence ?? '',
          r.extraction_method === 'vlm_table' ? 'VLM 表格' : r.extraction_method === 'vlm_text' ? 'VLM 文本' : r.extraction_method || '数据库',
        ]
        lines.push(cells.map((c) => {
          const s = String(c ?? '')
          return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
        }).join(','))
      }
      blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
      filename = `${base}_长表.csv`
      kindLabel = '长表 CSV'
    }
    const res = await saveAsDefault(blob, filename)
    if (res === 'cancelled') return
    toast(`已导出 ${chosen.length} 条记录（${kindLabel}）`, 'success')
  }

  if (!open) return null

  return (
    <div className="animate-fade-in" style={{ position: 'fixed', inset: 0, zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      {/* 遮罩 */}
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,.45)' }} />
      {/* 白色不透明面板（无玻璃/无透明度） */}
      <div style={{ position: 'relative', width: 'min(90vw, 1080px)', height: 'min(86vh, 720px)', background: '#ffffff', border: '1px solid #e5e7eb', borderRadius: 14, boxShadow: '0 24px 64px rgba(0,0,0,.35)', display: 'flex', flexDirection: 'column', overflow: 'hidden', color: '#1f2937' }}>
        {/* 头部 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: '1px solid #e5e7eb', flexShrink: 0 }}>
          <Icon.Download style={{ color: 'var(--accent)' }} />
          <span style={{ fontSize: 15, fontWeight: 600 }}>导出数据</span>
          <span style={{ fontSize: 12, color: '#6b7280' }}>
            已选 <b style={{ color: 'var(--accent)' }}>{exportCount}</b> / 共 <b>{records?.length ?? 0}</b> 条
          </span>
          <span style={{ flex: 1 }} />
          <input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="搜索实体 / 性质 / 值 / 来源…"
            style={{ width: 220, padding: '6px 10px', fontSize: 12, borderRadius: 7, border: '1px solid #d1d5db', background: '#fff', color: '#1f2937', outline: 'none' }}
          />
          <Button variant="ghost" size="icon" onClick={onClose} title="关闭"><Icon.Close /></Button>
        </div>

        {/* 主体：左筛选 + 右预览 */}
        <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
          {/* 左列：性质多选 + 来源分组 */}
          <div style={{ width: 240, borderRight: '1px solid #e5e7eb', padding: '12px 14px', overflowY: 'auto', flexShrink: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#4b5563' }}>性质（{fields === null ? '全选' : fields.size}/{allFields.length}）</span>
              <button onClick={toggleAll} style={{ border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 11, color: 'var(--accent)' }}>
                {fields === null ? '全不选' : '全选'}
              </button>
            </div>
            {allFields.map((f) => (
              <label key={f} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 2px', cursor: 'pointer' }}>
                <input type="checkbox" checked={isFieldOn(f)} onChange={() => toggleField(f)} style={{ accentColor: 'var(--accent)' }} />
                <span className="font-mono" style={{ fontSize: 12, flex: 1 }}>{f}</span>
                <span style={{ fontSize: 11, color: '#9ca3af' }}>{byField[f]}</span>
              </label>
            ))}
            <div style={{ borderTop: '1px solid #e5e7eb', marginTop: 10, paddingTop: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#4b5563', marginBottom: 6 }}>来源</div>
              {SOURCE_GROUPS.map((g) => (
                <label key={g.key} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 2px', cursor: 'pointer' }}>
                  <input type="radio" name="srcGroup" checked={sourceGroup === g.key} onChange={() => setSourceGroup(g.key)} style={{ accentColor: 'var(--accent)' }} />
                  <span style={{ fontSize: 12 }}>{g.label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* 右列：预览表格（行 checkbox，默认全选） */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 14px', borderBottom: '1px solid #e5e7eb', flexShrink: 0 }}>
              <input type="checkbox" checked={allOn} onChange={toggleAllRows} style={{ accentColor: 'var(--accent)' }} />
              <span style={{ fontSize: 12, color: '#4b5563' }}>{allOn ? '取消全选' : '全选当前筛选'}</span>
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 12, color: '#6b7280' }}>筛选后默认全选，点掉不需要的即可导出</span>
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: '10px 14px' }}>
              {filtered.length === 0 ? (
                <div style={{ padding: '30px 0', textAlign: 'center', fontSize: 12, color: '#9ca3af' }}>无记录（可调整左侧筛选或搜索）</div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
                  <thead>
                    <tr style={{ background: '#f3f4f6' }}>
                      {['', '性质', '值', '单位', '来源', '提取方式'].map((h, i) => (
                        <th key={i} style={{ textAlign: 'left', padding: '8px 10px', fontWeight: 510, color: '#6b7280', fontSize: 11.5, whiteSpace: 'nowrap' }}>
                          {i === 0 ? <input type="checkbox" checked={allOn} onChange={toggleAllRows} style={{ accentColor: 'var(--accent)' }} /> : h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((r) => (
                      <tr key={r.record_id} style={{ borderTop: '1px solid #f3f4f6', opacity: isRowOn(r.record_id) ? 1 : 0.5 }}>
                        <td style={{ padding: '7px 10px' }}>
                          <input type="checkbox" checked={isRowOn(r.record_id)} onChange={() => toggleRow(r.record_id)} style={{ accentColor: 'var(--accent)' }} />
                        </td>
                        <td className="font-mono" style={{ padding: '7px 10px', fontWeight: 510 }}>{r.field_name}</td>
                        <td className="font-mono" style={{ padding: '7px 10px' }}>{String(r.field_value).slice(0, 40)}</td>
                        <td style={{ padding: '7px 10px', color: '#4b5563' }}>{r.field_unit}</td>
                        <td style={{ padding: '7px 10px', color: '#4b5563', fontSize: 11 }} title={r.source_id}>{journalLabel(r.source_id)}</td>
                        <td style={{ padding: '7px 10px', fontSize: 11 }}>{r.extraction_method === 'vlm_table' ? 'VLM 表格' : r.extraction_method === 'vlm_text' ? 'VLM 文本' : '数据库'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>

        {/* 底部：格式 + 导出 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 18px', borderTop: '1px solid #e5e7eb', flexShrink: 0 }}>
          <span style={{ fontSize: 12, color: '#4b5563' }}>格式</span>
          <div style={{ display: 'flex', gap: 2, padding: 3, borderRadius: 8, background: '#f3f4f6' }}>
            {[
              { key: 'wide', label: '长表（CSV）' },
              { key: 'json', label: 'JSON' },
            ].map((f) => (
              <button key={f.key} onClick={() => setFormat(f.key)} style={{ padding: '5px 14px', fontSize: 12, fontWeight: 510, border: 'none', cursor: 'pointer', borderRadius: 6, background: format === f.key ? 'var(--accent)' : 'transparent', color: format === f.key ? '#fff' : '#4b5563' }}>
                {f.label}
              </button>
            ))}
          </div>
          <span style={{ flex: 1 }} />
          <Button size="sm" onClick={exportFile} disabled={!exportCount} style={{ background: 'var(--accent)', color: '#fff' }}>
            <Icon.Download /> 导出 {exportCount} 条
          </Button>
        </div>
      </div>
    </div>
  )
}
