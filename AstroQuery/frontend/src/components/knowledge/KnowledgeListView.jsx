import React, { useState, useEffect } from 'react'
import { Icon } from '@/components/icons'
import { LatexMath, LatexText } from '@/components/results/LatexMath'
import {
  KNOWLEDGE_CATEGORIES,
  getCategoryInfo,
  isValidFormula,
  translateProperty,
} from './knowledgeConstants'

export default function KnowledgeListView({
  items = [],
  categories = KNOWLEDGE_CATEGORIES,
  selectedCategory = 'all',
  onTogglePreference,
  onEdit,
  onFork,
  onDelete,
  onRestore,
  onSelectNode,
}) {
  const [collapsedCategories, setCollapsedCategories] = useState({})
  const [expandedLimits, setExpandedLimits] = useState({})

  useEffect(() => {
    setExpandedLimits({})
  }, [selectedCategory, items.length])

  const defaultLimit = selectedCategory === 'all' ? 12 : 36

  const showMoreForCategory = (catId, total, showAll = false) => {
    setExpandedLimits(prev => ({
      ...prev,
      [catId]: showAll ? total : (prev[catId] || defaultLimit) + 24,
    }))
  }

  const toggleCategoryCollapse = (catId) => {
    setCollapsedCategories(prev => ({
      ...prev,
      [catId]: !prev[catId],
    }))
  }

  // Filter by category if not 'all'
  const visibleCategories = categories.filter(c => {
    if (c.id === 'all') return false
    if (selectedCategory !== 'all' && c.id !== selectedCategory && c.label !== selectedCategory) return false
    return true
  })

  // Group items by category
  const grouped = visibleCategories.map(cat => {
    const catItems = items.filter(item => {
      const itemCat = item.category || 'physical_laws'
      return itemCat === cat.id || cat.altNames?.includes(itemCat) || itemCat === cat.label
    })
    return {
      category: cat,
      items: catItems,
    }
  }).filter(group => selectedCategory !== 'all' || group.items.length > 0)

  if (items.length === 0) {
    return (
      <div className="kw-empty-state">
        <Icon.Search style={{ width: 40, height: 40, opacity: 0.35 }} />
        <h4>未找到匹配的物理理论或定律</h4>
        <p>请尝试放宽检索关键词、切换分类或重置当前过滤条件。</p>
      </div>
    )
  }

  return (
    <div className="kw-list-container">
      {grouped.map(({ category, items: groupItems }) => {
        const isCollapsed = Boolean(collapsedCategories[category.id])
        return (
          <section key={category.id} className="kw-category-section">
            <header className="kw-section-title">
              <div
                className="kw-section-title-left"
                style={{ cursor: 'pointer' }}
                onClick={() => toggleCategoryCollapse(category.id)}
              >
                <button
                  type="button"
                  className="kw-icon-btn"
                  style={{ width: 22, height: 22 }}
                  aria-label={isCollapsed ? '展开分类' : '折叠分类'}
                >
                  {isCollapsed ? (
                    <Icon.ChevronRight style={{ width: 14, height: 14 }} />
                  ) : (
                    <Icon.ChevronDown style={{ width: 14, height: 14 }} />
                  )}
                </button>
                <span
                  className="kw-cat-dot"
                  style={{ background: category.color }}
                />
                <span>{category.label}</span>
                <span className="kw-cat-count">{groupItems.length}</span>
              </div>
            </header>

            {!isCollapsed && (
              <>
                <div className="kw-card-grid">
                  {groupItems.slice(0, expandedLimits[category.id] || defaultLimit).map(item => {
                  const isPreferred = Boolean(
                    item.user_preference === 'preferred' || item.preferred
                  )
                  const catInfo = getCategoryInfo(item.category, categories)

                  // 过滤内部英文枚举伪假定，只保留真正学术条件
                  const validConditions = Array.isArray(item.conditions)
                    ? item.conditions.filter(c => {
                        const s = String(typeof c === 'string' ? c : c?.text || '').trim().toLowerCase()
                        return s && !['established', 'consensus', 'provisional', 'empirical'].includes(s)
                      })
                    : []

                  return (
                    <article
                      key={item.id}
                      className={`kw-card ${isPreferred ? 'is-preferred' : ''}`}
                      onClick={() => onSelectNode?.(item.id)}
                      style={{ cursor: 'pointer' }}
                      title="点击查看完整理论详情、推导公式与关联拓扑"
                    >
                      <header className="kw-card-header">
                        <div className="kw-card-title-group">
                          <div className="kw-card-meta">
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
                            {item.is_override && (
                              <span
                                className="kw-badge"
                                style={{
                                  background: 'rgba(59, 130, 246, 0.15)',
                                  color: '#2563eb',
                                  border: '1px solid rgba(59, 130, 246, 0.3)',
                                }}
                              >
                                用户已修改
                              </span>
                            )}
                            {item.is_user && !item.is_override && (
                              <span
                                className="kw-badge"
                                style={{
                                  background: 'rgba(234, 179, 8, 0.15)',
                                  color: '#d97706',
                                  border: '1px solid rgba(234, 179, 8, 0.3)',
                                }}
                              >
                                自建理论
                              </span>
                            )}
                            {isPreferred && (
                              <span
                                className="kw-badge"
                                style={{
                                  background: 'rgba(234, 179, 8, 0.2)',
                                  color: '#d97706',
                                  border: '1px solid #d97706',
                                }}
                              >
                                科研优选
                              </span>
                            )}
                          </div>
                          <h4 className="kw-card-title">{item.title || item.name}</h4>
                        </div>

                        <div className="kw-card-actions">
                          {/* 优选切换 */}
                          <button
                            type="button"
                            className={`kw-icon-btn ${isPreferred ? 'is-active-star' : ''}`}
                            onClick={(e) => {
                              e.stopPropagation()
                              onTogglePreference(item.id, !isPreferred)
                            }}
                            title={isPreferred ? '已设为科研优先理论（点击取消）' : '设为科研优先理论'}
                            aria-label={isPreferred ? '取消优选' : '设为优选'}
                          >
                            {isPreferred ? (
                              <Icon.StarFilled style={{ width: 15, height: 15 }} />
                            ) : (
                              <Icon.Star style={{ width: 15, height: 15 }} />
                            )}
                          </button>

                          {/* 编辑理论 */}
                          <button
                            type="button"
                            className="kw-icon-btn"
                            onClick={(e) => {
                              e.stopPropagation()
                              onEdit(item)
                            }}
                            title="直接修改该理论内容与分类"
                            aria-label="编辑理论"
                          >
                            <Icon.Edit style={{ width: 14, height: 14 }} />
                          </button>

                          {/* 派生理论 */}
                          <button
                            type="button"
                            className="kw-icon-btn"
                            onClick={(e) => {
                              e.stopPropagation()
                              onFork(item)
                            }}
                            title="以此为基础派生新理论"
                            aria-label="派生理论"
                          >
                            <Icon.Fork style={{ width: 14, height: 14 }} />
                          </button>

                          {/* 删除理论 */}
                          <button
                            type="button"
                            className="kw-icon-btn kw-delete-action-btn"
                            onClick={(e) => {
                              e.stopPropagation()
                              if (window.confirm(`确定要删除理论条目「${item.title || item.name}」吗？`)) {
                                onDelete(item.id)
                              }
                            }}
                            title="从知识库中删除理论条目"
                            aria-label="删除理论"
                          >
                            <Icon.Trash style={{ width: 14, height: 14 }} />
                          </button>

                          {/* 仅在用户实际修改过内置条目时才显示恢复出厂默认按钮 */}
                          {Boolean(item.is_override) && (
                            <button
                              type="button"
                              className="kw-icon-btn"
                              onClick={(e) => {
                                e.stopPropagation()
                                onRestore(item.id)
                              }}
                              title="清除修改，重置为系统出厂预置状态"
                              aria-label="恢复默认"
                            >
                              <Icon.History style={{ width: 14, height: 14 }} />
                            </button>
                          )}
                        </div>
                      </header>

                      {/* 纯正数学公式展示区 */}
                      {item.formula && isValidFormula(item.formula) && (
                        <div className="kw-formula-box">
                          <LatexMath math={item.formula} displayMode />
                        </div>
                      )}

                      {/* 理论描述正文 */}
                      {(item.description || (item.formula && !isValidFormula(item.formula))) && (
                        <p className="kw-card-desc">
                          <LatexText text={item.description || item.formula} />
                        </p>
                      )}

                      {/* 真实物理假定条件 */}
                      {validConditions.length > 0 && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 12, color: 'var(--content-fg-secondary)' }}>
                          <span style={{ fontWeight: 500, color: 'var(--content-fg)' }}>适用物理条件与假定：</span>
                          {validConditions.map((cond, i) => (
                            <div key={i} style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                              <span style={{ width: 4, height: 4, borderRadius: '50%', background: 'currentColor', flexShrink: 0 }} />
                              <span><LatexText text={typeof cond === 'string' ? cond : cond.text || cond.description} /></span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* 参数区间定义 */}
                      {Array.isArray(item.parameters) && item.parameters.length > 0 && (
                        <div className="kw-param-grid">
                          <div style={{ fontWeight: 500, color: 'var(--content-fg)', marginBottom: 2 }}>参数区间定义：</div>
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
                      )}

                      {/* 关联物理量（学术中文转换） */}
                      {Array.isArray(item.properties) && item.properties.length > 0 && (
                        <div className="kw-tag-list">
                          <span style={{ fontSize: 11, color: 'var(--content-fg-secondary)' }}>关联物理量:</span>
                          {item.properties.slice(0, 8).map((prop, i) => {
                            const cleanProp = typeof prop === 'string' ? prop : prop.name || prop.id || ''
                            const displayProp = translateProperty(cleanProp)
                            return (
                              <span key={i} className="kw-tag">
                                <Icon.Tag style={{ width: 10, height: 10 }} />
                                <span>{displayProp}</span>
                              </span>
                            )
                          })}
                          {item.properties.length > 8 && (
                            <span className="kw-tag" title="点击卡片查看全部关联物理量">
                              +{item.properties.length - 8} 项
                            </span>
                          )}
                        </div>
                      )}

                      {item.sources && (
                        <footer className="kw-sources">
                          <span>文献出处：{typeof item.sources === 'string' ? item.sources : item.sources?.[0]?.title || ''}</span>
                        </footer>
                      )}
                    </article>
                  )
                })}
                </div>
                {groupItems.length > (expandedLimits[category.id] || defaultLimit) && (
                  <div className="kw-load-more-row">
                    <button
                      type="button"
                      className="kw-load-more-btn"
                      onClick={() => showMoreForCategory(category.id, groupItems.length, false)}
                    >
                      展开更多「{category.label}」（还有 {groupItems.length - (expandedLimits[category.id] || defaultLimit)} 条）
                    </button>
                    {groupItems.length <= 120 && (
                      <button
                        type="button"
                        className="kw-load-more-btn secondary"
                        onClick={() => showMoreForCategory(category.id, groupItems.length, true)}
                      >
                        显示本类全部 ({groupItems.length})
                      </button>
                    )}
                  </div>
                )}
              </>
            )}
          </section>
        )
      })}
    </div>
  )
}
