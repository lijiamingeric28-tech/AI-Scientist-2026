import React from 'react'
import { Icon } from '@/components/icons'

/* 穿透式六维强引用徽标（100% 矢量图标，杜绝 Emoji）
 * 映射六类沉淀数据：
 * 1. record: 结构化记录（森林绿）
 * 2. source: 文献与页码（图表蓝）
 * 3. figure: 科学图表证据（鼠尾草绿）
 * 4. conflict: 冲突仲裁案卷（暖琥珀色）
 * 5. definition: 物理量约定与量纲（紫灰色）
 * 6. theory: 294 理论知识库与公式（靛青色）
 */

export default function CitationBadge({ type, id, label, payload, onClick }) {
  const handleClick = (e) => {
    e.preventDefault()
    e.stopPropagation()
    onClick?.({ type, id, label, payload })
  }

  if (type === 'record') {
    return (
      <span
        onClick={handleClick}
        className="citation-badge citation-record"
        title={`点击查看测定记录详情 (${id})`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '1.5px 8px',
          margin: '0 2px',
          borderRadius: 'var(--radius-pill)',
          background: 'var(--accent-light)',
          border: '1px solid color-mix(in srgb, var(--accent) 30%, transparent)',
          color: 'var(--accent-text)',
          fontSize: 12,
          fontWeight: 500,
          cursor: 'pointer',
          verticalAlign: 'baseline',
          transition: 'all 0.15s ease',
        }}
      >
        <Icon.Hash style={{ width: 11, height: 11, flexShrink: 0 }} />
        <span>{label || id}</span>
      </span>
    )
  }

  if (type === 'source') {
    return (
      <span
        onClick={handleClick}
        className="citation-badge citation-source"
        title={`点击查阅文献资料与原文 (${id})`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '1.5px 8px',
          margin: '0 2px',
          borderRadius: 'var(--radius-pill)',
          background: 'var(--chart-blue-light, rgba(74, 108, 247, 0.08))',
          border: '1px solid color-mix(in srgb, var(--chart-blue, #4a6cf7) 30%, transparent)',
          color: 'var(--chart-blue, #4a6cf7)',
          fontSize: 12,
          fontWeight: 500,
          cursor: 'pointer',
          verticalAlign: 'baseline',
          transition: 'all 0.15s ease',
        }}
      >
        <Icon.FileText style={{ width: 11, height: 11, flexShrink: 0 }} />
        <span>{label || id}</span>
      </span>
    )
  }

  if (type === 'figure') {
    return (
      <span
        onClick={handleClick}
        className="citation-badge citation-figure"
        title={`点击展开多模态图证切片与 PDF 标注 (${id})`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '1.5px 8px',
          margin: '0 2px',
          borderRadius: 'var(--radius-pill)',
          background: 'color-mix(in srgb, var(--seed-accent) 8%, transparent)',
          border: '1px solid color-mix(in srgb, var(--seed-accent) 25%, transparent)',
          color: 'var(--seed-accent)',
          fontSize: 12,
          fontWeight: 500,
          cursor: 'pointer',
          verticalAlign: 'baseline',
          transition: 'all 0.15s ease',
        }}
      >
        <Icon.Image style={{ width: 11, height: 11, flexShrink: 0 }} />
        <span>{label || id}</span>
      </span>
    )
  }

  if (type === 'conflict') {
    return (
      <span
        onClick={handleClick}
        className="citation-badge citation-conflict"
        title={`点击查看质量管线冲突仲裁案卷 (${id})`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '1.5px 8px',
          margin: '0 2px',
          borderRadius: 'var(--radius-pill)',
          background: 'var(--status-warning-bg, rgba(234, 138, 0, 0.08))',
          border: '1px solid color-mix(in srgb, var(--status-warning, #ea8a00) 30%, transparent)',
          color: 'var(--status-warning, #ea8a00)',
          fontSize: 12,
          fontWeight: 500,
          cursor: 'pointer',
          verticalAlign: 'baseline',
          transition: 'all 0.15s ease',
        }}
      >
        <Icon.Scale style={{ width: 11, height: 11, flexShrink: 0 }} />
        <span>{label || id}</span>
      </span>
    )
  }

  if (type === 'definition') {
    return (
      <span
        onClick={handleClick}
        className="citation-badge citation-definition"
        title={`点击查看天体物理量规范与约定 (${id})`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '1.5px 8px',
          margin: '0 2px',
          borderRadius: 'var(--radius-pill)',
          background: 'rgba(139, 92, 246, 0.08)',
          border: '1px solid rgba(139, 92, 246, 0.25)',
          color: '#8b5cf6',
          fontSize: 12,
          fontWeight: 500,
          cursor: 'pointer',
          verticalAlign: 'baseline',
          transition: 'all 0.15s ease',
        }}
      >
        <Icon.HelpCircle style={{ width: 11, height: 11, flexShrink: 0 }} />
        <span>{label || id}</span>
      </span>
    )
  }

  if (type === 'theory') {
    return (
      <span
        onClick={handleClick}
        className="citation-badge citation-theory"
        title={`点击查阅天体物理理论底座与推演方程 (${id})`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '1.5px 8px',
          margin: '0 2px',
          borderRadius: 'var(--radius-pill)',
          background: 'rgba(14, 165, 233, 0.08)',
          border: '1px solid rgba(14, 165, 233, 0.25)',
          color: '#0284c7',
          fontSize: 12,
          fontWeight: 500,
          cursor: 'pointer',
          verticalAlign: 'baseline',
          transition: 'all 0.15s ease',
        }}
      >
        <Icon.Sparkle style={{ width: 11, height: 11, flexShrink: 0 }} />
        <span>{label || id}</span>
      </span>
    )
  }

  return (
    <span
      onClick={handleClick}
      className="citation-badge"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '1.5px 8px',
        margin: '0 2px',
        borderRadius: 'var(--radius-pill)',
        background: 'var(--surface-secondary)',
        border: '1px solid var(--surface-border)',
        fontSize: 12,
        color: 'var(--content-fg)',
        cursor: 'pointer',
      }}
    >
      <span>{label || id}</span>
    </span>
  )
}
