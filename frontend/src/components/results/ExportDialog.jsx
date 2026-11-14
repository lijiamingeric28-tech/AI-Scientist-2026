import { useRecordsPage } from '@/hooks/useRecordsPage'
import { filteredSelection } from '@/services/resultPages'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { sourceType, extractionLabel, sourceName } from '@/lib/readableData'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import {useMediaQuery} from '@/hooks/useMediaQuery'
import { useToast } from '@/components/ui/toast'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import { journalLabel } from '@/lib/journal'
import { matchesRecordSearch } from '@/lib/recordSearch'
import * as api from '@/services/api'

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
  { key: 'supplement', label: '仅补充材料' },
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
export async function saveAsDefault(blob, filename, chooseLocation = false) {
  try {
    if (chooseLocation && window.showSaveFilePicker) {
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
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  return 'fallback'
}

export default function ExportDialog({ serverScope, initialFilters, open, taskId, records, sources = [], onClose, embedded = false, readOnly = false, readOnlyReason }) {
  const propertyLabel = usePropertyLabel()
  const narrow=useMediaQuery('(max-width:767px)'),[filtersOpen,setFiltersOpen]=useState(false)
  const { toast } = useToast()
  const dialogRef = useDialogFocus(open && !embedded, onClose)
  const exportingRef = useRef(false)
  const [exporting, setExporting] = useState(false)
  const [fields, setFields] = useState(null)         // null=全选，Set=勾选子集
  const [sourceGroup, setSourceGroup] = useState('all')
  const [searchText, setSearchText] = useState(initialFilters?.q || '')
  const [format, setFormat] = useState('csv_long'), [previewPage,setPreviewPage]=useState(1)
  const [deliveryBinding, setDeliveryBinding] = useState(null)
  // 选中集：默认全选（null=全选，Set=用户点掉后的子集）
  const [selected, setSelected] = useState(null)
  const [excluded,setExcluded]=useState(new Set())
  const exportFilters={...(initialFilters||{}),q:searchText,fields:fields===null?undefined:[...fields],source_group:sourceGroup}
  const remote=useRecordsPage(serverScope,{...exportFilters,offset:(previewPage-1)*50,limit:50,collapse_duplicates:false},open&&!readOnly&&!!serverScope)
  const total=serverScope ? remote.data?.total ?? 0 : records.length
  const serverRows=remote.data?.items || []
  const facets=remote.data?.aggregates
  const exportFilterKey=JSON.stringify(filteredSelection(exportFilters).filters)
  useEffect(()=>{if(serverScope){setPreviewPage(1);setSelected(null);setExcluded(new Set())}},[exportFilterKey])

  // 任务/弹窗打开时重置
  useEffect(() => {
    if (!open || !taskId) return
    setFields(null)
    setSourceGroup('all')
    setSearchText(initialFilters?.q || '')
    setFormat('csv_long')
    setSelected(serverScope?null:new Set(records.map(r=>r.record_id)));setExcluded(new Set())
  }, [open, taskId])

  useEffect(() => {
    let cancelled = false
    setDeliveryBinding(null)
    if (open && taskId && (serverScope || records.some(record => record.protocol_version === 2))) {
      api.getDelivery(taskId,serverScope?.revision).then(binding => { if (!cancelled) setDeliveryBinding(binding) }).catch(() => {})
    }
    return () => { cancelled = true }
  }, [open, taskId,serverScope?.revision])

  const allFields = useMemo(() => facets?.fields?.map(item=>item.field) || [...new Set((records || []).map((r) => r.field_name))], [records,facets])
  const byField = useMemo(() => {
    const m = {}
    if(facets?.fields) return Object.fromEntries(facets.fields.map(item=>[item.field,item.count]))
    for (const r of records || []) m[r.field_name] = (m[r.field_name] || 0) + 1
    return m
  }, [records,facets])

  useEffect(()=>setPreviewPage(1),[fields,sourceGroup,searchText])
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
  const filtered = useMemo(() => serverScope ? serverRows : (records || []).filter((r) => {
    if (!isFieldOn(r.field_name)) return false
    const kind = r.protocol_version === 2 ? { catalog: 'database', official_attachment: 'supplement', paper: 'paper' }[r.source_kind] : sourceType(sources.find(source => source.source_id === r.source_id)?.source_type || sourceKindOf(r.source_id))
    if (sourceGroup !== 'all' && kind !== sourceGroup) return false
    if (!matchesRecordSearch(r, q, sources.find(source => source.source_id === r.source_id), propertyLabel)) return false
    return true
  }), [records, fields, sourceGroup, q, allFields, sources, propertyLabel,serverScope,remote.data])

  // 选中状态：null=全选（随筛选变化整体全选）；用户点掉某行后变 Set
  const isRowOn = (rid) => selected === null ? !excluded.has(rid) : selected.has(rid)
  const toggleRow = (rid) => {
    if(serverScope && selected===null){setExcluded(prev=>{const next=new Set(prev);next.has(rid)?next.delete(rid):next.add(rid);return next});return}
    setSelected((prev) => {
      const base = prev === null ? new Set(filtered.map((r) => r.record_id)) : new Set(prev)
      if (base.has(rid)) base.delete(rid)
      else base.add(rid)
      return base
    })
  }
  // 全选/全不选（针对当前筛选结果）
  const filteredIds = filtered.map((r) => r.record_id)
  const allOn = serverScope ? total > 0 && selected===null && excluded.size===0 : filtered.length > 0 && filtered.every((r) => isRowOn(r.record_id))
  const toggleAllRows = () => {
    if(serverScope){setSelected(allOn?new Set():null);setExcluded(new Set());return}
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

  const exportCount = serverScope ? (selected===null ? Math.max(0,total-excluded.size) : selected.size) : records.filter((r) => isRowOn(r.record_id)).length

  /* 长表 CSV 头部：与后端导出的 records_long 全列对齐（实体/性质/值/单位/来源/页/定位/置信度/方法/溯源） */
  const LONG_HEAD = ['记录 ID', '实体', '性质', '值', '单位', '来源', '页码', '定位框', '置信度', '提取方式', '原文摘要']

  const exportFile = async (chooseLocation = false) => {
    if (exportingRef.current) return
    const chosen = records.filter((r) => isRowOn(r.record_id))
    if(readOnly){toast(readOnlyReason||'回放时点只读；请打开原任务最终结果后显式导出','info');return}
    if (!exportCount) {
      toast('没有选中的记录可导出', 'info')
      return
    }
    if (serverScope || chosen[0].protocol_version === 2) {
      exportingRef.current = true; setExporting(true)
      try {
        const binding = await api.getDelivery(taskId)
        setDeliveryBinding(binding)
        if (serverScope ? (serverScope.deliveryId !== binding.delivery_id || serverScope.revision !== binding.revision) : chosen.some(record => record.delivery_id !== binding.delivery_id || (record.delivery_revision && record.delivery_revision !== binding.revision))) throw new Error('交付版本已变化，请关闭并重新选择导出记录')
        const manifest = await api.createExport(taskId, { operation_id: api.newOperationId(), task_id: taskId,
          delivery_id: binding.delivery_id, expected_delivery_revision: binding.revision,
          selection: serverScope ? (selected===null ? filteredSelection(exportFilters,excluded) : {mode:'ids',measurement_ids:[...selected]}) : { mode: 'ids', measurement_ids: chosen.map(record => record.record_id) }, format, export_schema_version: 2 })
        const response = await fetch(api.artifactUrl(taskId, manifest.artifacts[0].artifact_id))
        if (!response.ok) throw new Error('导出文件当前不可用')
        const extension = { json: 'json', json_wide: 'json', package: 'zip', csv_long: 'csv', csv_wide: 'csv' }[format]
        const outcome = await saveAsDefault(await response.blob(), `astroquery_${taskId}_${format}_v2.${extension}`, chooseLocation)
        if (outcome !== 'cancelled') toast(outcome === true ? '文件已保存' : '下载已开始', 'success')
      } catch (error) { toast(`导出失败：${error.message}`, 'error') }
      finally { exportingRef.current = false; setExporting(false) }
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
          r.record_id, r.entity_name, r.field_name, r.field_value, r.field_unit, r.source_id,
          prov.page ?? '', prov.bbox ? JSON.stringify(prov.bbox) : '',
          r.confidence ?? r.extraction_confidence ?? '',
          extractionLabel(r.extraction_method),
          r.context_snippet ?? r.raw_text ?? '',
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
    exportingRef.current = true
    setExporting(true)
    let res
    try { res = await saveAsDefault(blob, filename, chooseLocation) }
    catch (error) { toast(`导出失败：${error.message}`, 'error'); return }
    finally { exportingRef.current = false; setExporting(false) }
    if (res === 'cancelled') return
    toast(`已导出 ${chosen.length} 条记录（${kindLabel}）`, 'success')
  }

  if (!open) return null

  return (
    <div className="animate-fade-in" style={{ position: embedded ? 'relative' : 'fixed', inset: embedded ? undefined : 0, zIndex: embedded ? undefined : 200, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      {/* 遮罩 */}
      {!embedded && <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,.45)' }} />}
      {/* 白色不透明面板（无玻璃/无透明度） */}
      <div ref={dialogRef} role={embedded ? undefined : "dialog"} aria-modal={embedded ? undefined : "true"} aria-label="选择记录与导出格式" tabIndex={-1} className="animate-modal-in export-dialog" style={{ position: 'relative', width: embedded ? '100%' : 'min(90vw, 1080px)', height: embedded ? 'min(68vh, 620px)' : 'min(86vh, 720px)', background: 'var(--seed-surface)', border: '1px solid var(--surface-border)', borderRadius: 14, boxShadow: '0 24px 64px rgba(0,0,0,.35)', display: 'flex', flexDirection: 'column', overflow: 'hidden', color: 'var(--content-fg)' }}>
        {/* 头部 */}
        <div className="export-dialog-header" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: '1px solid var(--surface-border)', flexShrink: 0 }}>
          <Icon.Download style={{ color: 'var(--accent)' }} />
          <span style={{ fontSize: 'var(--text-body)', fontWeight: 600 }}>选择导出记录</span>
          <span style={{ fontSize: 'var(--text-ui)', color: 'var(--content-fg-tertiary)' }}>
            已选 <b style={{ color: 'var(--accent)' }}>{exportCount}</b> / 共 <b>{serverScope ? facets?.total ?? total : records?.length ?? 0}</b> 条
          </span>
          {deliveryBinding && <span className="hint">交付修订 {deliveryBinding.revision}</span>}
          <span style={{ flex: 1 }} />
          <input
            aria-label="搜索导出记录"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="搜索导出范围内的记录"
            style={{ width: 220, padding: '6px 10px', fontSize: 'var(--text-ui)', borderRadius: 7, border: '1px solid var(--surface-border)', background: 'var(--seed-surface)', color: 'var(--content-fg)', outline: 'none' }}
          />
          {!embedded && <Button variant="ghost" size="icon" onClick={onClose} aria-label="关闭导出" title="关闭"><Icon.Close /></Button>}
        </div>

        {narrow&&<button className="export-filter-toggle" aria-expanded={filtersOpen} onClick={()=>setFiltersOpen(v=>!v)}>{filtersOpen?'收起导出筛选':'展开导出筛选'}</button>}
        {/* 主体：左筛选 + 右预览 */}
        <div className="export-dialog-body" style={{ flex: 1, display: 'flex', minHeight: 0 }}>
          {/* 左列：性质多选 + 来源分组 */}
          <div className="export-filters" hidden={narrow&&!filtersOpen} style={{ width: 240, borderRight: '1px solid var(--surface-border)', padding: '12px 14px', overflowY: 'auto', flexShrink: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 'var(--text-ui)', fontWeight: 600, color: 'var(--content-fg-secondary)' }}>性质（{fields === null ? '全选' : fields.size}/{allFields.length}）</span>
              <button onClick={toggleAll} style={{ border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 'var(--text-note)', color: 'var(--accent)' }}>
                {fields === null ? '全不选' : '全选'}
              </button>
            </div>
            {allFields.map((f) => (
              <label key={f} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 2px', cursor: 'pointer' }}>
                <input type="checkbox" checked={isFieldOn(f)} onChange={() => toggleField(f)} style={{ accentColor: 'var(--accent)' }} />
                <span className="font-mono" style={{ fontSize: 'var(--text-ui)', flex: 1 }}>{propertyLabel(f)}</span>
                <span style={{ fontSize: 'var(--text-note)', color: 'var(--content-fg-tertiary)' }}>{byField[f]}</span>
              </label>
            ))}
            <div style={{ borderTop: '1px solid var(--surface-border)', marginTop: 10, paddingTop: 10 }}>
              <div style={{ fontSize: 'var(--text-ui)', fontWeight: 600, color: 'var(--content-fg-secondary)', marginBottom: 6 }}>来源</div>
              {SOURCE_GROUPS.map((g) => (
                <label key={g.key} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 2px', cursor: 'pointer' }}>
                  <input type="radio" name="srcGroup" checked={sourceGroup === g.key} onChange={() => setSourceGroup(g.key)} style={{ accentColor: 'var(--accent)' }} />
                  <span style={{ fontSize: 'var(--text-note)' }}>{g.label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* 右列：预览表格（行 checkbox，默认全选） */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 14px', borderBottom: '1px solid var(--surface-border)', flexShrink: 0 }}>
              <input type="checkbox" checked={allOn} onChange={toggleAllRows} style={{ accentColor: 'var(--accent)' }} />
              <span style={{ fontSize: 'var(--text-ui)', color: 'var(--content-fg-secondary)' }}>{allOn ? '取消全选' : '全选当前筛选'}</span>
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 'var(--text-ui)', color: 'var(--content-fg-tertiary)' }}></span>
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: '10px 14px' }}>
              {serverScope && remote.status !== 'success' ? <p role="status">{remote.status==='error'?remote.error:'正在读取导出记录…'}{remote.status==='error'&&<button onClick={remote.reload}>重试</button>}</p> : filtered.length === 0 ? (
                <div style={{ padding: '30px 0', textAlign: 'center', fontSize: 'var(--text-ui)', color: 'var(--content-fg-tertiary)' }}>无记录（可调整左侧筛选或搜索）</div>
              ) : (
                <table className="export-records" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-ui)' }}>
                  <thead>
                    <tr style={{ background: 'var(--surface-secondary)' }}>
                      {['', '性质', '值', '单位', '来源', '提取方式', '原文摘要'].map((h, i) => (
                        <th key={i} style={{ textAlign: 'left', padding: '8px 10px', fontWeight: 510, color: 'var(--content-fg-tertiary)', fontSize: 'var(--text-note)', whiteSpace: 'nowrap' }}>
                          {i === 0 ? <input type="checkbox" aria-label="选择全部匹配记录" checked={allOn} onChange={toggleAllRows} style={{ accentColor: 'var(--accent)' }} /> : h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(serverScope?filtered:filtered.slice((previewPage-1)*20,previewPage*20)).map((r) => (
                      <tr key={r.record_id} style={{ borderTop: '1px solid var(--surface-border-subtle)', opacity: isRowOn(r.record_id) ? 1 : 0.5 }}>
                        <td style={{ padding: '7px 10px' }}>
                          <input data-record-id={r.record_id} type="checkbox" aria-label={`选择导出：${r.entity_name} ${propertyLabel(r.field_name)} ${r.field_value} ${r.field_unit || ''}`} checked={isRowOn(r.record_id)} onChange={() => toggleRow(r.record_id)} style={{ accentColor: 'var(--accent)' }} />
                        </td>
                        <td className="font-mono" style={{ padding: '7px 10px', fontWeight: 510 }}>{propertyLabel(r.field_name)}</td>
                        <td className="font-mono" style={{ padding: '7px 10px' }}>{String(r.field_value).slice(0, 40)}</td>
                        <td style={{ padding: '7px 10px', color: 'var(--content-fg-secondary)' }}>{r.field_unit}</td>
                        <td style={{ padding: '7px 10px', color: 'var(--content-fg-secondary)', fontSize: 'var(--text-note)' }} title={r.source_id}>{sourceName(r.source_label || sources.find(source => source.source_id === r.source_id), r.source_id, true)}</td>
                        <td style={{ padding: '7px 10px', fontSize: 'var(--text-note)' }}>{extractionLabel(r.extraction_method)}</td>
                        <td style={{ padding: '7px 10px', maxWidth: 200 }}><span className="caption-clamp" title={r.context_snippet || r.raw_text || ''}>{r.context_snippet || r.raw_text || '该记录未提供'}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>

        <div className="stage-links" style={{padding:'4px 18px'}}><button aria-label="导出上一页" disabled={previewPage===1} onClick={()=>setPreviewPage(n=>n-1)}>上一页</button><span>{previewPage} / {Math.max(1,Math.ceil((serverScope?total:filtered.length)/(serverScope?50:20)))} 页 · {serverScope?total:filtered.length} 条匹配</span><button aria-label="导出下一页" disabled={previewPage*(serverScope?50:20)>=(serverScope?total:filtered.length)} onClick={()=>setPreviewPage(n=>n+1)}>下一页</button></div>
        <p className="hint" style={{padding:'4px 18px'}}>{({csv_long:'每条测量一行；原报、处理值和误差分别保留。',csv_wide:'按性质与来源分组，不平均多来源测量。',json_wide:'按性质组织测量及其出处，适合程序读取。',json:'完整结构化数据及本次选择范围。',package:'打包本次选定数据与索引，不是全部论文原文包。'})[format]}</p>
        <p className="hint" style={{padding:'8px 18px'}}>{readOnly?'此回放时点只读，已有归档可下载；新导出请打开最终结果。':`已选 ${exportCount} 条 / 当前筛选 ${serverScope?total:filtered.length} 条。${serverScope?'导出包含全部匹配页，取消勾选的记录除外。':'更换筛选不会自动加入新记录。'}`}</p>
        {/* 底部：格式 + 导出 */}
        <div className="export-dialog-footer" style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 18px', borderTop: '1px solid var(--surface-border)', flexShrink: 0 }}>
          <span style={{ fontSize: 'var(--text-ui)', color: 'var(--content-fg-secondary)' }}>格式</span>
          <div className="export-formats" style={{ display: 'flex', gap: 2, padding: 3, borderRadius: 8, background: 'var(--surface-secondary)' }}>
            {((serverScope || records.some(record => record.protocol_version === 2)) ? [
              { key: 'csv_long', label: '测量明细 CSV' },
              { key: 'package', label: '研究数据包 ZIP' },
              { key: 'csv_wide', label: '分组宽表 CSV' },
              { key: 'json_wide', label: '按性质 JSON' },
              { key: 'json', label: '完整 JSON' },
            ] : [
              { key: 'csv_long', label: '长表（CSV）' },
              { key: 'json', label: 'JSON' },
            ]).map((f) => (
              <button key={f.key} aria-pressed={format === f.key} onClick={() => setFormat(f.key)} style={{ padding: '5px 14px', fontSize: 'var(--text-ui)', fontWeight: 510, border: 'none', cursor: 'pointer', borderRadius: 6, background: format === f.key ? 'var(--accent)' : 'transparent', color: format === f.key ? 'var(--seed-surface)' : 'var(--content-fg-secondary)' }}>
                {f.label}
              </button>
            ))}
          </div>
          <span style={{ flex: 1 }} />
          {window.showSaveFilePicker && <Button variant="outline" size="sm" disabled={readOnly || !exportCount || exporting || (serverScope && remote.status!=='success')} onClick={() => exportFile(true)}>另存为…</Button>}
          <Button size="sm" onClick={() => exportFile(false)} disabled={readOnly || !exportCount || exporting || (serverScope && remote.status!=='success')} style={{ background: 'var(--accent)', color: 'var(--seed-surface)' }}>
            <Icon.Download /> {exporting ? '正在导出…' : `生成并下载 ${exportCount} 条`}
          </Button>
        </div>
      </div>
    </div>
  )
}
