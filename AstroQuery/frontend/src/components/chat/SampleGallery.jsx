import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'

/* Catalog order and the editorial recommendation are supplied by the curator. */

function fmtScore(v) {
  if (typeof v !== 'number') return '—'
  return String(Number(v * 100).toFixed(2)).replace(/0+$/, '').replace(/\.$/, '')
}

export default function SampleGallery({ samples = [], onOpen, onReplay, onSwitchToUser }) {
  const [hoverId, setHoverId] = useState(null),[search,setSearch]=useState('')
  const filtered=samples.filter(s=>JSON.stringify([s.name,s.title,s.object,s.properties,s.query]).toLowerCase().includes(search.toLowerCase()))
  if(!samples.length)return <section className="empty-state"><h2>演示样例待选定</h2><p>当前尚未发布精选演示。可先浏览我的查询中的已有结果。</p><Button onClick={onSwitchToUser}>浏览我的查询</Button></section>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* 头部：标题 + 说明（评审叙事：内嵌真实查询，离线免费回放） */}
      <div>
        <div style={{ fontSize: 'var(--text-body)', fontWeight: 510, color: 'var(--content-fg)' }}>
          演示样例 <span style={{ fontSize: 'var(--text-note)', fontWeight: 400, color: 'var(--content-fg-tertiary)' }}>· {samples.length} 组真实查询</span>
        </div>
        <div style={{ fontSize: 'var(--text-note)', color: 'var(--content-fg-secondary)', lineHeight: 1.6, marginTop: 4 }}>
          这些已保存查询包含原始事件与结果。点击“查看成果”阅读数据、来源和处理记录，
          或点“回放过程”重演执行步骤（不消耗查询额度、无需密钥）。
          <button
            onClick={onSwitchToUser}
            style={{
              border: 'none', background: 'transparent', cursor: 'pointer', padding: 0,
              color: 'var(--accent-text)', fontSize: 'var(--text-note)', textDecoration: 'underline',
            }}
          >
            发起真实查询请切回「我的查询」
          </button>
        </div>
      </div>

      <input className="workspace-search" aria-label="搜索演示样例" placeholder="搜索对象、性质或题目" value={search} onChange={e=>setSearch(e.target.value)}/>
      {/* 精选目录 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 10 }}>
        {filtered.map((s) => {
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
                className="hover-lift"
                role="button" tabIndex={0} onKeyDown={event => { if (event.target === event.currentTarget && ['Enter', ' '].includes(event.key)) { event.preventDefault(); onOpen?.(s.task_id) } }} title="查看数据成果"
                style={{
                  border: `1px solid ${hoverId === s.task_id ? 'var(--accent)' : 'var(--surface-border)'}`,
                  borderRadius: 10,
                  background: 'var(--surface-bg)',
                  padding: '12px 14px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 6,
                  cursor: 'pointer',
                  transition: 'border-color .18s ease, box-shadow .18s ease',
                  boxShadow: hoverId === s.task_id
                    ? '0 0 0 3px color-mix(in srgb, var(--accent) 12%, transparent)'
                    : undefined,
                }}
            >
              {s.featured && <strong className="demo-featured-label">首选演示</strong>}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--content-fg)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {s.name}
                </span>
                {typeof s.quality_score === 'number' && (
                  <span
                    style={{
                      fontSize: 'var(--text-note)', fontWeight: 600, fontFamily: 'var(--font-mono, ui-monospace, monospace)',
                      padding: '2px 8px', borderRadius: 'var(--radius-pill)',
                      background: 'var(--accent-light)', color: 'var(--accent-text)', flexShrink: 0,
                    }}
                    title="原任务完成与交付分，不是科学正确率"
                  >
                    任务分 {fmtScore(s.quality_score)}
                  </span>
                )}
              </div>
              {/* 查询句 */}
              <div style={{ fontSize: 'var(--text-note)', color: 'var(--content-fg-secondary)', lineHeight: 1.5 }}>
                {s.query}
              </div>
              {/* 摘要（平实一段） */}
              <div style={{ fontSize: 'var(--text-note)', color: 'var(--content-fg-secondary)', lineHeight: 1.55, opacity: 0.92 }}>
                {s.summary?.split('：')[0] || s.name} · 可查看来源、处理步骤与质量报告。
              </div>
              {/* 尾行：计数 + 回放 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 2 }}>
                <span style={{ fontSize: 'var(--text-note)', color: 'var(--content-fg-tertiary)' }}>
                  {Number(s.record_count) > 0 && <>{s.record_count} 条记录 · </>}
                  {Number(s.source_count) > 0 && <>{s.source_count} 个来源 · </>}
                  {s.figure_count != null && <>{s.figure_count} 幅研究图像</>}
                </span>
                <span style={{ flex: 1 }} />
                <Button variant="accent" size="sm" onClick={event => { event.stopPropagation(); onOpen?.(s.task_id) }}>查看成果</Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation()
                    onReplay?.(s.task_id)
                  }}
                  title="只读播放原任务过程，不新建科研任务"
                  style={{ color: 'var(--accent-text)', borderColor: 'color-mix(in srgb, var(--accent) 45%, transparent)', gap: 5, fontWeight: 500 }}
                >
                  <Icon.Play style={{ width: 11, height: 11 }} />
                  回放过程
                </Button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
