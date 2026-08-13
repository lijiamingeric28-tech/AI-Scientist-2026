import { Icon } from '@/components/icons'
import { StatusDot } from '@/components/status'
import Markdown from '@/lib/markdown'

/* 阶段卡片（设计文档 5.2 E7）：未展开 = 单行卡（状态点 + 阶段名 + 摘要）；
 * 展开 = 垂直子步骤时间线（竖线 + 节点 + 文字）。具体卡片具体设计：
 * 卡 1「任务理解」有子步骤时间线 + 完成态三项产出；其余卡片内容逐卡填充。
 */

function Substeps({ substeps }) {
  return (
    <div style={{ marginTop: 12 }}>
      {substeps.map((ss, i) => (
        <div key={ss.id} style={{ display: 'flex' }}>
          {/* 左侧时间线：节点 + 竖线 */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 18, flexShrink: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', height: 24 }}>
              <StatusDot status={ss.status} size={8} />
            </div>
            {i < substeps.length - 1 && (
              <div
                style={{
                  width: 2,
                  flex: 1,
                  minHeight: 20,
                  borderRadius: 1,
                  background:
                    ss.status === 'completed'
                      ? 'var(--status-success)'
                      : 'var(--surface-border)',
                  opacity: ss.status === 'completed' ? 0.6 : 1,
                }}
              />
            )}
          </div>
          {/* 节点内容（与圆点中心对齐） */}
          <div style={{ paddingBottom: 14, paddingLeft: 8, flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', height: 24, gap: 8 }}>
              <span style={{ fontSize: 13, color: 'var(--content-fg)' }}>{ss.label}</span>
              {ss.status === 'running' && (
                <span style={{ color: 'var(--content-fg-tertiary)', marginLeft: 4, fontSize: 12 }}>进行中…</span>
              )}
            </div>

            {/* 进度条（卡 2/3 共用样式） */}
            {ss.progress && (
              <ProgressBar
                label={
                  ss.progress.current
                    ? `${ss.progress.prefix || '处理'}第 ${ss.progress.completed + 1}/${ss.progress.total} — ${ss.progress.current}`
                    : '处理中…'
                }
                doneLabel={ss.progress.doneLabel || '完成'}
                completed={ss.progress.completed}
                total={ss.progress.total}
                done={ss.status === 'completed'}
              />
            )}

            {/* 完成摘要 */}
            {ss.detail && (
              <div style={{ fontSize: 12, color: 'var(--content-fg-secondary)', lineHeight: 1.6, marginTop: 4 }}>
                {ss.detail}
              </div>
            )}

            {/* 失败原因列表（bbox 验证失败，红字打印） */}
            {ss.failures && ss.failures.length > 0 && (
              <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 3 }}>
                {ss.failures.map((f, j) => (
                  <div key={j} style={{ fontSize: 12, lineHeight: 1.5, display: 'flex', gap: 8 }}>
                    <span style={{ color: 'var(--status-error)', flexShrink: 0, fontWeight: 510 }}>✕ {f.key}</span>
                    <span style={{ color: 'var(--content-fg-secondary)' }}>{f.reason}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

/* 卡 1 完成态产出：结构化定义列表（固定列对齐，回归主题色） */
function UnderstandOutput({ output }) {
  const { targetEntity, simbad, properties } = output
  const labelStyle = {
    width: 88,
    flexShrink: 0,
    fontSize: 12,
    fontWeight: 510,
    color: 'var(--content-fg-tertiary)',
    letterSpacing: '0.03em',
    paddingTop: 2,
  }
  return (
    <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* 目标天体 */}
      <div style={{ display: 'flex', gap: 12 }}>
        <span style={labelStyle}>目标天体</span>
        <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>{targetEntity}</span>
      </div>

      {/* SIMBAD 身份（main_id + 类型一行，坐标独立一行） */}
      <div style={{ display: 'flex', gap: 12 }}>
        <span style={labelStyle}>SIMBAD 身份</span>
        <div style={{ fontSize: 13, color: 'var(--content-fg)', lineHeight: 1.5 }}>
          <div>
            {simbad.mainId} · {simbad.otype}
          </div>
          <div className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg-secondary)', marginTop: 2 }}>
            RA {simbad.ra} · Dec {simbad.dec}
          </div>
        </div>
      </div>

      {/* 标准性质：三列网格（名称 | property_id | 标准单位） */}
      <div style={{ display: 'flex', gap: 12 }}>
        <span style={labelStyle}>标准性质</span>
        <div
          style={{
            flex: 1,
            display: 'grid',
            gridTemplateColumns: '72px 108px 1fr',
            gap: '4px 10px',
            fontSize: 13,
            alignItems: 'center',
          }}
        >
          {properties.map((p) => (
            <div key={p.propertyId} style={{ display: 'contents' }}>
              <span style={{ color: 'var(--content-fg)' }}>{p.name}</span>
              <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
                {p.propertyId}
              </span>
              <span style={{ color: 'var(--content-fg-secondary)', fontSize: 12 }}>{p.unit}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/* 进度条（卡 2 专用）：label 为左侧文字（进行中如"检索第 X/N 个星表 — Gaia DR3"），
 * done 时整条绿色并显示完成文案 */
function ProgressBar({ label, completed, total, done, doneLabel }) {
  const pct = total ? Math.round((completed / total) * 100) : 0
  return (
    <div style={{ marginTop: 8, maxWidth: 420 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4, gap: 12 }}>
        <span
          style={{
            fontSize: 12,
            color: 'var(--content-fg-secondary)',
            fontFamily: done ? 'inherit' : 'ui-monospace, Menlo, Consolas, monospace',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            flex: 1,
          }}
        >
          {label}
        </span>
        <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', flexShrink: 0 }}>
          {done ? doneLabel || '完成' : `${completed}/${total}`}
        </span>
      </div>
      <div style={{ height: 5, background: 'var(--surface-border)', borderRadius: 3, overflow: 'hidden' }}>
        <div
          style={{
            height: '100%',
            width: `${pct}%`,
            borderRadius: 3,
            background: done ? 'var(--status-success)' : 'var(--status-progress)',
            transition: 'width 0.3s ease',
          }}
        />
      </div>
    </div>
  )
}

/* 层 3：data_trace 修改轨迹（field/before→after/tool/reason/confidence） */
function Traces({ traces }) {
  if (!traces || traces.length === 0) return null
  return (
    <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {traces.map((t, i) => (
        <div
          key={i}
          style={{
            padding: '6px 10px',
            background: 'var(--surface-secondary)',
            borderRadius: 6,
            fontSize: 12,
            lineHeight: 1.6,
          }}
        >
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', color: 'var(--content-fg)' }}>
            <span style={{ fontWeight: 510 }}>{t.field}</span>
            <span className="font-mono" style={{ color: 'var(--content-fg-tertiary)', fontSize: 11 }}>{t.before} → {t.after}</span>
            <span style={{ color: 'var(--accent-text)', fontSize: 11, marginLeft: 'auto' }}>{t.tool}</span>
          </div>
          <div style={{ color: 'var(--content-fg-tertiary)', fontSize: 11, marginTop: 2 }}>
            {/* L-09：data_trace 无 confidence 时不渲染该段（避免显示"置信度 undefined"） */}
            {t.reason}{t.confidence != null ? ` · 置信度 ${t.confidence}` : ''}
          </div>
        </div>
      ))}
    </div>
  )
}

/* 层 2：Agent 列表（workflow_history 结构）—— 点击展开 data_trace 轨迹 */
function AgentTree({ agents }) {
  if (!agents || agents.length === 0) return null
  return (
    <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 2 }}>
      {agents.map((a) => (
        <details key={a.id || a.agent} style={{ fontSize: 13 }}>
          <summary
            style={{
              cursor: 'pointer',
              listStyle: 'none',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '4px 0',
            }}
          >
            <StatusDot status={a.status} size={6} />
            <span style={{ color: 'var(--content-fg)', fontWeight: 510, fontSize: 13 }}>{a.agent}</span>
            {a.status === 'running' && (
              <span style={{ color: 'var(--content-fg-tertiary)', fontSize: 11 }}>执行中…</span>
            )}
            {a.duration && (
              <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginLeft: 'auto' }}>
                {a.duration}
              </span>
            )}
            <Icon.ChevronDown style={{ width: 10, height: 10, flexShrink: 0, color: 'var(--content-fg-tertiary)' }} />
          </summary>
          {a.reason && (
            <div style={{ padding: '2px 0 4px 14px', fontSize: 12, color: 'var(--content-fg-secondary)', lineHeight: 1.6 }}>
              {a.reason}
            </div>
          )}
          <div style={{ paddingLeft: 14 }}>
            <Traces traces={a.traces} />
          </div>
        </details>
      ))}
    </div>
  )
}

/* 卡 5 动态流转序列：流转节点（规范化/冲突消解 × 轮次）→ AgentTree */
function FlowNodes({ flow }) {
  if (!flow || flow.length === 0) return null
  return (
    <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {flow.map((node) => (
        <div
          key={node.id}
          style={{
            border: '1px solid var(--surface-border-subtle)',
            borderRadius: 8,
            padding: '8px 12px',
            background: 'var(--surface-secondary)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <StatusDot status={node.status} size={7} />
            <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>
              {node.name} 第 {node.round} 轮
            </span>
            {node.note && (
              <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', background: 'var(--surface-bg)', padding: '1px 6px', borderRadius: 4 }}>
                {node.note}
              </span>
            )}
            {node.status === 'running' && (
              <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>执行中…</span>
            )}
          </div>
          <AgentTree agents={node.agents} />
        </div>
      ))}
    </div>
  )
}

/* 卡 2 三路分组：每组标题 + 子步骤（状态点 + 标签 + 详情/进度条） */
function GroupSteps({ groups }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 12 }}>
      {groups.map((group) => (
        <div key={group.id}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 510,
              color: 'var(--content-fg-tertiary)',
              marginBottom: 8,
              letterSpacing: '0.04em',
            }}
          >
            {group.name}
          </div>
          {/* 卡 6：组内为 agent 列表（导出/洞察） */}
          {group.agents ? (
            <AgentTree agents={group.agents} />
          ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {group.steps.map((step) => (
              <div key={step.id} style={{ display: 'flex' }}>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 18, flexShrink: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', height: 22 }}>
                    <StatusDot status={step.status} size={7} />
                  </div>
                </div>
                <div style={{ flex: 1, paddingLeft: 8, paddingBottom: 10, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', height: 22, gap: 8 }}>
                    <span style={{ fontSize: 13, color: 'var(--content-fg)' }}>{step.label}</span>
                    {step.status === 'running' && (
                      <span style={{ fontSize: 12, color: 'var(--content-fg-tertiary)' }}>进行中…</span>
                    )}
                  </div>
                  {step.detail && (
                    <div style={{ fontSize: 12, color: 'var(--content-fg-secondary)', lineHeight: 1.6, marginTop: 2 }}>
                      {step.detail}
                    </div>
                  )}
                  {step.progress && (
                    <ProgressBar
                      label={
                        step.progress.current
                          ? `检索第 ${step.progress.completed + 1}/${step.progress.total} 个${step.progress.labelKind === 'paper' ? '' : '星表'} — ${step.progress.current}`
                          : step.progress.labelKind === 'paper'
                            ? '正在下载 PDF…'
                            : '正在检索星表…'
                      }
                      doneLabel={
                        step.progress.labelKind === 'paper'
                          ? '下载完成'
                          : '检索完成'
                      }
                      completed={step.progress.completed}
                      total={step.progress.total}
                      done={step.status === 'completed'}
                    />
                  )}
                  {step.substatus && (
                    <div style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginTop: 2, fontFamily: 'ui-monospace, Menlo, Consolas, monospace' }}>
                      {step.substatus}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
          )}
        </div>
      ))}
    </div>
  )
}

/* 澄清历史（已折叠的交互卡，可展开回溯） */
function ClarificationHistory({ clarifications }) {
  if (!clarifications || clarifications.length === 0) return null
  return (
    <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
      {clarifications.map((cl, i) => (
        <details key={i} style={{ fontSize: 13 }}>
          <summary
            style={{
              cursor: 'pointer',
              color: 'var(--content-fg-secondary)',
              listStyle: 'none',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <Icon.ChevronRight style={{ width: 10, height: 10, flexShrink: 0 }} />
            <span style={{ color: 'var(--status-progress)' }}>●</span>
            <span>
              澄清 {i + 1} · 已回答：{cl.answer || '（跳过）'}
            </span>
          </summary>
          <div
            style={{
              marginTop: 6,
              padding: '8px 12px',
              background: 'var(--surface-secondary)',
              borderRadius: 6,
              color: 'var(--content-fg-secondary)',
              whiteSpace: 'pre-wrap',
              lineHeight: 1.6,
              fontSize: 12,
            }}
          >
            {cl.question}
          </div>
        </details>
      ))}
    </div>
  )
}

export default function StageCard({ stage, expanded, onToggle }) {
  const isExpanded = expanded

  const statusText = {
    waiting: '等待上游完成',
    running: stage.summary || '进行中…',
    completed: stage.summary || '已完成',
    error: '执行失败',
    skipped: stage.summary || '已跳过',
    cancelled: '已取消',
  }[stage.status]

  return (
    <div
      style={{
        background: 'var(--surface-bg)',
        border: `1px solid ${stage.status === 'running' ? 'var(--status-progress)' : 'var(--surface-border)'}`,
        borderRadius: 8,
        overflow: 'hidden',
      }}
    >
      {/* 头部：未展开态 = 单行卡 */}
      <div
        onClick={onToggle}
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '10px 14px',
          cursor: 'pointer',
          borderLeft: `3px solid ${
            stage.status === 'completed' ? 'var(--status-success)'
            : stage.status === 'running' ? 'var(--status-progress)'
            : stage.status === 'error' ? 'var(--status-error)'
            : stage.errors && stage.errors.length > 0 ? 'var(--status-error)'   // M-23: warn 级阶段错误 → 红态
            : 'var(--surface-border)'
          }`,
        }}
      >
        <div style={{ width: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', marginRight: 10, flexShrink: 0 }}>
          <StatusDot status={stage.status} size={8} />
        </div>
        <span style={{ fontWeight: 510, fontSize: 14, color: 'var(--content-fg)' }}>{stage.name}</span>
        {stage.duration && (
          <span className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg-tertiary)', marginLeft: 10 }}>{stage.duration}</span>
        )}
        <span style={{ flex: 1 }} />
        {statusText && (
          <span
            style={{
              fontSize: 12,
              color: stage.status === 'error' ? 'var(--status-error)' : 'var(--content-fg-tertiary)',
              marginRight: 8,
            }}
          >
            {statusText}
          </span>
        )}
        <div style={{ color: 'var(--content-fg-tertiary)', transform: isExpanded ? 'rotate(0deg)' : 'rotate(-90deg)', transition: 'transform 0.15s' }}>
          <Icon.ChevronDown />
        </div>
      </div>

      {/* 展开态 */}
      {isExpanded && (
        <div style={{ padding: '4px 14px 14px 42px', borderTop: '1px solid var(--surface-border-subtle)' }}>
          {stage.substeps ? (
            <Substeps substeps={stage.substeps} />
          ) : stage.flow ? (
            <FlowNodes flow={stage.flow} />
          ) : stage.agents ? (
            <AgentTree agents={stage.agents} />
          ) : stage.groups ? (
            <GroupSteps groups={stage.groups} />
          ) : (
            <div style={{ marginTop: 10, fontSize: 13, color: 'var(--content-fg-tertiary)' }}>
              阶段内容设计进行中
            </div>
          )}

          {stage.status === 'completed' && stage.id === 'understand' && stage.output && (
            <UnderstandOutput output={stage.output} />
          )}

          <ClarificationHistory clarifications={stage.clarifications} />

          {/* M-23: 阶段降级失败（error warn 事件）→ 红态错误行（D10 错误总表消费侧） */}
          {stage.errors && stage.errors.length > 0 && (
            <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {stage.errors.map((e, j) => (
                <div key={j} style={{ fontSize: 12, lineHeight: 1.5, display: 'flex', gap: 8 }}>
                  <span style={{ color: 'var(--status-error)', flexShrink: 0, fontWeight: 510 }}>⚠ {e.node || '阶段错误'}</span>
                  <span style={{ color: 'var(--content-fg-secondary)' }}>{e.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
