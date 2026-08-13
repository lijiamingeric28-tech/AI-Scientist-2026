import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

/**
 * Markdown 渲染组件
 * 支持 GFM（表格、任务列表、删除线等）
 */
export default function Markdown({ children, className, ...props }) {
  return (
    <div className={className} style={{ fontSize: 14, lineHeight: 1.7, color: "var(--content-fg-secondary)" }} {...props}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  )
}
