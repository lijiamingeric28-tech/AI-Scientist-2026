import { createContext, useCallback, useContext, useRef, useState } from 'react'

/* Toast 通知系统（块 7 定案：右上角浮出，自动消失）
 * 用法：const { toast } = useToast(); toast('仅支持 PDF 文件', 'error')
 */

const ToastContext = createContext(null)

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const seqRef = useRef(0)

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const toast = useCallback(
    (message, type = 'info', duration = 3000) => {
      const id = ++seqRef.current
      setToasts((prev) => [...prev, { id, message, type }])
      setTimeout(() => dismiss(id), duration)
    },
    [dismiss]
  )

  const colors = {
    info: { bg: 'var(--surface-bg)', border: 'var(--surface-border)', icon: 'var(--status-progress)' },
    error: { bg: 'var(--status-error-bg)', border: 'var(--status-error)', icon: 'var(--status-error)' },
    success: { bg: 'var(--status-success-bg)', border: 'var(--status-success)', icon: 'var(--status-success)' },
  }

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      {/* Toast 容器：右上角 */}
      <div style={{ position: 'fixed', top: 16, right: 16, zIndex: 200, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {toasts.map((t) => {
          const c = colors[t.type] || colors.info
          return (
            <div
              key={t.id}
              onClick={() => dismiss(t.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '10px 14px',
                background: c.bg,
                border: `1px solid ${c.border}`,
                borderRadius: 8,
                boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
                fontSize: 13,
                color: 'var(--content-fg)',
                cursor: 'pointer',
                maxWidth: 360,
                animation: 'slide-in-right 0.2s ease-out',
              }}
            >
              <span style={{ color: c.icon, fontWeight: 510 }}>{t.type === 'error' ? '✕' : t.type === 'success' ? '✓' : '●'}</span>
              <span>{t.message}</span>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast 必须在 ToastProvider 内使用')
  return ctx
}
