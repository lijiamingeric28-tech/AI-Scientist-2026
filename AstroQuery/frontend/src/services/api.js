import {limitedValueText} from '@/lib/valueDisplay'
const BASE = (import.meta.env?.VITE_API_BASE || '/api').replace(/\/+$/, '')
let configRevision = null
export const newOperationId = () => crypto.randomUUID()

export async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, { ...options, headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers } })
  if (!response.ok) {
    let detail
    try { detail = (await response.json()).detail } catch { detail = response.statusText }
    const error = new Error(typeof detail === 'string' ? detail : detail?.message || JSON.stringify(detail))
    error.code = detail?.code; error.status = response.status; error.details = detail
    throw error
  }
  return response.json()
}
const post = (path, body) => request(path, { method: 'POST', body: JSON.stringify(body) })
const id = encodeURIComponent
export const getState = (taskId, options = {}) => request(`/tasks/${id(taskId)}/state`, options)
export const getConversationState = (taskId, options = {}) => request(`/tasks/${id(taskId)}/state?view=conversation`, options)
export const getWorkspaceState = (taskId, options = {}) => request(`/tasks/${id(taskId)}/state?view=workspace`, options)
export const getTask = getState
export const getReplayClock = (taskId, options = {}) => request(`/tasks/${id(taskId)}/replay-clock`, options)
export const createTask = (query, operationId = newOperationId(), retrievalPreferences) => post('/tasks', { query, operation_id: operationId, ...(retrievalPreferences ? {retrieval_preferences:retrievalPreferences} : {}) })
export const listTasks = (limit = 50, offset = 0, status, source) => request(`/tasks?${new URLSearchParams({ limit, offset, include_replays: false, ...(['active','attention','ended','error'].includes(status) ? {category:status} : status ? { status } : {}), ...(source ? { source } : {}) })}`)
export const getPresentation = (taskId, atSeq, options = {}) => request(`/tasks/${id(taskId)}/presentation?include_chat_activity=true${atSeq == null ? '' : `&at_seq=${atSeq}`}`, options)
export const getExecution = (taskId, query = {}, options = {}) => request(`/tasks/${id(taskId)}/execution?${new URLSearchParams(Object.fromEntries(Object.entries(query).filter(([,v])=>v!=null)))}`, options)
export const executionReportUrl = (taskId, cursor, format) => `${BASE}/tasks/${id(taskId)}/execution/report?${new URLSearchParams({at_seq:cursor,format})}`
export const draftAction = (taskId, body) => post(`/tasks/${id(taskId)}/draft-actions`, body)
export const getPropertyCatalog = (taskId, questionId, options) =>
  request(`/tasks/${id(taskId)}/property-catalog?question_id=${id(questionId)}`, options)
export const reviewAnswer = (taskId, body) => post(`/tasks/${id(taskId)}/review-answers`, body)
export async function controlTask(taskId, action, operation) {
  const state = operation ? null : await getState(taskId)
  return post(`/tasks/${id(taskId)}/${action}`, operation || { operation_id: newOperationId(), expected_revision: state.revision })
}
export const pauseTask = taskId => controlTask(taskId, 'pause')
export const cancelTask = taskId => controlTask(taskId, 'cancel')
export const retryTask = taskId => controlTask(taskId, 'continue')
export function openEventStream(taskId, handlers, afterSeq = 0) {
  const source = new EventSource(`${BASE}/tasks/${id(taskId)}/events/stream?after_seq=${afterSeq}`)
  source.onmessage = event => { try { handlers.onEvent?.(JSON.parse(event.data)) } catch (error) { handlers.onProtocolError?.(error) } }
  source.addEventListener('eof', () => { source.close(); handlers.onEnd?.() })
  source.onerror = () => { source.close(); handlers.onError?.() }
  return source
}
export const getEvents = (taskId, afterSeq = 0) => request(`/tasks/${id(taskId)}/events?after_seq=${afterSeq}`)
export const getDelivery = (taskId, revision, { deliveryId, ...options } = {}) => {
  const params = new URLSearchParams()
  if (revision) params.set('delivery_revision', revision)
  if (deliveryId) params.set('delivery_id', deliveryId)
  return request(`/tasks/${id(taskId)}/delivery${params.size ? '?' + params : ''}`, options)
}
export async function getPreview(taskId, options) {
  const first = await request(`/tasks/${id(taskId)}/preview?view=ui&limit=500`, options)
  const items = [...first.items]
  while (items.length < first.total) {
    const page = await request(`/tasks/${id(taskId)}/preview?view=ui&limit=500&offset=${items.length}&expected_preview_id=${id(first.preview_id)}`, options)
    if (page.preview_id !== first.preview_id || !page.items.length) throw new Error('临时数据已有更新，请重新读取')
    items.push(...page.items)
  }
  return { ...first, items }
}
async function resource(taskId, deliveryId, name, revision, query='', options) {
  if (!deliveryId) throw new Error('读取结果必须指定交付版本')
  const suffix = revision ? `&expected_delivery_revision=${revision}&delivery_revision=${revision}` : ''
  const first = await request(`/tasks/${id(taskId)}/deliveries/${id(deliveryId)}/${name}?limit=500${suffix}${query}`, options)
  if (first.delivery_id !== deliveryId) throw new Error('结果响应的交付版本不一致')
  if (revision && first.delivery_revision && first.delivery_revision !== revision) throw new Error('结果响应的交付修订不一致')
  if (first.body !== undefined) return first.body
  const items = [...first.items]
  if (first.legacy_version === 1) for (const item of items) item.legacy_version=1
  while (items.length < first.total) {
    const pinned = first.delivery_revision ? `&expected_delivery_revision=${first.delivery_revision}&delivery_revision=${first.delivery_revision}` : suffix
    const page = await request(`/tasks/${id(taskId)}/deliveries/${id(deliveryId)}/${name}?limit=500&offset=${items.length}${pinned}${query}`, options)
    if (page.delivery_id !== deliveryId || page.delivery_revision !== first.delivery_revision || JSON.stringify(page.snapshot_ref) !== JSON.stringify(first.snapshot_ref) || !page.items.length) throw new Error('结果分页版本或范围不一致')
    items.push(...page.items.map(item=>page.legacy_version===1?{...item,legacy_version:1}:item))
  }
  if (name === 'figures') items.coverage = first.coverage || []
  items.snapshot_ref = first.snapshot_ref
  return items
}
function adaptRecord(item,deliveryId,revision,taskId) {
  if (item.legacy_version === 1) return { ...item, task_id: taskId || item.task_id }
  const { source, derived, property_binding: binding } = item
  const ready = derived?.main_state === 'ready'
  const value = ready ? derived.value_typed : source.value
  const representation = ready ? binding.output_profile.representation.kind : source.representation
  const dimensionless = ready ? binding.output_profile.unit.kind === 'dimensionless' : source.unit_declaration?.kind === 'dimensionless'
  const nativeUnit = ready ? binding.output_profile.unit.canonical_symbol ?? (dimensionless ? '1' : '') : source.unit ?? source.unit_declaration?.canonical_symbol ?? null
  const nativeIsCoordinate = typeof nativeUnit === 'string' && (/^dex(?:\b|$)/i.test(nativeUnit.trim()) || /^(?:log(?:10)?|ln)\s*\(/i.test(nativeUnit.trim()) || nativeUnit.trim() === '[Fe/H]')
  const shownUnit = ['log10', 'ln'].includes(representation) && !nativeIsCoordinate
    ? (dimensionless && nativeUnit === '1' ? `${representation}（无量纲原生坐标）` : `${representation}（${nativeUnit || '参考单位未明确'}基准）`) : nativeUnit
  const display=limitedValueText(value,ready?derived.limit??source.limit:source.limit)
  const resolvedTaskId = taskId || source.task_id || item.task_id
  return { ...item, task_id: resolvedTaskId, protocol_version: 2, delivery_id: deliveryId, delivery_revision: revision, record_id: source.measurement_id,
    source: { ...source, task_id: resolvedTaskId },
    entity_name: item.target?.main_id || source.target_ref.id, field_name: binding.definition.name_cn,
    property_id: binding.property_id, field_value: display, field_unit: shownUnit, field_representation: representation,
    source_id: source.source_ref.id, source_kind: source.source_kind, extraction_method: source.source_kind,
    uncertainty_source: source.uncertainty, uncertainty_normalized: derived?.uncertainty_typed,
    normalization_status: derived?.status || 'not_run', provenance: { evidence_refs: source.evidence_refs }, raw_text: source.raw_value }
}
export const getRecords = async (taskId,deliveryId,revision,options)=>{
  const rows=await resource(taskId,deliveryId,'records',revision,'&view=list',options)
  const result=rows.map(item=>adaptRecord(item,deliveryId,revision,taskId))
  result.snapshot_ref=rows.snapshot_ref
  return result
}
export const getRecord = async (taskId,deliveryId,revision,recordId,options)=>adaptRecord((await resource(taskId,deliveryId,'records',revision,`&record_id=${id(recordId)}`,options))[0],deliveryId,revision,taskId)
async function readSources(taskId, deliveryId, revision, query, options) {
  const rows = await resource(taskId, deliveryId, 'sources', revision, query, options)
  const sources = rows.map(source => ({ ...source, year:source.work?.records?.[0]?.year ?? source.year, authors:source.work?.records?.[0]?.authors ?? source.authors, abstract:source.work?.records?.[0]?.abstract ?? source.abstract, protocol_version: source.legacy_version === 1 ? 1 : 2, task_id: taskId }))
  sources.snapshot_ref = rows.snapshot_ref
  return sources
}
export const getSources = (taskId, deliveryId, revision, options) => readSources(taskId, deliveryId, revision, '', options)
export const getSourceList = (taskId, deliveryId, revision, options) => readSources(taskId, deliveryId, revision, '&view=list', options)
export const getFigures = (taskId, deliveryId, revision, options) => resource(taskId, deliveryId, 'figures', revision, '', options)
export const getCoverage = (taskId, deliveryId, revision, options) => resource(taskId, deliveryId, 'coverage', revision, '', options)
export const getQuality = async (taskId, deliveryId, revision, options) => {
  const report = await resource(taskId, deliveryId, 'quality', revision, '', options)
  return report.legacy_version === 1 ? report : { protocol_version: 2, delivery_id: deliveryId, report }
}
export const getInsights = async (taskId, deliveryId, revision, options) => {
  const reports = await resource(taskId, deliveryId, 'insights', revision, '', options)
  const report = reports.find(item => item.delivery_id === deliveryId)
  if (!report) return { status:'not_recorded', cards:[], delivery_id:deliveryId, delivery_revision:revision, snapshot_ref:reports.snapshot_ref }
  return report.legacy_report || report
}
export const getDifferences = (taskId, deliveryId, revision, options) => resource(taskId, deliveryId, 'differences', revision, '', options)
export const getMaterials = async (taskId, deliveryId, revision, options) => {
  const rows=await resource(taskId,deliveryId,'materials',revision,'',options)
  const result=rows.map(item=>({...item,task_id:taskId,protocol_version:item.legacy_version===1?1:2}))
  result.snapshot_ref=rows.snapshot_ref
  return result
}
export const getChanges = (taskId, deliveryId, revision, options) => resource(taskId, deliveryId, 'changes', revision, '', options)
export const getActivity = (taskId, deliveryId, revision, options) => resource(taskId, deliveryId, 'changes', revision, '&view=activity', options)
export const getCoverageMatrix = (taskId, deliveryId, revision, options) => resource(taskId, deliveryId, 'coverage', revision, '&view=matrix', options)
export const getMaterial = async (taskId, deliveryId, revision, materialId, options) => (await resource(taskId, deliveryId, 'materials', revision, `&material_id=${id(materialId)}`, options))[0]
export const getExports = async (taskId, deliveryId, revision, options) => (await request(`/tasks/${id(taskId)}/exports`, options)).filter(m=>(!deliveryId||m.delivery_id===deliveryId)&&(!revision||m.delivery_revision===revision)).flatMap(manifest => manifest.artifacts.map(artifact => ({ ...artifact,
  name: artifact.filename || manifest.filename || artifact.artifact_id, display_name: artifact.filename || manifest.filename || `${manifest.format} · ${manifest.selected_count} 条`, size: artifact.byte_size,
  created_at:manifest.created_at, format:manifest.format, selected_count:manifest.selected_count, delivery_revision:manifest.delivery_revision, snapshot_ref:manifest.snapshot_ref, description: `交付修订 ${manifest.delivery_revision}`, delivery_id: manifest.delivery_id, export_id: manifest.export_id })))
export const createExport = (taskId, body) => post(`/tasks/${id(taskId)}/exports`, body)
export const previewExport = (taskId, body, { path, ...options } = {}) =>
  request(`/tasks/${id(taskId)}/exports/preview${path ? '?' + new URLSearchParams({ path }) : ''}`,
    { ...options, method: 'POST', body: JSON.stringify(body) })
export const generateMaterialSummary = (taskId, deliveryId, body) =>
  post(`/tasks/${id(taskId)}/deliveries/${id(deliveryId)}/material-summary`, body)
export async function getWorkbenchPage(taskId, deliveryId, revision, name, query, options) {
  const params = new URLSearchParams(Object.fromEntries(Object.entries({
    view: 'workbench', expected_delivery_revision: revision, delivery_revision: revision, ...query,
  }).filter(([, value]) => value != null && value !== '' && value !== 'all')))
  const result = await request(`/tasks/${id(taskId)}/deliveries/${id(deliveryId)}/${name}?${params}`, options)
  if (result.delivery_id !== deliveryId || result.delivery_revision !== revision)
    throw new Error('结果响应的交付版本不一致')
  if (name === 'material_records') {
    result.items = result.items.map(item => adaptRecord(item, deliveryId, revision, taskId))
  }
  return result
}
export const artifactUrl = (taskId, artifactId) => `${BASE}/tasks/${id(taskId)}/artifacts/${id(artifactId)}`
export const exportFileUrl = artifactUrl
export async function getConfig() { const result = await request('/config'); configRevision = result.saved_revision; return result }
export const getLibraryStatus = () => request('/library-status?view=summary')
export const getKnowledgeContent = otype => request(`/knowledge-content?${new URLSearchParams({ otype })}`)
export async function testAndApplyConfig(values) {
  if (configRevision === null) throw new Error('请先读取当前配置')
  const result = await request('/config/test-and-apply', {method:'POST',headers:{'X-Requested-With':'AstroQuery'},
    body:JSON.stringify({expected_revision:configRevision,values})})
  configRevision = result.saved_revision
  return result
}
export async function putConfig(values) {
  if (configRevision === null) throw new Error('请先读取当前配置')
  const result = await request('/config', { method: 'PUT', headers: { 'X-Requested-With': 'AstroQuery' }, body: JSON.stringify({ expected_revision: configRevision, values }) })
  configRevision = result.saved_revision
  return result
}
const removed = message => Promise.reject(new Error(message))
export const deleteRecord = () => removed('全部合格测量予以保留，请使用本次导出勾选')
export const deleteTask = (taskId, operationId = newOperationId()) => request(`/tasks/${id(taskId)}?operation_id=${id(operationId)}`, { method: 'DELETE' })
export const deleteTaskData = (taskId, parts, operationId = newOperationId()) => request(`/tasks/${id(taskId)}/data`, { method: 'DELETE', body: JSON.stringify({ operation_id: operationId, parts }) })
export const batchDeleteTasks = (taskIds, operationId = newOperationId()) => post('/tasks/batch-delete', { task_ids: taskIds, operation_id: operationId })
export const replayTask = (taskId, speed = 10, operationId = newOperationId()) => post(`/tasks/${id(taskId)}/replay`, { speed, operation_id: operationId })
export const updateTaskTitle = (taskId, title) => request(`/tasks/${id(taskId)}/title`, { method: 'PUT', body: JSON.stringify({ title }) })
export const openFile = (taskId, artifactId) => post(`/tasks/${id(taskId)}/open-file`, { artifact_id: artifactId })
export const eventHistoryUrl = taskId => `${BASE}/tasks/${id(taskId)}/events/history`

/* ── 问答智能体 (Agent Copilot Harness 2.0) ── */
function agentScope(scope) {
  return scope?.delivery_id ? '?' + new URLSearchParams({ delivery_id: scope.delivery_id, delivery_revision: scope.delivery_revision }) : ''
}

export function getAgentMessages(taskId, scope, options) {
  return request(`/tasks/${id(taskId)}/agent/messages${agentScope(scope)}`, options)
}

export function getAgentCitation(taskId, messageId, citationId, scope, options) {
  return request(`/tasks/${id(taskId)}/agent/messages/${id(messageId)}/citations/${id(citationId)}${agentScope(scope)}`, options)
}

export function stopAgentReply(taskId, messageId) {
  return post(`/tasks/${id(taskId)}/agent/messages/${id(messageId)}/stop`, {})
}

export function deleteAgentMessages(taskId) {
  return request(`/tasks/${id(taskId)}/agent/messages`, { method: 'DELETE' })
}

export async function sendAgentChat(taskId, content, onEvent, signal) {
  const url = `${BASE}/tasks/${id(taskId)}/agent/chat`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(typeof content === 'string' ? { query: content } : content),
    signal,
  })
  if (!res.ok) {
    const detail = await res.json().then(body => body.detail, () => null)
    const error = new Error(detail?.message || '暂时无法发送问题')
    error.status = res.status
    error.code = detail?.code
    throw error
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let currentEvent = 'message'
  let currentData = []

  const dispatch = () => {
    if (currentData.length > 0) {
      const raw = currentData.join('\n')
      let payload
      try { payload = JSON.parse(raw) } catch { payload = raw }
      onEvent?.(currentEvent, payload)
      currentData = []
    }
    currentEvent = 'message'
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split(/\r?\n/)
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed) {
        dispatch()
        continue
      }
      if (trimmed.startsWith(':')) {
        continue
      }
      if (trimmed.startsWith('event:')) {
        currentEvent = trimmed.slice(6).trim()
      } else if (trimmed.startsWith('data:')) {
        currentData.push(trimmed.slice(5).trim())
      }
    }
  }

  dispatch()
}

