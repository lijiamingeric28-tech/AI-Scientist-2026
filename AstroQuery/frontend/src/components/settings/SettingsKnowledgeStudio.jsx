import { Suspense, lazy, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import { useDismissTransition } from '@/hooks/useDismissTransition'

const KnowledgeWorkspace = lazy(() => import('@/components/knowledge/KnowledgeWorkspace'))

export default function SettingsKnowledgeStudio({
  open,
  initialMode = 'graph',
  knowledgeContext,
  onBackToSettings,
  onClose,
}) {
  const dismissal = useDismissTransition(() => onClose?.(), { active: open })
  const studioRef = useDialogFocus(open, () => onBackToSettings?.())
  const studioMemory = useMemo(() => ({}), [])

  if (!open) return null

  const task = knowledgeContext?.task || null
  const pipeline = knowledgeContext?.pipeline || null
  const taskLabel = task?.title || pipeline?.presentation?.target?.main_id || task?.target?.main_id || ''

  return (
    <div
      className="settings-overlay"
      data-closing={dismissal.closing || undefined}
      onClick={dismissal.close}
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
        className="settings-studio-dialog animate-modal-in"
        onClick={event => event.stopPropagation()}
      >
        <header className="settings-studio-header">
          <div className="settings-studio-header-left">
            <Button
              variant="outline"
              size="sm"
              onClick={onBackToSettings}
              aria-label="返回设置"
            >
              <Icon.ArrowLeft style={{ width: 14, height: 14 }} />
              <span>返回设置</span>
            </Button>

            <nav className="settings-studio-breadcrumb" aria-label="设置导航路径">
              <span>设置</span>
              <span aria-hidden="true">/</span>
              <strong id="settings-studio-title">知识图谱与理论库配置</strong>
            </nav>

            {taskLabel && (
              <span className="settings-studio-context-pill" title={taskLabel}>
                当前背景任务：{taskLabel}
              </span>
            )}
          </div>

          <div className="settings-studio-header-right">
            <span className="settings-studio-mode-hint">大尺寸工作台模式</span>
            <Button
              variant="outline"
              size="sm"
              onClick={dismissal.close}
              aria-label="关闭设置工作台"
            >
              <Icon.Close style={{ width: 13, height: 13 }} />
              <span>关闭</span>
            </Button>
          </div>
        </header>

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
            />
          </Suspense>
        </div>
      </section>
    </div>
  )
}
