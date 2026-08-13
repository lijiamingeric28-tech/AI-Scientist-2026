import { useEffect, useState } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Icon } from '@/components/icons'
import { StatusDot } from '@/components/status'
import { FLOW_LABELS } from '@/lib/stages'

/* 工作流下钻面板（三级）：
 *   L1 阶段流程图（WorkflowView）→ 点击阶段节点
 *   L2 阶段执行明细：子步骤/检索分组进度、flow 轮次、Agent 列表、阶段日志
 *   L3 Agent 明细：耗时 / 数据修改轨迹（field before→after tool confidence）
 *      / 执行日志（检查器评分、LLM 初始化、httpx 工具调用等节点级明细）
 *
 * 数据来源全部是后端 SSE 真实事件（usePipeline 沉淀到 stage 上的
 * substeps/groups/flows/agents/logs），不存在 mock。
 * 后端没有独立的 tool_call 事件类型，但节点级 log 事件携带完整的工具/检查器
 * 执行信息——usePipeline 按 agent_started→completed 窗口将其归属到各 Agent
 *（agent.logs），L3"执行日志"分区即呈现这些明细；缺失时如实说明。
 */

const STAGE_STATUS_LABELS = {
  completed: '已完成', running: '执行中', error: '失败',
  waiting: '等待中', skipped: '已跳过', cancelled: '已取消',
}
const STAGE_STATUS_COLORS = {
  completed: 'var(--status-success)', running: 'var(--status-progress)', error: 'var(--status-error)',
  waiting: 'var(--content-fg-tertiary)', skipped: 'var(--content-fg-tertiary)', cancelled: 'var(--content-fg-tertiary)',
}

/* 步骤行：状态点 + 名称 + 详情 + 进度条 */
function StepRow({ step }) {
  const pr = step.progress
  const pct = pr && pr.total ? Math.round(((pr.completed || 0) / pr.total) * 100) : 0
  return (
    <div style={{ display: 'flex', gap: 10 }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 16, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', height: 22 }}>
          <StatusDot status={step.status} size={7} />
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0, paddingBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, height: 22 }}>
          <span style={{ fontSize: 13, color: 'var(--content-fg)' }}>{step.label}</span>
          {step.status === 'running' && (
            <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>进行中…</span>
          )}
          {pr && pr.total > 0 && (
            <span className="font-mono" style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
              {step.status === 'completed' ? `${pr.total}/${pr.total}` : `${pr.completed || 0}/${pr.total}`}
            </span>
          )}
        </div>
        {pr && pr.total > 0 && (
          <div style={{ height: 4, background: 'var(--surface-border)', borderRadius: 2, overflow: 'hidden', maxWidth: 320 }}>
            <div style={{
              height: '100%', borderRadius: 2, transition: 'width .3s ease',
              width: `${step.status === 'completed' ? 100 : pct}%`,
              background: step.status === 'completed' ? 'var(--status-success)' : 'var(--status-progress)',
            }} />
          </div>
        )}
        {step.detail && (
          <div className="hint-dim" style={{ marginTop: 4 }}>{step.detail}</div>
        )}
      </div>
    </div>
  )
}

/* L2 分区标题 */
function Section({ label, count, children }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span className="section-label">{label}</span>
        {count != null && <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>{count}</span>}
        <span style={{ height: 1, flex: 1, background: 'var(--surface-border-subtle)' }} />
      </div>
      {children}
    </div>
  )
}

/* L2：Agent 行（可点击进入 L3） */
function AgentRow({ agent, onOpen }) {
  const [hover, setHover] = useState(false)
  const traceCount = Array.isArray(agent.traces) ? agent.traces.length : 0
  const logCount = Array.isArray(agent.logs) ? agent.logs.length : 0
  return (
    <div
      onClick={onOpen}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '9px 12px', borderRadius: 'var(--radius-md)',
        border: '1px solid var(--surface-border-subtle)',
        background: hover ? 'var(--surface-secondary)' : 'var(--surface-bg)',
        cursor: 'pointer', marginBottom: 6, transition: 'background .12s',
      }}
    >
      <StatusDot status={agent.status} size={7} />
      <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>{agent.agent}</span>
      <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
        {STAGE_STATUS_LABELS[agent.status] || ''}
      </span>
      {agent.duration && (
        <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>{agent.duration}</span>
      )}
      <span style={{ flex: 1 }} />
      {logCount > 0 && (
        <span style={{
          fontSize: 11, color: 'var(--content-fg-secondary)',
          background: 'var(--surface-secondary)', border: '1px solid var(--surface-border-subtle)',
          padding: '1px 8px', borderRadius: 'var(--radius-pill)',
        }}>
          {logCount} 条执行日志
        </span>
      )}
      {traceCount > 0 && (
        <span style={{
          fontSize: 11, color: 'var(--content-fg-secondary)',
          background: 'var(--surface-secondary)', border: '1px solid var(--surface-border-subtle)',
          padding: '1px 8px', borderRadius: 'var(--radius-pill)',
        }}>
          {traceCount} 条修改
        </span>
      )}
      <Icon.ChevronRight style={{ width: 11, height: 11, color: 'var(--content-fg-tertiary)', flexShrink: 0 }} />
    </div>
  )
}

/* L3：单条修改轨迹 */
function TraceRow({ t }) {
  return (
    <div className="row-item" style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>{t.field}</span>
        <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
          {String(t.before ?? '—')} → {String(t.after ?? '—')}
        </span>
        {t.tool && (
          <span style={{
            marginLeft: 'auto', fontSize: 11, padding: '1px 8px', borderRadius: 'var(--radius-pill)',
            background: 'var(--surface-secondary)', border: '1px solid var(--surface-border-subtle)',
            color: 'var(--content-fg-secondary)', display: 'inline-flex', alignItems: 'center', gap: 4,
          }}>
            <Icon.Wrench style={{ width: 10, height: 10 }} />{t.tool}
          </span>
        )}
      </div>
      {t.reason && <div className="hint-dim" style={{ marginTop: 4 }}>{t.reason}</div>}
      {t.confidence != null && (
        <div style={{ marginTop: 4 }}>
          <span style={{
            fontSize: 11, padding: '1px 8px', borderRadius: 'var(--radius-pill)',
            background: 'var(--status-progress-bg)', color: 'var(--status-progress)',
          }}>
            置信度 {t.confidence}
          </span>
        </div>
      )}
    </div>
  )
}

/* 日志盒（阶段日志 / Agent 执行日志共用；usePipeline 按阶段保留最近 200 条、
 * 按 Agent 保留最近 300 条） */
function LogBox({ logs, maxHeight = 220 }) {
  return (
    <div style={{
      borderRadius: 'var(--radius-md)', border: '1px solid var(--surface-border-subtle)',
      background: 'var(--surface-secondary)', padding: '8px 10px',
      maxHeight, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 3,
    }}>
      {logs.map((l, i) => (
        <div key={i} className="font-mono" style={{ fontSize: 11, lineHeight: 1.5, display: 'flex', gap: 8 }}>
          <span style={{ color: 'var(--content-fg-tertiary)', flexShrink: 0 }}>{l.time}</span>
          {l.node && <span style={{ color: 'var(--content-fg-tertiary)', flexShrink: 0 }}>[{l.node}]</span>}
          <span style={{ color: l.level === 'error' ? 'var(--status-error)' : 'var(--content-fg-secondary)', wordBreak: 'break-all' }}>
            {l.message}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function StageDetailPanel({ stage, onClose, onShowStageInChat }) {
  // null = L2 阶段明细；否则为选中的 agent key（L3）
  const [agentKey, setAgentKey] = useState(null)

  // 切换阶段时回到 L2
  useEffect(() => { setAgentKey(null) }, [stage?.id])

  // Esc 关闭
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!stage) return null

  const agents = Array.isArray(stage.agents) ? stage.agents : []
  const flows = Array.isArray(stage.flows) ? stage.flows : []
  const logs = Array.isArray(stage.logs) ? stage.logs : []
  const errors = Array.isArray(stage.errors) ? stage.errors : []
  const agent = agentKey ? agents.find((a) => (a.id || a.agent) === agentKey) : null

  const hasSteps = (Array.isArray(stage.substeps) && stage.substeps.length > 0)
    || (Array.isArray(stage.groups) && stage.groups.length > 0)
  const stageEmpty = !hasSteps && !flows.length && !agents.length && !logs.length && !errors.length && !stage.summary

  return (
    <>
      {/* 遮罩 */}
      <div
        onClick={onClose}
        className="animate-fade-in"
        style={{ position: 'fixed', inset: 0, background: 'var(--overlay)', zIndex: 65 }}
      />

      {/* 下钻面板 */}
      <aside
        data-component="stage-detail-panel"
        className="glass animate-drawer-in"
        style={{
          position: 'fixed', top: 0, right: 0, bottom: 0, zIndex: 66,
          width: 520, maxWidth: '94vw',
          display: 'flex', flexDirection: 'column', overflow: 'hidden',
          borderLeft: '1px solid var(--glass-border)',
          boxShadow: 'var(--shadow-modal)',
        }}
      >
        {/* 面包屑 + 关闭 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '14px 16px 10px', flexShrink: 0 }}>
          {agent ? (
            <button
              onClick={() => setAgentKey(null)}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 4, border: 'none', background: 'transparent',
                cursor: 'pointer', color: 'var(--content-fg-secondary)', fontSize: 12, padding: '2px 4px',
              }}
            >
              <Icon.ChevronLeft style={{ width: 11, height: 11 }} />返回阶段
            </button>
          ) : null}
          <nav style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--content-fg-tertiary)', flex: 1, minWidth: 0, overflow: 'hidden', whiteSpace: 'nowrap' }}>
            <span>执行明细</span>
            <Icon.ChevronRight style={{ width: 9, height: 9, flexShrink: 0 }} />
            <span style={{ color: agent ? 'var(--content-fg-tertiary)' : 'var(--content-fg)', fontWeight: agent ? 400 : 510 }}>{stage.name}</span>
            {agent && (
              <>
                <Icon.ChevronRight style={{ width: 9, height: 9, flexShrink: 0 }} />
                <span style={{ color: 'var(--content-fg)', fontWeight: 510 }}>{agent.agent}</span>
              </>
            )}
          </nav>
          <button
            onClick={onClose}
            style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: 'var(--content-fg-tertiary)', display: 'flex', padding: 4 }}
            title="关闭"
          >
            <Icon.Close />
          </button>
        </div>

        <ScrollArea className="flex-1">
          <div style={{ padding: '4px 16px 24px' }}>
            <div key={agentKey || '__stage__'} className="animate-tab-in">

            {/* ───────── L3：Agent 明细 ───────── */}
            {agent ? (
              <div>
                {/* 状态行 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                  <StatusDot status={agent.status} size={8} />
                  <span style={{ fontSize: 12, color: STAGE_STATUS_COLORS[agent.status] || 'var(--content-fg-tertiary)' }}>
                    {STAGE_STATUS_LABELS[agent.status] || '未知状态'}
                  </span>
                  {agent.duration && (
                    <span className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg-tertiary)' }}>耗时 {agent.duration}s</span>
                  )}
                </div>

                {agent.reason && (
                  <div className="hint" style={{ marginBottom: 14 }}>{agent.reason}</div>
                )}

                <Section label="数据修改轨迹" count={(agent.traces || []).length || null}>
                  {(agent.traces || []).length ? (
                    agent.traces.map((t, i) => <TraceRow key={i} t={t} />)
                  ) : (Array.isArray(agent.logs) && agent.logs.length) ? (
                    <div className="hint-dim" style={{ padding: '4px 2px' }}>
                      该 Agent 未修改数据（评估 / 评分类节点只读不写）
                    </div>
                  ) : (
                    <div className="empty-state" style={{ padding: '24px 12px' }}>
                      <Icon.Wrench style={{ width: 16, height: 16, opacity: 0.6 }} />
                      <span style={{ fontSize: 'var(--fs-sm)' }}>后端未上报该 Agent 的修改轨迹</span>
                    </div>
                  )}
                </Section>

                {/* 执行日志：后端节点级 log 事件（检查器评分 / LLM 初始化 /
                    httpx 工具调用），usePipeline 按 agent 运行窗口归属 */}
                <Section label="执行日志 · 工具与检查器调用" count={(agent.logs || []).length || null}>
                  {(Array.isArray(agent.logs) && agent.logs.length) ? (
                    <LogBox logs={agent.logs} maxHeight={340} />
                  ) : (
                    <div className="empty-state" style={{ padding: '24px 12px' }}>
                      <Icon.Wrench style={{ width: 16, height: 16, opacity: 0.6 }} />
                      <span style={{ fontSize: 'var(--fs-sm)' }}>后端未上报该 Agent 的节点级执行日志</span>
                    </div>
                  )}
                </Section>
              </div>
            ) : (
              /* ───────── L2：阶段执行明细 ───────── */
              <div>
                {/* 阶段状态头 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <StatusDot status={stage.status} size={8} />
                  <span style={{ fontSize: 15, fontWeight: 510, color: 'var(--content-fg)' }}>{stage.name}</span>
                  <span style={{ fontSize: 12, color: STAGE_STATUS_COLORS[stage.status] || 'var(--content-fg-tertiary)' }}>
                    {STAGE_STATUS_LABELS[stage.status] || '—'}
                  </span>
                  {stage.duration && (
                    <span className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg-tertiary)' }}>{stage.duration}</span>
                  )}
                  <span style={{ flex: 1 }} />
                  {onShowStageInChat && (
                    <button
                      onClick={() => onShowStageInChat(stage.id)}
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 5,
                        border: '1px solid var(--surface-border)', borderRadius: 'var(--radius-pill)',
                        background: 'transparent', color: 'var(--content-fg-secondary)',
                        fontSize: 11, padding: '3px 12px', cursor: 'pointer', flexShrink: 0,
                      }}
                    >
                      <Icon.MessageSquare style={{ width: 11, height: 11 }} />在对话中查看
                    </button>
                  )}
                </div>
                {stage.summary && <div className="hint" style={{ marginBottom: 14 }}>{stage.summary}</div>}

                {stageEmpty && stage.status === 'waiting' && (
                  <div className="empty-state" style={{ padding: '40px 12px' }}>
                    <span style={{ fontSize: 'var(--fs-sm)' }}>该阶段尚未开始执行</span>
                  </div>
                )}

                {/* 步骤进度（子步骤 / 检索三路分组） */}
                {Array.isArray(stage.substeps) && stage.substeps.length > 0 && (
                  <Section label="执行步骤">
                    {stage.substeps.map((st) => <StepRow key={st.id} step={st} />)}
                  </Section>
                )}
                {Array.isArray(stage.groups) && stage.groups.map((g) => (
                  <Section key={g.id} label={`${g.name}路径`}>
                    {(g.steps || []).map((st) => <StepRow key={st.id} step={st} />)}
                  </Section>
                ))}

                {/* flow 轮次 */}
                {flows.length > 0 && (
                  <Section label="流程轮次" count={flows.length}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {flows.map((f) => (
                        <div key={f.key} className="row-item" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px' }}>
                          <StatusDot status={f.status} size={7} />
                          <span style={{ fontSize: 13, color: 'var(--content-fg)', fontWeight: 510 }}>
                            {FLOW_LABELS[f.flowId] || f.flowId}
                          </span>
                          <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>第 {f.round} 轮</span>
                          <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
                            {STAGE_STATUS_LABELS[f.status] || f.status}
                          </span>
                        </div>
                      ))}
                    </div>
                  </Section>
                )}

                {/* Agent 列表 → L3 */}
                {agents.length > 0 && (
                  <Section label="Agent 明细" count={agents.length}>
                    {agents.map((a) => (
                      <AgentRow key={a.id || a.agent} agent={a} onOpen={() => setAgentKey(a.id || a.agent)} />
                    ))}
                    <div className="hint-dim" style={{ marginTop: 4 }}>
                      点击 Agent 查看其执行日志（检查器 / LLM / 工具调用）与数据修改轨迹。
                    </div>
                  </Section>
                )}

                {/* 阶段错误 */}
                {errors.length > 0 && (
                  <Section label="阶段错误" count={errors.length}>
                    {errors.map((e, i) => (
                      <div key={i} style={{
                        display: 'flex', gap: 8, padding: '7px 10px', borderRadius: 'var(--radius-sm)',
                        background: 'var(--status-error-bg)', fontSize: 12, lineHeight: 1.5, marginBottom: 4,
                      }}>
                        <span style={{ color: 'var(--status-error)', fontWeight: 510, flexShrink: 0 }}>✕ {e.node || '错误'}</span>
                        <span style={{ color: 'var(--content-fg-secondary)' }}>{e.message}</span>
                      </div>
                    ))}
                  </Section>
                )}

                {/* 阶段日志 */}
                {logs.length > 0 && (
                  <Section label="阶段日志" count={logs.length}>
                    <LogBox logs={logs} />
                  </Section>
                )}
              </div>
            )}
            </div>
          </div>
        </ScrollArea>
      </aside>
    </>
  )
}
