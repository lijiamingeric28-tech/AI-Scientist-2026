import { Button } from '@/components/ui/button'

export default function ResourceState({ resource, label, onRetry, children }) {
  if (!resource || resource.status === 'waiting') return <p className="hint" role="status">{resource?.ended ? `本次任务未生成${label}，可查看已有执行内容。` : `${label}将在任务完成后统一展示`}</p>
  const hasData = resource.data != null
  if (!hasData && ['idle', 'loading', 'settling'].includes(resource.status)) return <p className="hint" role="status">{label}整理中…</p>
  return <>{resource.status === 'error' && <div className="resource-error" role="alert">{label}读取失败：{resource.error}<Button variant="outline" size="sm" onClick={onRetry}>重试</Button></div>}{resource.refreshing && hasData && <p className="hint" role="status">正在刷新{label}…</p>}{hasData && children}</>
}
