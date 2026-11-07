import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'

/* Catalog order and the editorial recommendation are supplied by the curator. */

function fmtScore(v) {
  if (typeof v !== 'number') return '—'
  return String(Number(v * 100).toFixed(2)).replace(/0+$/, '').replace(/\.$/, '')
}

export default function SampleGallery({ samples = [], onOpen, onReplay, onSwitchToUser }) {
  const [hoverId, setHoverId] = useState(null)
  const [search, setSearch] = useState('')
  const filtered = samples.filter((s) =>
    JSON.stringify([s.name, s.title, s.object, s.properties, s.query])
      .toLowerCase()
      .includes(search.toLowerCase())
  )

  if (!samples.length) {
    return (
      <section className="empty-state">
        <h2>演示样例待选定</h2>
        <p>当前尚未发布精选演示。可先浏览我的查询中的已有结果。</p>
        <Button onClick={onSwitchToUser}>浏览我的查询</Button>
      </section>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* 头部：标题 + 说明（评审叙事：内嵌真实查询，离线免费回放） */}
      <div>
        <div style={{ fontSize: 'var(--text-body)', fontWeight: 550, color: 'var(--content-fg)' }}>
          演示样例 <span style={{ fontSize: 'var(--text-note)', fontWeight: 400, color: 'var(--content-fg-tertiary)' }}>· {samples.length} 组真实科学查询</span>
        </div>
        <div style={{ fontSize: 'var(--text-note)', color: 'var(--content-fg-secondary)', lineHeight: 1.6, marginTop: 4 }}>
          这些已保存查询包含原始文献提取事实与图文证据链。点击“查看成果”查阅多源交叉数据与科研图表，
          或点“回放过程”重演完整执行步骤（无需消耗算力与密钥）。
          <button
            onClick={onSwitchToUser}
            style={{
              border: 'none',
              background: 'transparent',
              cursor: 'pointer',
              padding: '0 0 0 8px',
              color: 'var(--accent-text)',
              fontSize: 'var(--text-note)',
              textDecoration: 'underline',
            }}
          >
            发起真实查询请切回「我的查询」
          </button>
        </div>
      </div>

      <input
        className="workspace-search"
        aria-label="搜索演示样例"
        placeholder="搜索天体对象、物理性质或研究题目…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ maxWidth: 460 }}
      />

      {/* 精选目录：一行放两个（宽屏双列，窄屏自动单列） */}
      <div className="sample-grid-2col">
        {filtered.map((s) => {
          const isHovered = hoverId === s.task_id
          const objectName = s.object || s.name?.split('·')[0]?.trim() || s.name

          return (
            <div
              key={s.task_id}
              onClick={() => {
                const sel = window.getSelection()
                if (sel && sel.toString().trim().length > 0) return
                onOpen?.(s.task_id)
              }}
              onMouseEnter={() => setHoverId(s.task_id)}
              onMouseLeave={() => setHoverId(null)}
              className="sample-card hover-lift"
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.target === event.currentTarget && ['Enter', ' '].includes(event.key)) {
                  event.preventDefault()
                  onOpen?.(s.task_id)
                }
              }}
              title="点击查看数据成果"
            >
              {/* 1. 顶部：天体对象名称 + 天体类型微标 + 标杆微章 + 任务分 */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                  <span
                    style={{
                      fontSize: 16.5,
                      fontWeight: 650,
                      color: 'var(--title-strong, #44785b)',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {objectName}
                  </span>
                  {s.otype && (
                    <span
                      style={{
                        fontSize: 11,
                        padding: '1.5px 7px',
                        borderRadius: 4,
                        background: 'var(--surface-secondary)',
                        color: 'var(--content-fg-secondary)',
                        fontWeight: 500,
                        flexShrink: 0,
                      }}
                      title={`SIMBAD 天体类型：${s.otype}`}
                    >
                      {s.otype}
                    </span>
                  )}
                  {s.featured && (
                    <span
                      style={{
                        fontSize: 10,
                        padding: '1.5px 7px',
                        borderRadius: 4,
                        background: 'var(--accent)',
                        color: '#ffffff',
                        fontWeight: 500,
                        flexShrink: 0,
                      }}
                    >
                      首选演示
                    </span>
                  )}
                </div>

                {typeof s.quality_score === 'number' && (
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      fontFamily: 'var(--font-mono, ui-monospace, monospace)',
                      padding: '2px 9px',
                      borderRadius: 'var(--radius-pill)',
                      background: 'var(--accent-light)',
                      color: 'var(--accent-text)',
                      flexShrink: 0,
                    }}
                    title="原任务完成度与质检评分"
                  >
                    任务分 {fmtScore(s.quality_score)}
                  </span>
                )}
              </div>

              {/* 2. 物理性质区：星体与性质鲜明分离 */}
              {Array.isArray(s.properties) && s.properties.length > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 11.5, color: 'var(--content-fg-tertiary)', fontWeight: 500, flexShrink: 0 }}>
                    查询性质：
                  </span>
                  {s.properties.map((prop) => (
                    <span key={prop} className="sample-prop-tag">
                      {prop}
                    </span>
                  ))}
                </div>
              )}

              {/* 3. 原始提问需求（灰阶 1：深灰标准字） */}
              <div
                style={{
                  fontSize: 13,
                  color: 'var(--content-fg)',
                  lineHeight: 1.5,
                  padding: '6px 10px',
                  borderRadius: 6,
                  background: 'var(--surface-secondary)',
                  borderLeft: '3px solid var(--accent-light)',
                }}
              >
                {s.query}
              </div>

              {/* 4. 论文溯源与分析摘要（灰阶 2：中灰次级字） */}
              <div
                style={{
                  fontSize: 12.5,
                  color: 'var(--content-fg-secondary)',
                  lineHeight: 1.6,
                  flex: 1,
                }}
              >
                {s.summary}
              </div>

              {/* 5. 底部数据指标条（灰阶 3：浅灰微标） + 查看成果与回放过程按钮 */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                  borderTop: '1px solid var(--surface-border-subtle)',
                  paddingTop: 12,
                  marginTop: 'auto',
                }}
              >
                <div className="sample-metric-pill">
                  <span><strong>{s.record_count || 0}</strong> 条测量</span>
                  <span>·</span>
                  <span><strong>{s.source_count || 0}</strong> 篇来源</span>
                  <span>·</span>
                  <span><strong>{s.figure_count || 0}</strong> 幅图像</span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                  <Button
                    variant="accent"
                    size="sm"
                    onClick={(event) => {
                      event.stopPropagation()
                      onOpen?.(s.task_id)
                    }}
                    style={{ fontSize: 12.5, padding: '5px 13px', fontWeight: 500 }}
                  >
                    查看成果
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation()
                      onReplay?.(s.task_id)
                    }}
                    title="只读播放原任务过程，不新建科研任务"
                    style={{
                      fontSize: 12.5,
                      color: 'var(--accent-text)',
                      borderColor: 'color-mix(in srgb, var(--accent) 45%, transparent)',
                      gap: 4,
                      fontWeight: 500,
                      padding: '5px 11px',
                    }}
                  >
                    <Icon.Play style={{ width: 11, height: 11 }} />
                    回放过程
                  </Button>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
