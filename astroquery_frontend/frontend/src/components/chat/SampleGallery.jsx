import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'

/* 演示样例画廊（2026-09-02）——「演示样例」模式空态主视图。
 *
 * 数据源：frontend/src/data/samples.json（scripts/rebuild_sample_pack.py 生成，
 * 质量分/记录数/来源数与任务 state_json 及结果端点同源，勿手工编辑）。
 * 点卡片主体 → 选中样例（进入与真实任务完全相同的时间线视图）；
 * 卡内「回放」→ 直接创建回放任务重演真实过程（事件级重放，零查询额度）。
 */

function fmtScore(v) {
  if (typeof v !== 'number') return '—'
  return String(Number(v).toFixed(4)).replace(/0+$/, '').replace(/\.$/, '')
}

export default function SampleGallery({ samples = [], onOpen, onReplay, onSwitchToUser }) {
  const [hoverId, setHoverId] = useState(null)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* 头部：标题 + 说明（评审叙事：内嵌真实查询，离线免费回放） */}
      <div>
        <div style={{ fontSize: 15, fontWeight: 510, color: 'var(--content-fg)' }}>
          演示样例 <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--content-fg-tertiary)' }}>· {samples.length} 组真实查询</span>
        </div>
        <div style={{ fontSize: 12, color: 'var(--content-fg-secondary)', lineHeight: 1.6, marginTop: 4 }}>
          这些查询曾真实运行并通过人工复核，事件流与结果已内嵌系统——点击卡片查看完整过程，
          或点「回放」按压缩节奏重演（不消耗查询额度、无需密钥）。
          <button
            onClick={onSwitchToUser}
            style={{
              border: 'none', background: 'transparent', cursor: 'pointer', padding: 0,
              color: 'var(--accent-text)', fontSize: 12, textDecoration: 'underline',
            }}
          >
            发起真实查询请切回「我的查询」
          </button>
        </div>
      </div>

      {/* 卡片墙（单列自适应网格） */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 10 }}>
        {samples.map((s) => {
            return (
              <div
                key={s.task_id}
              onClick={() => onOpen?.(s.task_id)}
              onMouseEnter={() => setHoverId(s.task_id)}
              onMouseLeave={() => setHoverId(null)}
              title="查看完整运行时间线"
              style={{
                border: `1px solid ${hoverId === s.task_id ? 'var(--accent)' : 'var(--surface-border)'}`,
                borderRadius: 10,
                background: 'var(--surface-bg)',
                padding: '12px 14px',
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                cursor: 'pointer',
                transition: 'border-color .15s, box-shadow .15s',
                boxShadow: hoverId === s.task_id
                  ? '0 0 0 3px color-mix(in srgb, var(--accent) 12%, transparent)'
                  : undefined,
              }}
            >
              {/* 首行：名称 + 质量分徽章 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--content-fg)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {s.name}
                </span>
                {typeof s.quality_score === 'number' && (
                  <span
                    style={{
                      fontSize: 11, fontWeight: 600, fontFamily: 'var(--font-mono, ui-monospace, monospace)',
                      padding: '2px 8px', borderRadius: 'var(--radius-pill)',
                      background: 'var(--accent-light)', color: 'var(--accent-text)', flexShrink: 0,
                    }}
                    title="质量分（人工复核后管线输出）"
                  >
                    质量 {fmtScore(s.quality_score)}
                  </span>
                )}
              </div>
              {/* 查询句 */}
              <div style={{ fontSize: 12, color: 'var(--content-fg-secondary)', lineHeight: 1.5 }}>
                {s.query}
              </div>
              {/* 摘要（平实一段） */}
              <div style={{ fontSize: 12, color: 'var(--content-fg-secondary)', lineHeight: 1.55, opacity: 0.92 }}>
                {s.summary}
              </div>
              {/* 尾行：计数 + 回放 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 2 }}>
                <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
                  {Number(s.record_count) > 0 && <>{s.record_count} 条记录 · </>}
                  {Number(s.source_count) > 0 && <>{s.source_count} 个来源 · </>}
                  事件已内嵌
                </span>
                <span style={{ flex: 1 }} />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation()
                    onReplay?.(s.task_id)
                  }}
                  title="创建回放任务，重演完整过程（不消耗查询额度）"
                  style={{ color: 'var(--accent-text)', borderColor: 'color-mix(in srgb, var(--accent) 45%, transparent)', gap: 5, fontWeight: 500 }}
                >
                  <Icon.Play style={{ width: 11, height: 11 }} />
                  回放
                </Button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
