import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'

/* 任务清理确认弹窗（2026-08-24）：
 * - 单个任务：可勾选清理内容（论文 PDF / 图证图片 / 检查点快照 / 事件记录），
 *   或连同任务记录整体删除（勾选后内容项禁用，整删包含全部）
 * - 批量模式：仅整体删除，展示数量
 * 风格对齐 SettingsDialog（玻璃弹窗 + 主题变量）。
 */

const PART_LABELS = {
  pdfs: '论文 PDF 文件',
  figures: '图证图片',
  checkpoints: '检查点快照',
  events: '事件记录',
}

export default function DeleteTaskDialog({ mode = 'single', task, count = 0, onClose, onConfirm }) {
  const [parts, setParts] = useState({ pdfs: true, figures: true, checkpoints: true, events: true })
  const [whole, setWhole] = useState(false)

  // Esc 关闭
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const togglePart = (k) => setParts((p) => ({ ...p, [k]: !p[k] }))

  const handleConfirm = () => {
    if (mode === 'batch') {
      onConfirm({ whole: true, parts: [] })
      return
    }
    onConfirm({ whole, parts: whole ? [] : Object.keys(parts).filter((k) => parts[k]) })
  }

  return (
    <div
      onClick={onClose}
      className="animate-fade-in"
      style={{ position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 160, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="glass animate-drawer-in"
        style={{
          width: 380, maxWidth: '92vw',
          background: 'color-mix(in srgb, var(--seed-surface) 82%, transparent)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-modal)',
          padding: '16px 18px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <Icon.Wrench style={{ color: 'var(--status-warn)' }} />
          <span style={{ fontSize: 15, fontWeight: 590, color: 'var(--content-fg)' }}>
            {mode === 'batch' ? `批量删除 ${count} 个任务` : '清理任务数据'}
          </span>
          <Button variant="ghost" size="icon" onClick={onClose} style={{ marginLeft: 'auto' }}><Icon.Close /></Button>
        </div>

        {mode === 'batch' ? (
          <div className="hint" style={{ margin: '10px 0 4px' }}>
            将删除所选任务的全部记录与关联数据（论文 PDF、图证、检查点、事件、导出文件）。此操作不可恢复。
          </div>
        ) : (
          <>
            <div className="hint" style={{ margin: '10px 0 6px', wordBreak: 'break-all' }}>
              {task?.title || ''}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {Object.entries(PART_LABELS).map(([key, label]) => (
                <label key={key} style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px',
                  borderRadius: 'var(--radius-md)', cursor: whole ? 'default' : 'pointer',
                  background: whole ? 'var(--surface-secondary)' : 'transparent',
                  opacity: whole ? 0.55 : 1,
                }}>
                  <input
                    type="checkbox"
                    checked={whole ? true : parts[key]}
                    disabled={whole}
                    onChange={() => togglePart(key)}
                    style={{ accentColor: 'var(--accent)' }}
                  />
                  <span style={{ fontSize: 13, color: 'var(--content-fg)' }}>{label}</span>
                </label>
              ))}
            </div>
            <label style={{
              display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, padding: '9px 10px',
              borderRadius: 'var(--radius-md)', cursor: 'pointer',
              background: 'var(--status-error-bg)', border: '1px solid color-mix(in srgb, var(--status-error) 30%, transparent)',
            }}>
              <input
                type="checkbox"
                checked={whole}
                onChange={(e) => setWhole(e.target.checked)}
                style={{ accentColor: 'var(--status-error)' }}
              />
              <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--status-error)' }}>
                连同任务记录一起删除（从列表中移除）
              </span>
            </label>
            <div className="hint-dim" style={{ marginTop: 8 }}>
              仅清理内容时任务记录保留，历史结果仍可查看；整体删除不可恢复。
            </div>
          </>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={mode === 'single' && !whole && Object.values(parts).every((v) => !v)}
          >
            {mode === 'batch' ? `删除 ${count} 个任务` : whole ? '删除任务' : '清理所选内容'}
          </Button>
        </div>
      </div>
    </div>
  )
}
