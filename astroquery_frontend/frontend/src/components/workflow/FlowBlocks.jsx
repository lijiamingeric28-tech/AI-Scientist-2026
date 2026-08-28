import { StatusDot } from '@/components/status'
import { Icon } from '@/components/icons'
import { FLOW_LABELS, CLEAN_FLOW_BLOCKS, flowIdOfAgent } from '@/lib/stages'

/* 清洗卡嵌套块结构（2026-08-27，StageCard 与 StageDetailPanel 共用）：
 * 每个轮次块（数据规范化 第 N 轮 / 冲突消解 第 N 轮 / 人工审核）为容器，
 * 其下挂属于该块的 Agent（flow 上下文的权威归属来自后端：
 * agent 事件 flow_id + round 字段；旧任务无该字段时按子图 Agent 名单名字兜底）。
 * 未触发的块（无 flow 事件且无对应 agent）显示「未触发，按需被选」而非「等待中」。
 * round 后端 0-based → 显示 1-based；多轮循环（第 2 轮等）不再去重丢失。 */

const FLOW_STATUS_LABELS = { completed: '已完成', running: '执行中', waiting: '等待中' }

/* Agent → 所属块 flowId（flow_id 权威优先，旧事件名字兜底） */
function agentFlowKey(agent) {
  const fid = (agent && agent.flow_id) || (agent && agent.flowId)
  if (fid && fid !== 'other') return fid
  return flowIdOfAgent(agent && agent.agent)
}

export function getAgentFlowKey(agent) {
  return agentFlowKey(agent)
}

/* agents 按 flowId 归组（保留 round 信息） */
function groupAgentsByFlow(agents) {
  const byFlow = new Map()
  for (const a of agents || []) {
    const fid = agentFlowKey(a)
    if (fid === 'other') continue
    if (!byFlow.has(fid)) byFlow.set(fid, { agents: [] })
    byFlow.get(fid).agents.push(a)
  }
  return byFlow
}

/* 块序列生成：flow 事件 (flowId, round) 保持出现顺序；
 * 固定块清单未出现的（human_review / conflict 未触发）追加尾部占位块。 */
function buildBlocks(flows, stageId) {
  const seenOrder = []
  const seen = new Set()
  for (const f of flows || []) {
    const k = `${f.flowId}|${f.round}`
    if (!seen.has(k)) { seen.add(k); seenOrder.push({ flowId: f.flowId, round: f.round, node: f }) }
  }
  if (stageId === 'clean') {
    for (const fid of CLEAN_FLOW_BLOCKS) {
      if (!seenOrder.some((x) => x.flowId === fid)) seenOrder.push({ flowId: fid, round: null, node: null })
    }
  }
  return seenOrder
}

/* Agent 明细子结点（交互/确认键均按复合键，多轮不冲突） */
function AgentItem({ agent, onOpenAgent }) {
  const traceCount = Array.isArray(agent.traces) ? agent.traces.length : 0
  const logCount = Array.isArray(agent.logs) ? agent.logs.length : 0
  return (
    <div
      onClick={() => onOpenAgent(agent)}
      className="agent-row"   // 2026-08-27：hover 背景 CSS 化（滑动无 setState）
      style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '6px 10px', borderRadius: 'var(--radius-md)',
        border: '1px solid var(--surface-border-subtle)',
        background: 'var(--surface-bg)',
        cursor: 'pointer', marginBottom: 4,
      }}
    >
      <StatusDot status={agent.status} size={6} />
      <span style={{ fontSize: 12.5, fontWeight: 510, color: 'var(--content-fg)' }}>{agent.agent}</span>
      {agent.status === 'running' && <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>执行中…</span>}
      {agent.duration && <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>{agent.duration}</span>}
      <span style={{ flex: 1 }} />
      {logCount > 0 && (
        <span style={{ fontSize: 10.5, padding: '1px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--surface-secondary)', border: '1px solid var(--surface-border-subtle)', color: 'var(--content-fg-secondary)' }}>
          {logCount} 条执行日志
        </span>
      )}
      {traceCount > 0 && (
        <span style={{ fontSize: 10.5, padding: '1px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--surface-secondary)', border: '1px solid var(--surface-border-subtle)', color: 'var(--content-fg-secondary)' }}>
          {traceCount} 条修改
        </span>
      )}
      <Icon.ChevronRight style={{ width: 11, height: 11, color: 'var(--content-fg-tertiary)', flexShrink: 0 }} />
    </div>
  )
}

export default function FlowBlocks({ flows, stageId, agents, onOpenAgent }) {
  if (!flows || flows.length === 0) return null
  const byFlowGroup = groupAgentsByFlow(agents)
  const blocks = buildBlocks(flows, stageId)
  const assigned = new Set()

  return (
    <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="hint-dim" style={{ fontSize: 11 }}>流程轮次</div>
      {blocks.map((b) => {
        const g = byFlowGroup.get(b.flowId)
        const node = b.node || (flows || []).find((f) => f.flowId === b.flowId)
        const status = node ? (b.round === node.round ? node.status : (b.round == null ? node.status : 'waiting'))
          : (g && g.agents.length) ? g.agents[g.agents.length - 1].status || 'running'
          : 'waiting'
        const placeholder = !node && status === 'waiting'
        // 候选 agent：flowId 相同；round 精确匹配优先；该 flow 仅一轮时兼容旧数据无 round
        let candidates = g ? g.agents : []
        if (b.round != null) {
          const byRound = candidates.filter((a) => a.round === b.round)
          const noRound = candidates.filter((a) => a.round == null)
          const uniqueFlow = blocks.filter((x) => x.flowId === b.flowId).length === 1
          candidates = byRound.length ? byRound : (uniqueFlow ? noRound : [])
        }
        for (const a of candidates) assigned.add(a.id)
        return (
          <div key={`${b.flowId}|${b.round ?? 'x'}`} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <StatusDot status={status} size={7} />
              <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>
                {FLOW_LABELS[b.flowId] || b.flowId || node?.name}
              </span>
              {placeholder ? (
                <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>未触发，按需被选</span>
              ) : (
                <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>第 {(b.round ?? 0) + 1} 轮</span>
              )}
              {node?.note && (
                <span style={{ fontSize: 10.5, color: 'var(--content-fg-secondary)', background: 'var(--surface-secondary)', padding: '1px 8px', borderRadius: 'var(--radius-pill)' }}>
                  {node.note}
                </span>
              )}
              <span style={{ flex: 1 }} />
              <span style={{
                fontSize: 11, fontWeight: 510,
                color: status === 'completed' ? 'var(--status-success)'
                  : status === 'running' ? 'var(--status-progress)'
                  : 'var(--content-fg-tertiary)',
              }}>
                {FLOW_STATUS_LABELS[status] || status}
              </span>
            </div>
            {candidates.length > 0 && (
              <div style={{ marginTop: 4, marginLeft: 14, paddingLeft: 12, borderLeft: '1.5px solid var(--surface-border)', display: 'flex', flexDirection: 'column' }}>
                {candidates.map((a) => <AgentItem key={a.id} agent={a} onOpenAgent={onOpenAgent} />)}
              </div>
            )}
          </div>
        )
      })}
      {/* 兜底：无法归块的 agent（旧数据）平铺在最下方 */}
      {stageId === 'clean' && (() => {
        const rest = (agents || []).filter((a) => !assigned.has(a.id))
        return rest.length ? (
          <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column' }}>
            {rest.map((a) => <AgentItem key={a.id} agent={a} onOpenAgent={onOpenAgent} />)}
          </div>
        ) : null
      })()}
    </div>
  )
}
