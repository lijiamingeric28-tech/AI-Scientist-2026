import { useEffect, useMemo, useRef, useState } from 'react'
import BackToTop from '@/components/ui/BackToTop'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useDismissTransition } from '@/hooks/useDismissTransition'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import * as api from '@/services/api'
import { saveAsDefault } from './ExportDialog'
import './workbench-export.css'

const FIELDS = [
  ['uncertainty', '独立不确定度'],
  ['conditions', '方法与测量条件'],
  ['original', '原报值与单位'],
  ['source', '来源与定位'],
  ['processing', '处理与核验状态'],
]
const PREVIEW_COLUMNS = {
  target: '天体', property_name: '性质', value: '数值', unit: '单位', error_minus: '负向误差',
  error_plus: '正向误差', error_unit: '误差单位', limit: '限值类型', lower_bound: '下端点',
  upper_bound: '上端点', text_value: '文字值', measurement_id: '测量 ID', source_title: '来源',
}

async function downloadArtifact(taskId, artifactId, filename, canSave = () => true) {
  const response = await fetch(api.exportFileUrl(taskId, artifactId))
  if (!response.ok) throw new Error('文件暂不可读，请重试')
  const blob = await response.blob()
  if (canSave()) await saveAsDefault(blob, filename)
}

function DownloadedFiles({ taskId, files }) {
  const [failure, setFailure] = useState('')
  const [pending, setPending] = useState(null)
  async function download(file) {
    setFailure('')
    setPending(file.artifact_id)
    try {
      await downloadArtifact(taskId, file.artifact_id, file.name)
    } catch (error) {
      setFailure(error.message)
    } finally {
      setPending(null)
    }
  }
  return <><ul className="export-download-list">
    {files.map((file, index) => <li key={`${file.artifact_id}:${index}`}>
      <Icon.FileText aria-hidden="true" />
      <span>{file.name}</span>
      <Button variant="outline" size="sm" disabled={pending !== null} onClick={() => download(file)}>下载文件</Button>
    </li>)}
  </ul>{failure && <p role="alert" className="resource-error">{failure}</p>}</>
}

function ExportOptions({ settings, update, fields, setFields, rows, multiple, disabled }) {
  return <fieldset className="export-options" disabled={disabled}>
    <legend>导出设置</legend>
    {rows > 0 && <>
      <label>数据格式
        <select value={settings.format} onChange={e => update({ format: e.target.value })}>
          <option value="csv">CSV · 每条测量一行</option>
          <option value="csv_wide">CSV 宽表 · 按共同观测展开</option>
          <option value="json">JSON · 结构化字段</option>
        </select>
      </label>
      <label>数据分表
        <select value={settings.group} onChange={e => update({ group: e.target.value })}>
          <option value="combined">合并为一份</option>
          <option value="property">按性质分表</option>
          <option value="material">按资料分表</option>
        </select>
      </label>
      <div className="export-field-options" role="group" aria-label="数据保留字段">
        <h4>数据保留字段</h4>
        <span>始终保留测量、性质和单位</span>
        {FIELDS.map(([key, name]) => <label key={key}>
          <input type="checkbox" checked={fields.includes(key)} onChange={e => {
            const on = e.target.checked
            setFields(current => FIELDS.map(([id]) => id).filter(id => id === key ? on : current.includes(id)))
          }} />{name}
        </label>)}
      </div>
    </>}
    <label>交付方式
      <select value={settings.container} disabled={settings.originals} onChange={e => update({ packageChoice: e.target.value })}>
        <option value="direct" disabled={multiple}>直接下载单个文件</option>
        <option value="zip">ZIP 研究包</option>
        <option value="separate">数据与图像分开下载</option>
      </select>
    </label>
    <label className="export-originals"><input type="checkbox" checked={settings.originals}
      onChange={e => update({ originals: e.target.checked })} />包含相关原件（ZIP）</label>
  </fieldset>
}

function DataPreview({ data, file, onFile }) {
  const files = data.files.filter(item => item.kind === 'data')
  const preview = data.data_preview
  if (!preview) return <p className="hint">本次选择只有图像。</p>
  const json = preview.format === 'json'
  const shown = json ? preview.value.measurements.length : preview.rows.length
  return <section className="export-data-preview">
    {files.length > 1 && <label>预览文件
      <select value={file} onChange={e => onFile(e.target.value)}>
        {files.map(item => <option key={item.path} value={item.path}>{item.path}</option>)}
      </select>
    </label>}
    <div className="export-preview-caption">
      <strong>{preview.path}</strong><span>显示前 {shown} 项 · 共 {preview.total} 项</span>
    </div>
    {json ? <pre className="export-preview-code" aria-label="JSON 内容" tabIndex={0}>
      {JSON.stringify(preview.value, null, 2)}
    </pre> : <div className="export-preview-table-wrap" role="region" tabIndex={0} aria-label="CSV 内容">
      <table className="export-preview-table">
        <thead><tr>{preview.columns.map(column => <th key={column} scope="col" data-column={column}
          title={column}>{PREVIEW_COLUMNS[column] || column}</th>)}</tr></thead>
        <tbody>{preview.rows.map((row, i) => <tr key={i}>{row.map((value, j) =>
          <td key={preview.columns[j]} title={value}>{value}</td>)}</tr>)}</tbody>
      </table>
    </div>}
  </section>
}

function ImagePreview({ images, onRemove, disabled }) {
  const [selected, setSelected] = useState(null)
  const image = images.find(item => item.figure_id === selected) || images[0]
  if (!image) return null
  return <section className="export-image-preview">
    {images.length > 1 && <div className="export-image-picker" aria-label="选择要预览的图像">
      {images.map((item, index) => <button type="button" className="export-image-thumb" key={item.figure_id}
        aria-pressed={image.figure_id === item.figure_id} onClick={() => setSelected(item.figure_id)}
        aria-label={`${index + 1}. ${item.label || '研究图像'}`}>
        {item.image_url ? <img src={item.image_url} alt="" loading="lazy" decoding="async" /> : <Icon.Image aria-hidden="true" />}
      </button>)}
    </div>}
    <figure>
      {image.image_url ? <a href={image.image_url} target="_blank" rel="noreferrer" title="查看原图">
        <img src={image.image_url} alt={image.label || '研究图像'} />
      </a> : <p role="status">图像文件暂不可读</p>}
      <figcaption>
        <div className="workbench-section-heading"><strong>{image.label || '研究图像'}{image.page ? ` · 第 ${image.page} 页` : ''}</strong>
          <button type="button" className="text-link" disabled={disabled} onClick={() => onRemove('figures', image.figure_id)}>移除此图像</button>
        </div>
        <p>{image.caption || image.source_title}</p>
      </figcaption>
    </figure>
  </section>
}

function SelectionList({ selection, sourceLabels, onRemove, disabled }) {
  const groups = useMemo(() => {
    const grouped = new Map()
    for (const kind of ['records', 'figures']) {
      for (const item of Object.values(selection.items[kind])) {
        const source = sourceLabels.get(item.sourceId) || item.source || '已选资料'
        if (!grouped.has(source)) grouped.set(source, [])
        grouped.get(source).push({ ...item, kind })
      }
    }
    return [...grouped]
  }, [selection.items, sourceLabels])
  return <div className="export-selection-list">{groups.map(([source, items]) =>
    <details key={source} open={groups.length === 1 || undefined}>
      <summary>{source} · {items.length} 项</summary>
      <ul>{items.map(item => <li key={`${item.kind}:${item.id}`}>
        <span>{item.title || item.id}</span>
        <button type="button" className="text-link" aria-label={`移除 ${item.title || item.id}`} disabled={disabled}
          onClick={() => onRemove(item.kind, item.id)}>移除</button>
      </li>)}</ul>
    </details>)}</div>
}

export default function WorkbenchExport({ scope, selection, resources, onClose, reload, readOnly, sourceLabels }) {
  const dismissal = useDismissTransition(onClose)
  const dialog = useDialogFocus(true, dismissal.close)
  const [tab, setTab] = useState(readOnly ? 'files' : 'selection')
  const [settings, setSettings] = useState({ format: 'csv', group: 'combined', packageChoice: 'direct', originals: false })
  const [fields, setFields] = useState(() => FIELDS.map(([id]) => id))
  const [undo, setUndo] = useState([])
  const [previewTab, setPreviewTab] = useState(selection.measurementIds.length ? 'data' : 'images')
  const [file, setFile] = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [exported, setExported] = useState(null)
  const action = useRef(null), inFlight = useRef(false), mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const rows = selection.measurementIds.length, images = selection.figureIds.length
  const hasSelection = rows + images > 0
  const multiple = (rows > 0 && settings.group !== 'combined') || images > 1 || Boolean(rows && images)
  const container = settings.originals || (multiple && settings.packageChoice === 'direct') ? 'zip' : settings.packageChoice
  const payload = {
    task_id: scope.taskId, delivery_id: scope.deliveryId, expected_delivery_revision: scope.revision,
    export_schema_version: 3, selection: { measurement_ids: selection.measurementIds, figure_ids: selection.figureIds },
    options: { data_format: settings.format, group_by: rows ? settings.group : 'combined',
      container, include_originals: settings.originals, fields: rows ? fields : [] },
  }
  const key = JSON.stringify(payload)
  const requestedFile = file?.key === key ? file.path : null
  const current = snapshot?.key === key && snapshot.retry === retry ? snapshot : null
  const data = current?.data
  const previewReady = data && current.path === requestedFile
  const files = data?.files || []
  const cannotRead = files.some(item => item.available === false)
  const view = previewTab === 'data' && !rows ? 'images' : previewTab === 'images' && !images ? 'data' : previewTab
  const update = patch => setSettings(previous => ({ ...previous, ...patch }))

  useEffect(() => {
    if (readOnly || tab !== 'selection' || !hasSelection) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      api.previewExport(scope.taskId, { ...JSON.parse(key), operation_id: 'preview' },
        { path: requestedFile, signal: controller.signal })
        .then(data => {
          if (controller.signal.aborted) return
          if (data.delivery_id !== scope.deliveryId || data.delivery_revision !== scope.revision)
            throw new Error('预览对应的成果版本已变化')
          setSnapshot({ key, retry, path: requestedFile, data })
        })
        .catch(e => { if (!controller.signal.aborted) setSnapshot({ key, retry, path: requestedFile, error: e.message }) })
    }, 100)
    return () => { clearTimeout(timer); controller.abort() }
  }, [key, requestedFile, tab, retry, hasSelection, readOnly, scope.taskId, scope.deliveryId, scope.revision])
  useEffect(() => { setError(''); setExported(null) }, [key])

  function remove(kind, id) {
    const item = selection.items[kind][id]
    if (!item) return
    setUndo(previous => [...previous, [{ kind, item }]])
    selection.remove(kind, id)
  }
  function clear() {
    setUndo(previous => [...previous, ['records', 'figures'].flatMap(kind =>
      Object.values(selection.items[kind]).map(item => ({ kind, item })))])
    selection.clear()
  }
  function undoRemove() {
    if (!undo.length) return
    selection.restore(undo.at(-1))
    setUndo(previous => previous.slice(0, -1))
  }

  async function download() {
    if (inFlight.current || readOnly || !previewReady || cannotRead) return
    inFlight.current = true
    setBusy(true); setError('')
    try {
      if (action.current?.key !== key) action.current = { key, operation: api.newOperationId() }
      const result = await api.createExport(scope.taskId, { ...payload, operation_id: action.current.operation })
      if (result.delivery_id !== scope.deliveryId || result.delivery_revision !== scope.revision)
        throw new Error('导出成果已变化，请重新选择')
      if (!mounted.current) return
      if (container === 'separate') {
        setExported(result.artifacts.map(artifact => ({ ...artifact, name: artifact.filename })))
        setTab('files')
        dialog.current?.focus({ preventScroll: true })
      } else {
        await downloadArtifact(scope.taskId, result.artifacts[0].artifact_id, result.filename, () => mounted.current)
        if (!mounted.current) return
        dialog.current?.focus({ preventScroll: true })
        setExported(result.filename)
      }
      reload('exports')
    } catch (e) { if (mounted.current) setError(e.message) }
    finally { inFlight.current = false; if (mounted.current) setBusy(false) }
  }

  const savedFiles = resources.exports?.data || []
  const downloads = Array.isArray(exported) && !exported.every(file =>
    savedFiles.some(saved => saved.artifact_id === file.artifact_id && saved.name === file.name))
    ? [...exported, ...savedFiles.filter(saved => !exported.some(file => saved.artifact_id === file.artifact_id && saved.name === file.name))]
    : savedFiles
  return <div className="settings-overlay workbench-export-overlay" data-closing={dismissal.closing || undefined} onClick={dismissal.close}>
    <section ref={dialog} className="export-center selecting animate-modal-in workbench-export-dialog"
      role="dialog" aria-modal="true" aria-labelledby="workbench-export-title" tabIndex={-1}
      onClick={e => e.stopPropagation()} data-closing={dismissal.closing || undefined}
      onAnimationEnd={dismissal.onAnimationEnd} onKeyDownCapture={dismissal.onKeyDownCapture}>
      <header className="settings-header"><h2 id="workbench-export-title">导出结果</h2>
        <Button aria-label="关闭导出" variant="outline" size="sm" onClick={dismissal.close}>关闭</Button>
      </header>
      <nav className="workspace-chips export-tabs" aria-label="导出页面">
        {!readOnly && <button className={`filter-chip ${tab === 'selection' ? 'active' : ''}`}
          aria-pressed={tab === 'selection'} onClick={() => setTab('selection')}>所选内容</button>}
        <button className={`filter-chip ${tab === 'files' ? 'active' : ''}`}
          aria-pressed={tab === 'files'} onClick={() => setTab('files')}>已生成文件</button>
      </nav>
      <div className="workbench-export-body">
        {tab === 'files' ? (downloads.length ? <DownloadedFiles taskId={scope.taskId} files={downloads} />
          : resources.exports?.status === 'error' ? <p role="alert">文件读取失败 <button className="text-link" onClick={() => reload('exports')}>重试</button></p>
            : <p>{resources.exports?.status === 'success' ? '当前成果没有已生成的文件' : '正在读取文件…'}</p>)
          : <div className="export-split">
            <div className="export-configure">
              <div className="export-selection-heading">
                <h3>已选 {rows} 条测量 · {images} 幅图像</h3>
                <div>{undo.length > 0 && <button type="button" className="text-link" disabled={busy} onClick={undoRemove}>撤销移除</button>}
                  {hasSelection && <button type="button" className="text-link" disabled={busy} onClick={clear}>清空选择</button>}</div>
              </div>
              {hasSelection ? <>
                <SelectionList selection={selection} sourceLabels={sourceLabels} disabled={busy} onRemove={remove} />
                <ExportOptions settings={{ ...settings, container }} update={update} fields={fields} setFields={setFields}
                  rows={rows} multiple={multiple} disabled={busy} />
              </> : <p className="hint">在候选数据或全部数据中勾选要导出的测量和图像。</p>}
            </div>
            <div className="export-preview" aria-label="导出预览">
              <h3>导出预览</h3>
              {hasSelection ? <>
                <nav className="workspace-chips" aria-label="预览类别">
                  {[['data', '数据', rows], ['images', '图像', images], ['files', '文件清单', true]]
                    .filter(([, , count]) => count).map(([id, label]) =>
                      <button type="button" key={id} className={`filter-chip ${view === id ? 'active' : ''}`}
                        aria-pressed={view === id} onClick={() => setPreviewTab(id)}>{label}</button>)}
                </nav>
                {current?.error ? <p role="alert" className="resource-error">{current.error}{' '}
                  <button className="text-link" onClick={() => setRetry(n => n + 1)}>重试</button></p>
                  : !data ? <p role="status">正在准备预览…</p>
                    : view === 'data' ? <div aria-busy={!previewReady}>
                      <DataPreview data={data} file={requestedFile || data.data_preview?.path}
                        onFile={path => setFile({ key, path })} />
                      {!previewReady && <p role="status">正在读取所选文件…</p>}
                    </div>
                      : view === 'images' ? <ImagePreview images={data.images} onRemove={remove} disabled={busy} />
                        : <ul className="export-file-list">{files.map(item => <li key={item.path}>
                          <Icon.FileText aria-hidden="true" /><span>{item.path}</span>
                          {item.available === false && <strong>暂不可读</strong>}
                        </li>)}</ul>}
                {cannotRead && <p role="alert" className="resource-error">有文件暂不可读，请检查文件清单或调整选择。</p>}
              </> : <p className="hint">勾选后可查看数据、图像和文件清单。</p>}
            </div>
          </div>}
        <BackToTop />
      </div>
      {tab === 'selection' && <footer className="settings-footer">
        <div className="export-download-status" aria-live="polite">
          {error ? <span className="resource-error">{error}</span>
            : typeof exported === 'string' ? <span>下载已开始 · {exported}</span> : null}
        </div>
        <Button variant="outline" size="sm" onClick={dismissal.close}>返回选择</Button>
        <Button variant="accent" onClick={download} disabled={!previewReady || cannotRead || busy}>
          {busy ? '正在准备文件…' : container === 'zip' ? '下载 ZIP' : container === 'separate' ? '生成下载文件' : '下载文件'}
        </Button>
      </footer>}
    </section>
  </div>
}
