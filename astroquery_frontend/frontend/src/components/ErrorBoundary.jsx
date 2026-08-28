import React from 'react'

/* 全局错误边界（2026-08-27）：渲染崩溃时显示可诊断的错误信息而非整页白屏。
 * 白屏 = React 未捕获异常（updater 纯函数被破坏/StrictMode 双调等）——
 * 边界兜底保 UI 存活 + 暴露错误堆栈，便于定位而非静默。 */

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // 收集到 window 供调试
    window.__lastRenderError = { error: String(error), stack: info?.componentStack }
    console.error('[ErrorBoundary] 渲染异常:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 24, color: 'var(--content-fg)' }}>
          <div style={{ fontSize: 14, fontWeight: 590, color: 'var(--status-error)', marginBottom: 8 }}>
            界面渲染出错（可尝试刷新或切换任务）
          </div>
          <div
            className="font-mono"
            style={{
              fontSize: 11, background: 'var(--surface-secondary)', borderRadius: 6,
              padding: '10px 12px', maxHeight: 320, overflowY: 'auto', wordBreak: 'break-all',
            }}
          >
            {String(this.state.error)}
          </div>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              marginTop: 10, border: 'none', background: 'var(--accent)', color: 'var(--accent-on)',
              fontSize: 12, padding: '4px 14px', borderRadius: 6, cursor: 'pointer',
            }}
          >
            重试渲染
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
