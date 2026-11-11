import React, { useState, useMemo } from 'react'
import { Icon } from '@/components/icons'
import { LatexMath, LatexText } from '@/components/results/LatexMath'
import {
  getCategoryInfo,
  isValidFormula,
  translateProperty,
  translateEdgeLabel,
} from './knowledgeConstants'

export default function KnowledgeDrawer({
  item,
  categories = [],
  allNodes = [],
  topologyLinks = [],
  onClose,
  onSelectNode,
  onTogglePreference,
  onEdit,
  onFork,
  onDelete,
  onRestore,
}) {
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)

  const nodeById = useMemo(() => {
    const map = new Map()
    for (const n of allNodes) {
      if (n?.id) map.set(n.id, n)
    }
    return map
  }, [allNodes])

  if (!item) return null

  const isPropertyHub = Boolean(item.is_property)
  const isPreferred = Boolean(item.preferred || item.user_preference === 'preferred')
  const catInfo = getCategoryInfo(item.category, categories)

  // 过滤内部英文枚举伪假定，只保留真正学术物理条件
  const validConditions = Array.isArray(item.conditions)
    ? item.conditions.filter(c => {
        const s = String(typeof c === 'string' ? c : c?.text || '').trim().toLowerCase()
        return s && !['established', 'consensus', 'provisional', 'empirical'].includes(s)
      })
    : []

  // 关联拓扑连线
  const relatedLinks = topologyLinks.filter(
    l => (l.source?.id || l.source) === item.id || (l.target?.id || l.target) === item.id
  )

  return (
    <>
      {/* 全屏毛玻璃背景遮罩 */}
      <div
        className="kw-drawer-backdrop"
        onClick={onClose}
        aria-label="关闭侧边栏"
      />

      {/* 560px 宽度统一 ContextDrawer 风格抽屉 */}
      <aside
        className="kw-graph-drawer"
        role="dialog"
        aria-label={item.label || item.title || item.name || '理论详情'}
      >
        <header className="kw-drawer-header">
          <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <span
                className="kw-badge"
                style={{
                  background: `${catInfo.color}20`,
                  color: catInfo.color,
                  border: `1px solid ${catInfo.color}40`,
                }}
              >
                {catInfo.label}
              </span>
              {item.confidence_label && (
                <span
                  className="kw-badge"
                  style={{
                    background: 'rgba(16, 185, 129, 0.12)',
                    color: '#059669',
                    border: '1px solid rgba(16, 185, 129, 0.28)',
                  }}
                >
                  {item.confidence_label}
                </span>
              )}
              {isPreferred && (
                <span
                  className="kw-badge"
                  style={{
                    background: 'rgba(234, 179, 8, 0.15)',
                    color: '#d97706',
                    border: '1px solid rgba(234, 179, 8, 0.35)',
                  }}
                >
                  科研优选
                </span>
              )}
              {item.is_override && (
                <span
                  className="kw-badge"
                  style={{
                    background: 'rgba(59, 130, 246, 0.15)',
                    color: '#2563eb',
                    border: '1px solid rgba(59, 130, 246, 0.35)',
                  }}
                >
                  用户自定义已修改
                </span>
              )}
              {item.is_user && !item.is_override && (
                <span
                  className="kw-badge"
                  style={{
                    background: 'rgba(234, 179, 8, 0.15)',
                    color: '#d97706',
                    border: '1px solid rgba(234, 179, 8, 0.35)',
                  }}
                >
                  自建理论
                </span>
              )}
            </div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 650, color: 'var(--content-fg)', lineHeight: 1.4 }}>
              {item.title || item.label || item.name}
            </h3>
          </div>
          <button
            type="button"
            className="kw-icon-btn"
            onClick={onClose}
            aria-label="关闭详情"
          >
            <Icon.Close style={{ width: 16, height: 16 }} />
          </button>
        </header>

        <div className="kw-drawer-body">
          {/* Universal 操作按钮行：科研优选、编辑理论、派生理论、删除、恢复默认 (非物理量枢纽节点可见) */}
          {!isPropertyHub && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <button
                type="button"
                className={`kw-filter-pref-btn ${isPreferred ? 'active' : ''}`}
                style={{ flex: 1, minWidth: 140, justifyContent: 'center' }}
                onClick={() => onTogglePreference?.(item.id, !isPreferred)}
              >
                {isPreferred ? (
                  <Icon.StarFilled style={{ width: 14, height: 14 }} />
                ) : (
                  <Icon.Star style={{ width: 14, height: 14 }} />
                )}
                <span>{isPreferred ? '已设为科研优选' : '设为科研优选'}</span>
              </button>

              {/* 编辑理论 */}
              <button
                type="button"
                className="kw-filter-pref-btn"
                onClick={() => onEdit?.(item)}
                title="直接修改该理论内容与分类"
              >
                <Icon.Edit style={{ width: 14, height: 14 }} />
                <span>编辑理论</span>
              </button>

              {/* 派生理论 */}
              <button
                type="button"
                className="kw-filter-pref-btn"
                onClick={() => onFork?.(item)}
                title="以此理论为模板派生新知识"
              >
                <Icon.Fork style={{ width: 14, height: 14 }} />
                <span>派生</span>
              </button>

              {/* 删除理论 */}
              <button
                type="button"
                className="kw-filter-pref-btn"
                style={{ color: 'var(--status-error, #ef4444)' }}
                onClick={() => setDeleteConfirmOpen(true)}
                title="从理论知识库中删除此条目"
              >
                <Icon.Trash style={{ width: 14, height: 14 }} />
                <span>删除</span>
              </button>

              {/* 仅在用户实际修改过内置条目时才显示恢复出厂默认按钮 */}
              {Boolean(item.is_override) && (
                <button
                  type="button"
                  className="kw-filter-pref-btn"
                  onClick={() => {
                    onRestore?.(item.id)
                    onClose?.()
                  }}
                  title="清除全部修改，重置为系统出厂预置状态"
                >
                  <Icon.History style={{ width: 14, height: 14 }} />
                  <span>恢复默认</span>
                </button>
              )}
            </div>
          )}

          {isPropertyHub && (
            <div
              style={{
                padding: '10px 12px',
                borderRadius: 8,
                background: 'var(--surface-secondary, rgba(0, 0, 0, 0.02))',
                border: '1px solid var(--surface-border)',
                fontSize: 12.5,
                lineHeight: 1.6,
                color: 'var(--content-fg-secondary)',
              }}
            >
              天体物理核心观测量拓扑枢纽 —— 汇集知识图谱中约束、推演或依赖该物理量的理论定律与检验方法。点击下方关联条目可直接跳转浏览详情。
            </div>
          )}

          {/* 删除确认对话框 */}
          {deleteConfirmOpen && (
            <div
              style={{
                padding: 12,
                background: 'rgba(239, 68, 68, 0.08)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: 8,
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
              }}
            >
              <div style={{ fontSize: 13, color: 'var(--content-fg)', fontWeight: 500 }}>
                确定要从知识库中删除「{item.title || item.label || item.name}」吗？
              </div>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  className="kw-mode-btn"
                  style={{ padding: '4px 10px', fontSize: 12 }}
                  onClick={() => setDeleteConfirmOpen(false)}
                >
                  取消
                </button>
                <button
                  type="button"
                  style={{
                    padding: '4px 12px',
                    fontSize: 12,
                    background: 'var(--status-error, #ef4444)',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 6,
                    cursor: 'pointer',
                  }}
                  onClick={() => {
                    setDeleteConfirmOpen(false)
                    onDelete?.(item.id)
                    onClose?.()
                  }}
                >
                  确认删除
                </button>
              </div>
            </div>
          )}

          {/* 纯正 LaTeX 数学公式 */}
          {item.formula && isValidFormula(item.formula) && (
            <div className="kw-formula-box">
              <LatexMath math={item.formula} displayMode />
            </div>
          )}

          {/* 核心理论机制阐述 */}
          {(item.description || (item.formula && !isValidFormula(item.formula))) && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--content-fg-secondary)' }}>
                核心理论机制阐述
              </span>
              <div
                style={{
                  margin: 0,
                  fontSize: 13,
                  lineHeight: 1.68,
                  color: 'var(--content-fg)',
                  whiteSpace: 'pre-line',
                  wordBreak: 'break-word',
                  overflowWrap: 'anywhere',
                }}
              >
                <LatexText text={item.description || item.formula} />
              </div>
            </div>
          )}

          {/* 适用物理条件与假定 */}
          {validConditions.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--content-fg-secondary)' }}>
                适用物理条件与边界假定
              </span>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.6, color: 'var(--content-fg)' }}>
                {validConditions.map((cond, ci) => (
                  <li key={ci}><LatexText text={typeof cond === 'string' ? cond : cond.text || cond.description} /></li>
                ))}
              </ul>
            </div>
          )}

          {/* 参数区间定义表格 */}
          {Array.isArray(item.parameters) && item.parameters.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--content-fg-secondary)' }}>
                参数区间与物理量定义
              </span>
              <div className="kw-param-grid">
                {item.parameters.map((p, i) => (
                  <div key={i} className="kw-param-row">
                    <span className="kw-param-name">
                      {p.symbol ? <LatexMath math={p.symbol} /> : p.name}
                      {p.desc ? ` (${p.desc})` : ''}
                    </span>
                    <span className="kw-param-val">
                      {p.range} {p.unit || ''}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 关联物理量与天体性质 */}
          {Array.isArray(item.properties) && item.properties.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--content-fg-secondary)' }}>
                关联物理量与天体性质
              </span>
              <div className="kw-tag-list">
                {item.properties.map((prop, i) => {
                  const cleanProp = typeof prop === 'string' ? prop : prop.name || prop.id || ''
                  const displayProp = translateProperty(cleanProp)
                  return (
                    <span key={i} className="kw-tag">
                      <Icon.Tag style={{ width: 10, height: 10 }} />
                      <span>{displayProp}</span>
                    </span>
                  )
                })}
              </div>
            </div>
          )}

          {/* 文献出处 */}
          {item.sources && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--content-fg-secondary)' }}>
                文献出处与权威依据
              </span>
              <div style={{ fontSize: 12, color: 'var(--content-fg)', lineHeight: 1.5, overflowWrap: 'anywhere' }}>
                {typeof item.sources === 'string' ? item.sources : item.sources?.[0]?.title || ''}
              </div>
            </div>
          )}

          {/* 图谱拓扑关联 */}
          {relatedLinks.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--content-fg-secondary)' }}>
                图谱拓扑关联 ({relatedLinks.length})
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
                {relatedLinks.map((link, idx) => {
                  const sourceId = link.source?.id || link.source
                  const targetId = link.target?.id || link.target
                  const otherId = sourceId === item.id ? targetId : sourceId
                  const matchedNode = nodeById.get(otherId)
                  const rawLabel =
                    (link.source?.id === otherId ? (link.source?.label || link.source?.title) : null) ||
                    (link.target?.id === otherId ? (link.target?.label || link.target?.title) : null) ||
                    matchedNode?.title ||
                    matchedNode?.label ||
                    translateProperty(otherId)
                  const relationLabel = translateEdgeLabel(link.label)
                  return (
                    <div
                      key={idx}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 10,
                        padding: '6px 10px',
                        borderRadius: 6,
                        background: 'var(--surface-secondary, rgba(0,0,0,0.02))',
                        border: '1px solid var(--surface-border)',
                        cursor: 'pointer',
                      }}
                      onClick={() => onSelectNode?.(otherId)}
                    >
                      <span style={{ fontWeight: 500, color: 'var(--content-fg)', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {rawLabel}
                      </span>
                      <span style={{ fontSize: 11, color: 'var(--accent)', flexShrink: 0 }}>
                        {relationLabel} →
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </aside>
    </>
  )
}
