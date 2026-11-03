/* 任务状态徽标 —— 彩色圆点 + 中文文字（块 1 B2 定案） */

export const STATUS_COLORS = {
  clarifying: 'var(--status-running)', waiting_input: 'var(--status-waiting)', waiting_review: 'var(--status-waiting)',
  paused: 'var(--status-waiting)', interrupted: 'var(--status-error)', pausing: 'var(--status-waiting)', cancelling: 'var(--status-waiting)',
  budget_exhausted: 'var(--status-waiting)', definition_invalidated: 'var(--status-error)', pending: 'var(--status-waiting)',
  waiting: 'var(--status-waiting)', partial: 'var(--status-waiting)', skipped: 'var(--status-waiting)',
  queued: 'var(--status-waiting)',
  running: 'var(--status-running, #5097B1)',
  completed: 'var(--status-success)',
  error: 'var(--status-error)',
  failed: 'var(--status-error)',  // H-01: 旧词表别名（存量记录防御，主词表为 error）
  cancelled: 'var(--status-waiting)',
}

export const STATUS_LABELS = {
  clarifying: '准备查询', waiting_input: '等待输入', waiting_review: '等待质检审核', paused: '已暂停', interrupted: '执行中断',
  pausing: '正在暂停', cancelling: '正在取消', budget_exhausted: '预算已结束', definition_invalidated: '定义已失效',
  queued: '排队中',
  running: '运行中',
  completed: '已完成',
  error: '失败',
  failed: '失败',  // H-01: 旧词表别名
  cancelled: '已取消',
}

/* 状态点：running 带呼吸动画，其余实心 */
export function StatusDot({ status, size = 8 }) {
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        background: STATUS_COLORS[status] || STATUS_COLORS.cancelled,
        flexShrink: 0,
        ...(status === 'running' ? { animation: 'pulse-dot 2s ease-in-out infinite' } : {}),
      }}
    />
  )
}

/* 工具栏状态徽标：圆点 + 中文文字 */
export function StatusBadge({ status }) {
  const color = STATUS_COLORS[status] || STATUS_COLORS.cancelled
  const label = STATUS_LABELS[status] || '未知'
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 'var(--text-note)', color: 'var(--content-fg-secondary)' }}>
      <StatusDot status={status} />
      <span>{label}</span>
      <span style={{ width: 1, height: 12, background: 'var(--surface-border)', margin: '0 2px' }} />
    </span>
  )
}
