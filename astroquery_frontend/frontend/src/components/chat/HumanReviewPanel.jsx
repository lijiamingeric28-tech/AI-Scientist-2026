import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import Markdown from '@/lib/markdown'

/* 人工审核批量面板（2026-09-02 重构）：
 * - 单次批量协议（human_review_batch）：payload.conflicts 全部冲突 + summary_markdown
 * - 强制逐项裁决（无"全部保留/全部跳过"批量按钮）：每项 = 后端给出的 1-5 选项卡 + 可选理由
 * - 必选校验：提交时存在未选项 → 高亮提示，不提交
 * - 提交组装 JSON.stringify({verdicts}) → onSubmit 一次 resume
 */

const ACTION_LABELS = {
  1: '采用 Source A',
  2: '采用 Source B',
  3: '自定义值',
  4: '保留两者（标注差异）',
  5: '跳过（保留原样）',
}
const ACTION_KEYS = { 1: 'adopt_source_a', 2: 'adopt_source_b', 3: 'custom_value', 4: 'retain_both', 5: 'skip' }

function Item({ c, index, total, onSet }) {
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState('')       // '' | '1'..'5'
  const [value, setValue] = useState('')   // custom_value 输入
  const [reason, setReason] = useState('')
  const [error, setError] = useState(false)

  const commit = () => {
    if (!key) {
      onSet(c.conflict_d, null)
      setError(true)
      return
    }
    const entry = { action: ACTION_KEYS[key] }
    if (key === '3') entry.selected_value = value
    if (reason.trim()) entry.reason = reason.trim()
    onSet(c.conflict_d, entry)
    setError(false)
  }

  return (
    <div style={{ border: '1px solid var(--surface-border-subtle)', borderRadius: 8, marginBottom: 8, background: error ? 'var(--status-error-bg)' : 'var(--surface-bg)' }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none', display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px' }}
        onClick={() => setOpen((v) => !v)}>
        <Icon.ChevronRight style={{ width: 10, height: 10, flexShrink: 0, color: 'var(--content-fg-tertiary)', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .12s' }} />
        <span className="font-mono" style={{ fontSize: 12, fontWeight: 590, color: 'var(--content-fg)' }}>{c.conflict_d}</span>
        {c.field_name && <span style={{ fontSize: 12, color: 'var(--content-fg-secondary)' }}>{c.field_name}</span>}
        {c.entity_name && <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>{c.entity_name}</span>}
        <span style={{ flex: 1 }} />
        {error && <span style={{ fontSize: 11, color: 'var(--status-error)' }}>未选择</span>}
        {key ? (
          <span style={{ fontSize: 11, padding: '1px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--accent-light)', color: 'var(--accent-text)', fontWeight: 510 }}>
            {ACTION_LABELS[key]}
          </span>
        ) : (
          <span style={{ fontSize: 10.5, padding: '1px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--surface-secondary)', color: 'var(--content-fg-tertiary)' }}>未裁决</span>
        )}
      </summary>
      {open && (
        <div style={{ padding: '0 12px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* 冲突详情 markdown */}
          {c.markdown && (
            <div style={{ fontSize: 12.5 }}>
              <Markdown>{c.markdown}</Markdown>
            </div>
          )}
          {/* 裁决选项卡（后端 c.options 权威） */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {(c.options || ['1', '2', '3', '4', '5']).map((k) => (
              <button
                key={k}
                onClick={() => { setKey(k); setError(false) }}
                style={{
                  padding: '4px 10px', fontSize: 11.5, fontWeight: 510, borderRadius: 'var(--radius-pill)',
                  border: '1px solid', cursor: 'pointer',
                  borderColor: key === k ? 'var(--accent)' : 'var(--surface-border)',
                  background: key === k ? 'var(--accent-light)' : 'transparent',
                  color: key === k ? 'var(--accent-text)' : 'var(--content-fg-secondary)',
                }}
              >
                {ACTION_LABELS[k]}
              </button>
            ))}
          </div>
          {/* 自定义值输入（选中 3 时显示） */}
          {key === '3' && (
            <input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="请输入自定义值（数值或文本）"
              style={{ padding: '6px 10px', fontSize: 12, border: '1px solid var(--surface-border)', borderRadius: 6, outline: 'none', background: 'var(--surface-secondary)', color: 'var(--content-fg)' }}
            />
          )}
          {/* 可选理由 */}
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="理由（可选）"
            style={{ padding: '6px 10px', fontSize: 12, border: '1px solid var(--surface-border)', borderRadius: 6, outline: 'none', background: 'var(--surface-secondary)', color: 'var(--content-fg)' }}
          />
          <Button variant="outline" size="sm" onClick={commit} style={{ alignSelf: 'flex-end' }}>确定此项</Button>
        </div>
      )}
    </div>
  )
}

export default function HumanReviewPanel({ payload, onSubmit }) {
  const conflicts = payload.conflicts || []
  const [verdicts, setVerdicts] = useState({})
  const [missing, setMissing] = useState(false)

  const setVerdict = (cid, entry) => {
    setVerdicts((prev) => {
      const next = { ...prev }
      if (entry === null) delete next[cid]
      else next[cid] = entry
      return next
    })
  }

  const submit = () => {
    // 必选校验：全部冲突必须裁决
    if (conflicts.length === 0) return
    const unresolved = conflicts.filter((c) => !verdicts[c.conflict_d])
    if (unresolved.length > 0) {
      setMissing(true)
      return
    }
    setMissing(false)
    onSubmit(JSON.stringify({ verdicts }))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* 整批 markdown 汇总 */}
      {payload.summary_markdown && (
        <div style={{ fontSize: 12.5 }}>
          <Markdown>{payload.summary_markdown}</Markdown>
        </div>
      )}
      {/* 冲突列表（逐项裁决） */}
      <div>
        {conflicts.map((c, i) => (
          <Item key={c.conflict_d} c={c} index={i} total={conflicts.length} onSet={setVerdict} />
        ))}
      </div>
      {missing && (
        <div style={{ fontSize: 12, color: 'var(--status-error)' }}>存在未裁决项，请逐项选择后再提交</div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ flex: 1, fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
          已裁决 {Object.keys(verdicts).length}/{conflicts.length} · 提交后需再选择下一步（提交裁决/重新评估/取消）
        </span>
        <Button
          size="sm"
          onClick={submit}
          style={{ background: 'var(--accent)', color: 'var(--accent-on)' }}
        >
          提交裁决
        </Button>
      </div>
    </div>
  )
}
