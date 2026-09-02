import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

/* Markdown 渲染组件
 * 支持 GFM（表格、任务列表、删除线等）
 * P1-7：components 样式覆盖 — 标题/列表/表格/code/引用/链接统一走 CSS 变量
 * 与工作流卡片体系（圆角/二级底色/等宽 code），替代 react-markdown 默认样式。
 */

const components = {
  p: ({ children }) => <p style={{ margin: '0 0 8px' }}>{children}</p>,
  strong: ({ children }) => <strong style={{ fontWeight: 590, color: 'var(--content-fg)' }}>{children}</strong>,
  em: ({ children }) => <em style={{ color: 'var(--content-fg-secondary)' }}>{children}</em>,
  ul: ({ children }) => <ul style={{ margin: '0 0 8px', paddingLeft: 20 }}>{children}</ul>,
  ol: ({ children }) => <ol style={{ margin: '0 0 8px', paddingLeft: 20 }}>{children}</ol>,
  li: ({ children }) => <li style={{ marginBottom: 4 }}>{children}</li>,
  code: ({ children }) => (
    <code style={{ fontFamily: 'ui-monospace, Menlo, Consolas, monospace', fontSize: '0.92em', background: 'var(--surface-secondary)', padding: '1px 5px', borderRadius: 4, color: 'var(--accent-text)' }}>
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre style={{ margin: '0 0 8px', padding: '8px 10px', background: 'var(--surface-secondary)', borderRadius: 'var(--radius-md)', overflowX: 'auto', fontFamily: 'ui-monospace, Menlo, Consolas, monospace', fontSize: '0.9em', lineHeight: 1.6 }}>
      {children}
    </pre>
  ),
  blockquote: ({ children }) => (
    <blockquote style={{ margin: '0 0 8px', padding: '4px 12px', borderLeft: '3px solid var(--accent-light)', color: 'var(--content-fg-secondary)', background: 'var(--surface-secondary)', borderRadius: '0 var(--radius-md) var(--radius-md) 0' }}>
      {children}
    </blockquote>
  ),
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-text)' }}>{children}</a>
  ),
  h1: ({ children }) => <h1 style={{ fontSize: 17, fontWeight: 590, margin: '0 0 8px', color: 'var(--content-fg)' }}>{children}</h1>,
  h2: ({ children }) => <h2 style={{ fontSize: 15, fontWeight: 590, margin: '0 0 8px', color: 'var(--content-fg)' }}>{children}</h2>,
  h3: ({ children }) => <h3 style={{ fontSize: 13.5, fontWeight: 590, margin: '0 0 8px', color: 'var(--content-fg)' }}>{children}</h3>,
  h4: ({ children }) => <h4 style={{ fontSize: 13, fontWeight: 590, margin: '0 0 8px', color: 'var(--content-fg)' }}>{children}</h4>,
  table: ({ children }) => (
    <div style={{ overflowX: 'auto', margin: '0 0 8px' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: 12.5, width: '100%' }}>{children}</table>
    </div>
  ),
  th: ({ children }) => <th style={{ border: '1px solid var(--surface-border)', padding: '5px 8px', background: 'var(--surface-secondary)', textAlign: 'left', fontWeight: 590 }}>{children}</th>,
  td: ({ children }) => <td style={{ border: '1px solid var(--surface-border)', padding: '5px 8px' }}>{children}</td>,
  img: ({ src, alt }) => <img src={src} alt={alt} style={{ maxWidth: '100%', borderRadius: 'var(--radius-md)' }} />,
  hr: () => <hr style={{ border: 'none', borderTop: '1px solid var(--surface-border)', margin: '10px 0' }} />,
}

export default function Markdown({ children, className, ...props }) {
  return (
    <div className={className} style={{ fontSize: 14, lineHeight: 1.7, color: "var(--content-fg-secondary)" }} {...props}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{children}</ReactMarkdown>
    </div>
  )
}
