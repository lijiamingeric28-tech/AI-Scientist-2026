/* P1-5：日志结构化行（级别胶囊 + 节点胶囊 + 常规字体换行正文）
 *
 * 取消整块 mono/nowrap 的终端风平铺（LogDrawer 与下钻 LogBox 曾各自实现），
 * 统一为：时间（灰 mono）+ 级别胶囊（INFO 蓝 / DEBUG 灰 / WARN 黄 / ERROR 红）
 * + 节点胶囊（accent 浅底）+ 正文（常规字体、自动换行、ERROR 红字）。
 */

const LEVEL_STYLE = {
  INFO: { color: 'var(--log-info-text, #174066)', bg: 'var(--log-info-bg, #B6D2E8)' },
  DEBUG: { color: 'var(--content-fg-tertiary)', bg: 'var(--surface-secondary)' },
  WARN: { color: 'var(--log-warn-text, #713f12)', bg: 'var(--log-warn-bg, #FDEB9C)' },
  WARNING: { color: 'var(--log-warn-text, #713f12)', bg: 'var(--log-warn-bg, #FDEB9C)' },
  ERROR: { color: 'var(--log-error-text, #991b1b)', bg: 'var(--log-error-bg, #F8C4C4)' },
  ERR: { color: 'var(--log-error-text, #991b1b)', bg: 'var(--log-error-bg, #F8C4C4)' },
}

export default function LogLine({ l }) {
  const rawLevel = String(l.level || 'INFO').toUpperCase()
  const level = (rawLevel === 'WARNING' || rawLevel === 'WARN')
    ? 'WARN'
    : (rawLevel === 'ERROR' || rawLevel === 'ERR')
      ? 'ERROR'
      : rawLevel
  const ls = LEVEL_STYLE[level] || LEVEL_STYLE[rawLevel] || LEVEL_STYLE.INFO
  return (
    <div className="log-line" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-start', lineHeight: 1.75, fontSize: 13 }}>
      {l.time && (
        <span className="font-mono" style={{ flexShrink: 0, fontSize: 11, color: 'var(--content-fg-tertiary)', paddingTop: 1 }}>
          {l.time}
        </span>
      )}
      <span
        style={{
          flexShrink: 0, fontSize: 11, fontWeight: 510,
          color: ls.color, background: ls.bg,
          padding: '0 6px', borderRadius: 'var(--radius-pill)', marginTop: 1,
        }}
      >
        {level}
      </span>
      {l.node && (
        <span
          style={{
            flexShrink: 0, fontSize: 11, padding: '0 6px', borderRadius: 'var(--radius-pill)',
            background: 'var(--accent-light)', color: 'var(--accent-text)', marginTop: 1,
          }}
        >
          {l.node}
        </span>
      )}
      <span
        style={{
          flex: '1 1 160px', minWidth: 0, color: level === 'ERROR' ? 'var(--status-error)' : 'var(--content-fg-secondary)',
          wordBreak: 'break-word',
        }}
      >
        {l.message}
      </span>
    </div>
  )
}
