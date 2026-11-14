import { Suspense, lazy, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import '@/components/knowledge/knowledgeWorkspace.css'

const KnowledgeWorkspace = lazy(() => import('@/components/knowledge/KnowledgeWorkspace'))

export default function SettingsKnowledgeStudio({
  open,
  dismissal,
  initialMode = 'graph',
  knowledgeContext,
  initialEntryId = null,
  onBackToSettings,
  onClose,
}) {
  // SettingsDialog owns the entire exit; do not chain a second dismissal here.
  const studioRef = useDialogFocus(open, onClose)
  const studioMemory = useMemo(() => initialEntryId ? { selectedId: initialEntryId, detailOpen: true } : {}, [initialEntryId])

  if (!open) return null

  const task = knowledgeContext?.task || null
  const pipeline = knowledgeContext?.pipeline || null
  const taskLabel = task?.title || pipeline?.presentation?.target?.main_id || task?.target?.main_id || ''

  return (
    <div
      className="settings-overlay"
      data-closing={dismissal.closing || undefined}
      onClick={onClose}
    >
      <section
        ref={studioRef}
        data-closing={dismissal.closing || undefined}
        onAnimationEnd={dismissal.onAnimationEnd}
        onKeyDownCapture={dismissal.onKeyDownCapture}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-studio-title"
        className="settings-studio-dialog kwb-studio animate-modal-in"
        onClick={event => event.stopPropagation()}
      >
        <div className="settings-studio-body">
          <Suspense
            fallback={
              <div style={{ padding: 32, color: 'var(--text-secondary)', fontSize: 13 }}>
                正在加载知识图谱与理论库工作台…
              </div>
            }
          >
            <KnowledgeWorkspace
              task={task}
              pipeline={pipeline}
              active={open}
              initialMode={initialMode}
              memory={studioMemory}
              renderHeader={({ total, readOnly, pending, stale, onCreate }) => (
                <header className="kwb-studio-header">
                  <div className="kwb-title-group">
                    <button type="button" className="kwb-back-button" onClick={onBackToSettings} aria-label="返回设置"><Icon.ArrowLeft /><span>返回设置</span></button>
                    <span className="kwb-header-divider" aria-hidden="true" />
                    <Icon.Network />
                    <h2 id="settings-studio-title">知识图谱与理论库</h2>
                    <span className="kwb-header-count">{Number.isFinite(total) ? total.toLocaleString('zh-CN') : '—'} 条{pending ? ' · 更新中' : stale ? ' · 上次读取' : ''}</span>
                    {taskLabel && <span className="kwb-task-context" title={`当前任务：${taskLabel}`}>{taskLabel}</span>}
                  </div>
                  <div className="kwb-header-actions">
                    <Button variant="accent" size="sm" disabled={readOnly} onClick={onCreate}><Icon.Plus /><span>新增知识</span></Button>
                    <button type="button" className="kwb-close-button" onClick={onClose} aria-label="关闭设置工作台"><Icon.Close /></button>
                  </div>
                </header>
              )}
            />
          </Suspense>
        </div>
      </section>
    </div>
  )
}
