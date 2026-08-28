import React, { useState } from 'react'
import { Icon } from '@/components/icons'
import { StatusDot } from '@/components/status'
import Markdown from '@/lib/markdown'
import FlowBlocks from '@/components/workflow/FlowBlocks'
import { FLOW_LABELS } from '@/lib/stages'   // 2026-08-27：卡头 statusText（runningFlow 显示"第 N 轮"）仍用——此前删 FlowNodes 时误删 import 导致 ReferenceError 白屏
import { cleanCliQuestion, fmtPair, fmtRaDec } from '@/lib/format'

/* 阶段卡片（设计文档 5.2 E7）：未展开 = 单行卡（状态点 + 阶段名 + 摘要）；
 * 展开 = 垂直子步骤时间线（竖线 + 节点 + 文字）。具体卡片具体设计：
 * 卡 1「任务理解」有子步骤时间线 + 完成态三项产出；其余卡片内容逐卡填充。
 */

function Substeps({ substeps }) {
  return (
    <div style={{ marginTop: 12 }}>
      {substeps.map((ss, i) => (
        <div key={ss.id} style={{ display: 'flex', alignItems: 'flex-start' }}>
          {/* 左侧节点列（P1-1：统一圆点不连线 7px；height 与文字行一致，
              圆点垂直居中于文字行而非整行——此前被 stretch 撑满导致偏上） */}
          <div style={{ display: 'flex', alignItems: 'center', width: 12, height: 24, flexShrink: 0 }}>
            <StatusDot status={ss.status} size={7} />
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

            {/* 2026-08-27: 卡3 步骤①"论文提取"分段——pdf→图片(convert) 与
                VLM 提取(extract) 两阶段，各有进度；全部完成才整行标"已完成"。
                旧任务事件无 phase（phases 空）→ 不渲染分段，保持单段原样。 */}
            {ss.phases && Object.keys(ss.phases).length > 0 && (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6, paddingLeft: 10, borderLeft: '1.5px solid var(--surface-border)' }}>
                {['convert', 'extract'].map((ph) => {
                  const p = ss.phases[ph]
                  if (!p) return null
                  const label = ph === 'convert' ? '拆分 PDF' : 'VLM 提取'
                  return (
                    <div key={ph} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <StatusDot status={p.status === 'completed' ? 'completed' : p.status === 'running' ? 'running' : 'waiting'} size={6} />
                      <span style={{ fontSize: 12, color: 'var(--content-fg-secondary)' }}>{label}</span>
                      {p.status === 'completed'
                        ? <span className="font-mono" style={{ fontSize: 11, color: 'var(--status-success)' }}>完成 {p.progress?.total ?? ''}</span>
                        : p.progress?.current
                          ? <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>第 {Math.min(p.progress.completed + 1, p.progress.total)}/{p.progress.total} — {p.progress.current}</span>
                          : <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>待开始</span>}
                    </div>
                  )
                })}
              </div>
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

/* 卡 1 完成态产出：结构化定义列表（P1-8 重设计：标签列统一 88px、SIMBAD otype
 * 友好映射、标准性质代码标签样式、RA/Dec 独立层级） */
const OTYPE_LABELS = {
  's*r': '红超巨星', G: '星系', '*': '恒星', '**': '双星系统',
  V: '变星', 'V*': '变星', IR: '红外源', 'LP*': '长周期变星',
  NIR: '近红外源', smm: '亚毫米源', UV: '紫外源', 'AB*': '共生星',
  GlC: '球状星团', OCl: '疏散星团', 'Cl*': '星团',
}

function UnderstandOutput({ output }) {
  const { targetEntity, simbad, properties } = output
  const otype = OTYPE_LABELS[simbad.otype] || simbad.otype || null
  return (
    <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* 区块一：天体身份（P1-8 v2：主次分明——目标天体为主标题，
           mainId/otype/坐标为元数据副行；组内间距 < 组间间距） */}
      <div>
        <div className="section-label" style={{ marginBottom: 6 }}>目标天体</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 18, fontWeight: 590, color: 'var(--content-fg)', letterSpacing: '-0.01em' }}>{targetEntity}</span>
          {simbad.mainId && (
            <span className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg-secondary)' }}>{simbad.mainId}</span>
          )}
          {otype && (
            <span style={{ fontSize: 10.5, padding: '1px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--accent-light)', color: 'var(--accent-text)' }}>
              {otype}
            </span>
          )}
        </div>
        {simbad.ra && simbad.dec ? (
          /* P1-6：RA/Dec 时角/度分秒制（原样小数直出改为天文标准格式） */
          <div className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg-tertiary)', marginTop: 4 }}>
            {fmtRaDec(simbad.ra, simbad.dec)}
          </div>
        ) : (
          Array.isArray(simbad.aliases) && simbad.aliases.length > 0 && (
            <div style={{ fontSize: 12, color: 'var(--content-fg-tertiary)', marginTop: 4 }}>
              别名：{simbad.aliases.slice(0, 3).join(' · ')}
              {simbad.aliases.length > 3 ? ` 等 ${simbad.aliases.length} 个` : ''}
            </div>
          )
        )}
      </div>

      {/* 区块二：标准性质（数据卡网格——名称 + 代码标签 + 单位紧凑成组） */}
      {properties.length > 0 && (
        <div>
          <div className="section-label" style={{ marginBottom: 6 }}>标准性质</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
            {properties.map((p) => (
              <div key={p.propertyId} className="row-item" style={{ padding: '8px 12px' }}>
                <div style={{ fontSize: 12.5, color: 'var(--content-fg)' }}>{p.name}</div>
                <div style={{ marginTop: 5, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <span
                    className="font-mono"
                    style={{
                      fontSize: 10.5,
                      color: 'var(--accent-text)',
                      background: 'var(--accent-light)',
                      padding: '1px 6px',
                      borderRadius: 4,
                    }}
                  >
                    {p.propertyId}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>{p.unit}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/* 步 id → 单位词（2026-08-27：卡 2 进度条文案按步类型区分——
 * 此前恒显示"星表"/"检索星表"，论文/补充材料的进度全部错配） */
const STEP_UNIT = {
  'database/match': '星表',
  'paper/search': '论文组',
  'paper/download': '篇论文',
  'supplementary/find': '篇文献',
  'supplementary/summary': '张表',
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
        <div key={i} className="trace-item">
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', color: 'var(--content-fg)' }}>
            <span style={{ fontWeight: 510 }}>{t.field}</span>
            {/* P1-6：fmtPair 统一 before→after 展示（缺值显示 —） */}
            <span className="font-mono" style={{ color: 'var(--content-fg-tertiary)', fontSize: 11 }}>{fmtPair(t.before, t.after)}</span>
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

/* 层 2：Agent 列表（workflow_history 结构）—— P1-2：点击行 → 右侧抽屉下钻
 *（视觉对齐 StageDetailPanel 的 AgentRow：状态点 + 名称 + 徽章 + 箭头） */
function AgentRow({ agent, onOpen }) {
  const traceCount = Array.isArray(agent.traces) ? agent.traces.length : 0
  const logCount = Array.isArray(agent.logs) ? agent.logs.length : 0
  return (
    <div
      onClick={onOpen}
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
      {agent.status === 'running' && (
        <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>执行中…</span>
      )}
      {agent.duration && (
        <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>{agent.duration}</span>
      )}
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

function AgentTree({ agents, onOpenAgent }) {
  if (!agents || agents.length === 0) return null
  return (
    <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 2 }}>
      {agents.map((a) => (
        <AgentRow key={a.id || a.agent} agent={a} onOpen={() => onOpenAgent(a, stage)} />
      ))}
    </div>
  )
}

/* 卡 5 动态流转序列：嵌套结构（2026-08-27 重构）——
 * 每个轮次块（数据规范化 第 N 轮 / 冲突消解 第 N 轮 / 人工审核）为容器，
 * 其下挂属于该块的 Agent（flow 上下文的权威归属来自后端：
 * agent 事件 flow_id + round 字段；旧任务无该字段时按子图 Agent 名单名字兜底）。
 * 未触发的块（无 flow 事件且无对应 agent）显示「未触发，按需被选」而非「等待中」。
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
              <div key={step.id} style={{ display: 'flex', alignItems: 'flex-start' }}>
                {/* P1-8：圆点列高度与文字行一致（22px），垂直居中于文字行 */}
                <div style={{ display: 'flex', alignItems: 'center', width: 18, height: 22, flexShrink: 0 }}>
                  <StatusDot status={step.status} size={7} />
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
                          ? `处理第 ${step.progress.completed + 1}/${step.progress.total}${STEP_UNIT[step.id]} — ${step.progress.current}`
                          : step.id === 'paper'
                            ? '正在检索论文'
                            : step.id === 'supplementary'
                              ? '正在定位补充材料'
                              : '正在检索星表'
                      }
                      doneLabel={
                        step.id === 'paper'
                          ? '检索完成'
                          : step.id === 'supplementary'
                            ? '定位完成'
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
/* 澄清记录（P1-8：折叠式——summary 只显示序号 + 回答状态，展开看提问 + 回答；
 * 无引用框/无终端原文；提问优先结构化字段，历史任务无 fields 用清洗文本） */
function ClarificationHistory({ clarifications }) {
  if (!clarifications || clarifications.length === 0) return null
  return (
    <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div className="hint-dim" style={{ fontSize: 11 }}>澄清记录</div>
      {clarifications.map((cl, i) => {
        const fields = Array.isArray(cl.fields) ? cl.fields : []
        const question = fields.length ? null : cleanCliQuestion(cl.question)
        return (
          <details key={i} style={{ fontSize: 13 }}>
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
              <Icon.ChevronRight style={{ width: 10, height: 10, flexShrink: 0, color: 'var(--content-fg-tertiary)' }} />
              <span style={{ fontSize: 12, fontWeight: 510, color: 'var(--content-fg)' }}>澄清 {i + 1}</span>
              {cl.answer ? (
                <span style={{ fontSize: 10.5, padding: '1px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--status-success-bg)', color: 'var(--status-success)', fontWeight: 510 }}>
                  已回答
                </span>
              ) : (
                <span style={{ fontSize: 10.5, padding: '1px 8px', borderRadius: 'var(--radius-pill)', background: 'var(--surface-secondary)', color: 'var(--content-fg-tertiary)' }}>
                  未回答
                </span>
              )}
              <span style={{ flex: 1 }} />
              {cl.answer && (
                <span className="hint-dim" style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 160 }}>
                  回答：{cl.answer}
                </span>
              )}
            </summary>
            <div style={{ marginTop: 4, padding: '8px 12px', background: 'var(--surface-secondary)', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', gap: 6 }}>
              {/* 提问：结构化字段（新任务）或清洗文本（历史任务） */}
              {fields.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {fields.map((f) => (
                    <div key={f.label} style={{ display: 'flex', gap: 10, fontSize: 12 }}>
                      <span style={{ width: 72, flexShrink: 0, color: 'var(--content-fg-tertiary)' }}>{f.label}</span>
                      <span style={{ color: 'var(--content-fg)' }}>{f.value}</span>
                    </div>
                  ))}
                </div>
              ) : (
                question && (
                  <div style={{ fontSize: 12, color: 'var(--content-fg-secondary)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                    {question}
                  </div>
                )
              )}
              {/* 回答 */}
              <div style={{ fontSize: 12, display: 'flex', gap: 10 }}>
                <span style={{ width: 72, flexShrink: 0, color: 'var(--content-fg-tertiary)' }}>回答</span>
                <span style={{ color: cl.answer ? 'var(--content-fg)' : 'var(--content-fg-tertiary)' }}>
                  {cl.answer || '未回答'}
                </span>
              </div>
            </div>
          </details>
        )
      })}
    </div>
  )
}

/* 数据源质量分布（洞察卡区块）——每个数据源一条水平质量条，颜色按质量等级
 *（excellent 绿 / good 青 / fair 蓝 / poor 红），分数右侧标注 + 等级 pill。
 * 样式对齐全站：状态色变量 + section-label + pill + font-mono 分数。 */
const QUAL_LEVEL_COLOR = {
  excellent: 'var(--status-success)',
  good: 'var(--accent-text)',
  fair: 'var(--status-progress)',
  poor: 'var(--status-error)',
}
const QUAL_LEVEL_LABEL = { excellent: '优', good: '良', fair: '中', poor: '差' }

function SourceQualityChart({ sourceScores }) {
  if (!sourceScores || sourceScores.length === 0) return null
  // 整体分布：按质量等级统计源数量（条形图——比较分类数量，饼图角度不精确）
  const ORDER = ['excellent', 'good', 'fair', 'poor']
  const total = sourceScores.length
  const counts = {}
  for (const s of sourceScores) counts[s.level] = (counts[s.level] || 0) + 1
  const max = Math.max(1, ...ORDER.map((l) => counts[l] || 0))
  const rows = ORDER
    .filter((l) => counts[l])
    .map((l) => ({ level: l, count: counts[l], pct: Math.round((counts[l] / total) * 100) }))
  return (
    <div style={{ marginTop: 14 }}>
      <div className="section-label" style={{ marginBottom: 8 }}>数据源质量分布</div>
      {/* 分布条形：宽度 = 该等级源数量（相对最大），颜色 = 等级状态色 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map((r) => {
          const color = QUAL_LEVEL_COLOR[r.level] || 'var(--content-fg-tertiary)'
          return (
            <div key={r.level} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ width: 40, flexShrink: 0, fontSize: 12, fontWeight: 510, color }}>{QUAL_LEVEL_LABEL[r.level] || r.level}</span>
              <div style={{ flex: 1, height: 10, borderRadius: 4, background: 'var(--surface-border-subtle)', overflow: 'hidden' }}>
                <div style={{ width: `${(r.count / max) * 100}%`, height: '100%', borderRadius: 4, background: color, transition: 'width .3s ease' }} />
              </div>
              <span className="font-mono" style={{ width: 96, flexShrink: 0, fontSize: 11, color: 'var(--content-fg-secondary)', textAlign: 'right' }}>{r.count} 个 · {r.pct}%</span>
            </div>
          )
        })}
      </div>
      <div className="hint-dim" style={{ marginTop: 8, fontSize: 11 }}>共 {total} 个数据源，按质量等级统计</div>
      {/* 明细：各源分数（折叠，hover 见全名） */}
      <details style={{ marginTop: 6 }}>
        <summary style={{ cursor: 'pointer', listStyle: 'none', display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
          <Icon.ChevronRight style={{ width: 10, height: 10, flexShrink: 0 }} />
          查看各源明细
        </summary>
        <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 5 }}>
          {sourceScores.map((s) => {
            const color = QUAL_LEVEL_COLOR[s.level] || 'var(--content-fg-tertiary)'
            return (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span title={s.id} style={{ width: 148, flexShrink: 0, fontSize: 11, color: 'var(--content-fg-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.id}</span>
                <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'var(--surface-border-subtle)', overflow: 'hidden' }}>
                  <div style={{ width: `${Math.round(s.score * 100)}%`, height: '100%', borderRadius: 3, background: color }} />
                </div>
                <span className="font-mono" style={{ width: 36, flexShrink: 0, fontSize: 11, color: 'var(--content-fg-tertiary)', textAlign: 'right' }}>{s.score.toFixed(2)}</span>
              </div>
            )
          })}
        </div>
      </details>
    </div>
  )
}

/* 卡「数据洞察」完成态产出（来自 /state 的 output_state.insights，结构见 hydrateInsights） */
function InsightOutput({ insights, onOpenInsights, sourceScores }) {
  const fi = Array.isArray(insights.field_insights) ? insights.field_insights.length : 0
  const rel = Array.isArray(insights.cross_field_relationships) ? insights.cross_field_relationships.length : 0
  const grade = insights.usage_recommendations?.overall_grade
  const g = String(grade || '').toLowerCase()
  const gradeColor = !grade ? null
    : /excellent|good|^a$|^a[-_]/.test(g) ? 'var(--status-success)'
    : /poor|bad|fail|^c$|^d$|^c[-_]|^d[-_]/.test(g) ? 'var(--status-error)'
    : 'var(--status-progress)'
  const chipStyle = {
    fontSize: 11, padding: '2px 10px', borderRadius: 'var(--radius-pill)',
    background: 'var(--surface-secondary)', border: '1px solid var(--surface-border-subtle)',
    color: 'var(--content-fg-secondary)',
  }
  return (
    <div style={{ marginTop: 12 }}>
      {insights.overall_narrative && (
        /* P1-7：综合叙述改 Markdown 渲染（加粗/列表/引用生效） */
        <div style={{
          fontSize: 13, color: 'var(--content-fg-secondary)', lineHeight: 1.7, marginBottom: 10,
          padding: '10px 12px', background: 'var(--surface-secondary)', borderRadius: 'var(--radius-md)',
        }}>
          <Markdown>{insights.overall_narrative}</Markdown>
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={chipStyle}>{fi} 条字段洞察</span>
        <span style={chipStyle}>{rel} 条跨字段关系</span>
        {grade && (
          <span style={{ ...chipStyle, color: gradeColor, borderColor: 'transparent', background: 'color-mix(in srgb, currentColor 10%, transparent)' }}>
            可用等级 {grade}
          </span>
        )}
        {onOpenInsights && (
          <button
            onClick={onOpenInsights}
            style={{
              marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 5,
              border: '1px solid var(--surface-border)', borderRadius: 'var(--radius-pill)',
              background: 'transparent', color: 'var(--content-fg)',
              fontSize: 12, padding: '4px 12px', cursor: 'pointer', fontWeight: 510,
            }}
          >
            查看完整报告<Icon.ChevronRight style={{ width: 10, height: 10 }} />
          </button>
        )}
      </div>
      {/* 数据源质量分布图（per_source_scores，颜色按等级状态色） */}
      <SourceQualityChart sourceScores={sourceScores} />
    </div>
  )
}

/* 2026-08-27：memo——stage 引用不变时跳过重渲染。usePipeline 每 100ms 批量
 * setStages（log flush），timeline 8 卡不做 memo 会全量重渲（主区滚动卡顿元凶）。
 * stage 对象引用只在所属卡变化时改变（map 返回原对象），配合 ChatView 稳定的
 * onToggle/onOpenAgent/onOpenInsights 引用即可生效。 */
const StageCard = React.memo(function StageCard({ stage, expanded, onToggle, onOpenInsights, onOpenAgent, sourceScores }) {
  const isExpanded = expanded
  // 2026-08-27：hover 已 CSS 化（.stage-card:hover）——滑动时不再触发 React 重渲染

  // 2026-08-14：运行中卡头显示具体子流程进度（替代笼统"进行中…"）——
  // clean/deliver/insight 优先显示当前 flow 轮次（如"规范化 第 2 轮"），
  // 其余显示最近启动的 Agent 名
  const runningFlow = (stage.flows || []).filter((f) => f.status === 'running').slice(-1)[0]
  const runningAgents = (stage.agents || []).filter((a) => a.status === 'running')
  const statusText = {
    waiting: '等待上游完成',
    running: stage.summary
      || (runningFlow ? `${FLOW_LABELS[runningFlow.flowId] || runningFlow.flowId} 第 ${runningFlow.round} 轮` : null)
      || (runningAgents.length ? `执行中：${runningAgents[runningAgents.length - 1].agent}` : null)
      || '进行中…',
    completed: stage.summary || '已完成',
    error: '执行失败',
    skipped: stage.summary || '已跳过',
    cancelled: '已取消',
  }[stage.status]
  // P1-3：卡头状态胶囊（对齐工作流 pill 视觉：状态色文字 + 浅色底）
  const statusPill = {
    completed: { color: 'var(--status-success)', bg: 'var(--status-success-bg)' },
    running: { color: 'var(--status-progress)', bg: 'var(--status-progress-bg)' },
    error: { color: 'var(--status-error)', bg: 'var(--status-error-bg)' },
    waiting: { color: 'var(--content-fg-tertiary)', bg: 'var(--surface-secondary)' },
    skipped: { color: 'var(--content-fg-tertiary)', bg: 'var(--surface-secondary)' },
    cancelled: { color: 'var(--content-fg-tertiary)', bg: 'var(--surface-secondary)' },
  }[stage.status] || { color: 'var(--content-fg-tertiary)', bg: 'var(--surface-secondary)' }

  return (
    <div
      data-component="stage-card"
      className="stage-card"
      style={{
        background: 'var(--surface-bg)',
        border: `1px solid ${stage.status === 'running' ? 'var(--status-progress)' : stage.status === 'error' ? 'var(--status-error)' : 'var(--surface-border)'}`,
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden',
      }}
    >
      {/* 头部：未展开态 = 单行卡（状态信息由状态点承载，不加彩色左边框） */}
      <div
        onClick={() => onToggle(stage.id)}   // 2026-08-27: 传 id 使 ChatView 的 toggleStage 引用可稳定（memo 依赖）
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '10px 14px',
          cursor: 'pointer',
        }}
      >
        <div style={{ width: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', marginRight: 10, flexShrink: 0 }}>
          <StatusDot status={stage.status} size={7} />
        </div>
        <span style={{ fontWeight: 510, fontSize: 14, color: 'var(--content-fg)' }}>{stage.name}</span>
        {stage.duration && (
          <span className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg-tertiary)', marginLeft: 10 }}>{stage.duration}</span>
        )}
        <span style={{ flex: 1 }} />
        {statusText && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 510,
              color: statusPill.color,
              background: statusPill.bg,
              padding: '2px 10px',
              borderRadius: 'var(--radius-pill)',
              marginRight: 8,
              maxWidth: 320,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
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
          ) : Array.isArray(stage.flows) && stage.flows.length ? (
            /* 2026-08-13：字段名修正 stage.flow → stage.flows（usePipeline 写入复数）；
               2026-08-27：嵌套块结构——轮次块内挂所属 Agent（FlowBlocks 共享组件） */
            <FlowBlocks flows={stage.flows} stageId={stage.id} agents={stage.agents} onOpenAgent={(a) => onOpenAgent(a, stage)} />
          ) : stage.agents ? (
            <AgentTree agents={stage.agents} onOpenAgent={onOpenAgent} />
          ) : stage.groups ? (
            <GroupSteps groups={stage.groups} />
          ) : null /* P1-8：无内容卡（如 done）展开区为空——不再显示"阶段内容设计进行中"占位 */}

          {stage.status === 'completed' && stage.id === 'understand' && stage.output && (
            <UnderstandOutput output={stage.output} />
          )}

          {/* 数据洞察卡完成态：综合叙述 + 计数 + 完整报告入口（stage.output 来自 /state） */}
          {stage.status === 'completed' && stage.id === 'insight' && stage.output && (
            <InsightOutput insights={stage.output} onOpenInsights={onOpenInsights} sourceScores={sourceScores} />
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
})
export default StageCard
