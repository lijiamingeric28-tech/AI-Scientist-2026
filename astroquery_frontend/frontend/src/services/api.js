/* API 服务层 —— 契约 docs/API_CONTRACT.md（10 轮定稿）
 * 后端：web.main（FastAPI :8000）。前端 dev 走 Vite proxy（vite.config.js）。
 */

// M-20③: 部署地址环境注入（VITE_API_BASE，如 '/astro/api'）；默认同源 /api
const BASE = (import.meta.env?.VITE_API_BASE || '/api').replace(/\/+$/, '')

/* L-03：错误体归一——FastAPI detail 可能是数组（422 校验）/对象/字符串；
 * 此前 toast 直接显示 [object Object] 不可读 */
function formatErrorDetail(detail) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d) => {
      if (d && typeof d === 'object') {
        const loc = Array.isArray(d.loc) ? d.loc.join('.') : ''
        return `${loc ? loc + ': ' : ''}${d.msg ?? ''}`
      }
      return String(d)
    }).join('; ')
  }
  if (detail && typeof detail === 'object') {
    try { return JSON.stringify(detail) } catch { /* fallthrough */ }
  }
  return String(detail ?? '请求失败')
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
    ...options,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? body
    } catch { /* 空 body / 非 JSON */ }
    throw new Error(formatErrorDetail(detail))
  }
  return res.json()
}

/* ── 上传 / 任务 ── */
export async function uploadFiles(fileList) {
  const fd = new FormData()
  fileList.forEach((f) => fd.append('files', f))
  // H-03：res.ok 检查——4xx/5xx 不再静默解析错误体当成功（此前 up.pdf_ids
  // undefined → 前端静默以空列表建任务，用户以为上传成功）
  const res = await fetch(`${BASE}/upload`, { method: 'POST', body: fd })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? body
    } catch { /* ignore */ }
    throw new Error(formatErrorDetail(detail))
  }
  return res.json()
}

export function createTask(query, pdfIds) {
  return request('/tasks', {
    method: 'POST',
    body: JSON.stringify({ query, pdf_ids: pdfIds }),
  })
}

export function listTasks(limit = 50, offset = 0, status) {
  const q = new URLSearchParams({ limit, offset })
  if (status) q.set('status', status)
  return request(`/tasks?${q}`)
}

export function getTask(taskId) {
  return request(`/tasks/${taskId}`)
}

export function getState(taskId) {
  return request(`/tasks/${taskId}/state`)
}

export function resumeTask(taskId, answer) {
  return request(`/tasks/${taskId}/resume`, {
    method: 'POST',
    body: JSON.stringify({ answer }),
  })
}

export function cancelTask(taskId) {
  return request(`/tasks/${taskId}/cancel`, { method: 'POST' })
}

export function retryTask(taskId) {
  return request(`/tasks/${taskId}/retry`, { method: 'POST' })
}

/* ── 结果（重度数据 HTTP） ── */
export function getRecords(taskId) {
  return request(`/tasks/${taskId}/records`)
}

export function getSources(taskId) {
  return request(`/tasks/${taskId}/sources`)
}

export function getFigures(taskId) {
  return request(`/tasks/${taskId}/figures`)
}

export function getQuality(taskId) {
  return request(`/tasks/${taskId}/quality`)
}

export function getExports(taskId) {
  return request(`/tasks/${taskId}/exports`)
}

// L-13: 打开输出文件（契约 D9-3：后端 os.startfile 本地打开）
export function openFile(taskId, name) {
  return request(`/tasks/${taskId}/open-file`, {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

/* ── 事件流（SSE） ── */
export function openEventStream(taskId, handlers, afterSeq = 0) {
  const es = new EventSource(`${BASE}/tasks/${taskId}/events?after_seq=${afterSeq}`)
  es.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data)
      handlers.onEvent?.(data)
    } catch { /* ignore */ }
  }
  es.onerror = () => {
    // EventSource 自动重连（契约 D1-4）；断线重连后 from 续播由 hook 管理
    handlers.onError?.()
  }
  return es
}

/* ── 配置（契约 D10） ── */
export function getConfig() {
  return request('/config')
}

export function putConfig(body) {
  // H-05④: 自定义头触发 CORS preflight——跨源 PUT 在预检阶段即被白名单拒绝
  // （后端同时校验该头），防任意网页改 base_url 投毒
  return request('/config', {
    method: 'PUT',
    body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'AstroQuery' },
  })
}