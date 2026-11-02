import React from 'react'
import { Icon } from '@/components/icons'

/* 穿透式四维强引用徽标（100% 矢量图标，杜绝 Emoji）
 * 映射四类沉淀数据：
 * 1. REC: 结构化记录（森林绿）
 * 2. SOURCE: 文献与页码（图表蓝）
 * 3. FIG: 科学图表证据（鼠尾草绿）
 * 4. ARB: 冲突仲裁案卷（暖琥珀色）
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
        title={`点击查阅 ADS 文献摘要 (${id})`}
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
      >
        <Icon.Scale style={{ width: 11, height: 11, flexShrink: 0 }} />
        <span>{label || id}</span>
      </span>
    )
  }

  return (
    <span onClick={handleClick} className="citation-badge">
      <span>{label || id}</span>
    </span>
  )
}
