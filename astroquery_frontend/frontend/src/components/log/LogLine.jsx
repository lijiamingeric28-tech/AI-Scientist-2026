/* P1-5：日志结构化行（级别胶囊 + 节点胶囊 + 常规字体换行正文）
 *
 * 取消整块 mono/nowrap 的终端风平铺（LogDrawer 与下钻 LogBox 曾各自实现），
 * 统一为：时间（灰 mono）+ 级别胶囊（INFO 蓝 / DEBUG 灰 / WARN 黄 / ERROR 红）
 * + 节点胶囊（accent 浅底）+ 正文（常规字体、自动换行、ERROR 红字）。
 */

const LEVEL_STYLE = {
  INFO: { color: 'var(--status-progress)', bg: 'var(--status-progress-bg)' },
  DEBUG: { color: 'var(--content-fg-tertiary)', bg: 'var(--surface-secondary)' },
  WARNING: { color: 'var(--status-warn)', bg: 'var(--status-warn-bg)' },
  ERROR: { color: 'var(--status-error)', bg: 'var(--status-error-bg)' },
}

export default function LogLine({ l }) {
  const level = String(l.level || 'INFO').toUpperCase()
  const ls = LEVEL_STYLE[level] || LEVEL_STYLE.INFO
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start', lineHeight: 1.55, fontSize: 12 }}>
      {l.time && (
        <span className="font-mono" style={{ flexShrink: 0, fontSize: 11, color: 'var(--content-fg-tertiary)', paddingTop: 1 }}>
          {l.time}
        </span>
      )}
      <span
        style={{
          flexShrink: 0, fontSize: 10, fontWeight: 510,
          color: ls.color, background: ls.bg,
          padding: '0 6px', borderRadius: 'var(--radius-pill)', marginTop: 1,
        }}
      >
        {level}
      </span>
      {l.node && (
        <span
          style={{
            flexShrink: 0, fontSize: 10, padding: '0 6px', borderRadius: 'var(--radius-pill)',
            background: 'var(--accent-light)', color: 'var(--accent-text)', marginTop: 1,
          }}
        >
          {l.node}
        </span>
      )}
      <span
        style={{
          flex: 1, color: level === 'ERROR' ? 'var(--status-error)' : 'var(--content-fg-secondary)',
          wordBreak: 'break-word',
        }}
      >
        {l.message}
      </span>
    </div>
  )
}
