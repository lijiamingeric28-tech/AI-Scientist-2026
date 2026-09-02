import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'

/* ========== Icon Components ========== */
const Icon = {
  Plus: (p) => <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" {...p}><path d="M8 3v10M3 8h10" /></svg>,
  Send: (p) => <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M14 2L7 9M14 2l-4.5 12-2.5-5.5L2 6z" /></svg>,
  Paperclip: (p) => <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M13.5 7.5l-6 6a3.5 3.5 0 01-5-5l6-6a2.5 2.5 0 013.5 3.5l-6 6a1.5 1.5 0 01-2-2l5.5-5.5" /></svg>,
  Check: (p) => <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M2.5 6l2.5 2.5 4.5-5" /></svg>,
  ChevronDown: (p) => <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M3 4.5l3 3 3-3" /></svg>,
  PanelRight: (p) => <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" {...p}><rect x="2" y="2" width="12" height="12" rx="2" /><path d="M10 2v12" /></svg>,
  MessageSquare: (p) => <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M14 10a1 1 0 01-1 1H5l-3 3V3a1 1 0 011-1h10a1 1 0 011 1z" /></svg>,
  Network: (p) => <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...p}><circle cx="4" cy="4" r="1.5" /><circle cx="12" cy="4" r="1.5" /><circle cx="4" cy="12" r="1.5" /><circle cx="12" cy="12" r="1.5" /><path d="M5.5 4h5M4 5.5v5M12 5.5v5M5.5 12h5" /></svg>,
  FileText: (p) => <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M8 1H3.5A1.5 1.5 0 002 2.5v9A1.5 1.5 0 003.5 13h7a1.5 1.5 0 001.5-1.5V5L8 1z" /><path d="M8 1v4h4M5 7h4M5 9.5h4M5 4.5h1" /></svg>,
  Settings: (p) => <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" {...p}><circle cx="8" cy="8" r="2" /><path d="M8 2v2M8 12v2M2 8h2M12 8h2M3.75 3.75l1.5 1.5M10.75 10.75l1.5 1.5M12.25 3.75l-1.5 1.5M5.25 10.75l-1.5 1.5" /></svg>,
  Close: (p) => <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" {...p}><path d="M3.5 3.5l7 7M10.5 3.5l-7 7" /></svg>,
  Wrench: (p) => <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M7 1.5a3.5 3.5 0 00-3 5L1.5 9l1.5 1.5L5.5 8a3.5 3.5 0 005-3L8 3.5 6.5 5 5 3.5 6.5 2z" /></svg>,
  Download: (p) => <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M7 2v7.5M3.5 6.5L7 10l3.5-3.5M2 12h10" /></svg>,
  Sparkle: (p) => <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M8 2l1.5 4L14 7.5 9.5 9 8 14 6.5 9 2 7.5l4.5-1.5z" /></svg>,
}

/* ========== Mock Data ========== */
const taskHistory = [
  { id: '1', title: '锂电池正极材料数据提取', time: '10 分钟前', status: 'running' },
  { id: '2', title: '钛合金疲劳强度分析', time: '2 小时前', status: 'completed' },
  { id: '3', title: '钙钛矿太阳能电池参数提取', time: '昨天', status: 'completed' },
  { id: '4', title: '碳纤维复合材料力学性能', time: '2 天前', status: 'completed' },
  { id: '5', title: '石墨烯导热系数数据整理', time: '3 天前', status: 'error' },
  { id: '6', title: '形状记忆合金相变温度', time: '4 天前', status: 'completed' },
]

const currentTask = { id: '1', title: '锂电池正极材料数据提取' }

const stages = [
  { id: 'intent', name: '意图澄清', status: 'completed', duration: '2.3s', summary: '已识别提取目标：锂电池正极材料的电化学性能参数' },
  { id: 'retrieval', name: '知识检索', status: 'completed', duration: '4.1s', summary: '从 Materials Project 和 OQMD 检索到 12 篇相关文献' },
  { id: 'extraction', name: '数据提取', status: 'completed', duration: '8.5s', summary: '从检索到的 3 篇核心文献中提取了 24 个结构化数据字段' },
  { id: 'quality', name: '数据质量评估', status: 'in_progress', duration: '3.2s', summary: '正在评估数据完整性、一致性和规范性...' },
  { id: 'conflict', name: '冲突分析', status: 'waiting', duration: '-', summary: '等待质量评估完成' },
  { id: 'normalization', name: '规范化', status: 'waiting', duration: '-', summary: '等待冲突分析完成' },
  { id: 'export', name: '导出', status: 'waiting', duration: '-', summary: '等待规范化完成' },
]

const stageDetails = {
  intent: {
    agents: [{
      name: '意图澄清 Agent', duration: '2.3s', status: 'completed',
      tools: [
        { name: 'LLM 调用: 意图解析', duration: '1.1s', status: 'completed', input: 'Model: deepseek-chat\nPrompt: 分析用户的研究数据提取需求...', output: '提取目标: 锂电池正极材料\n数据字段: 比容量, 循环寿命, 倍率性能\n材料体系: NCM, LFP, NCA' },
        { name: 'Tool: 领域知识库检索', duration: '0.8s', status: 'completed', input: 'Query: 锂电池正极材料标准参数\nDatabase: Materials Science KB', output: '返回 8 个标准参数字段定义\n匹配领域本体: battery_cathode_material' },
        { name: 'LLM 调用: 结构化输出', duration: '0.4s', status: 'completed', input: 'Model: deepseek-chat\nFormat: JSON Schema v2', output: '{ "target": "cathode_material", "fields": 8, "confidence": 0.94 }' },
      ],
    }],
  },
  retrieval: {
    agents: [{
      name: '检索 Agent', duration: '4.1s', status: 'completed',
      tools: [
        { name: 'Tool: 数据库检索', duration: '1.2s', status: 'completed', input: 'Sources: Materials Project, OQMD\nQuery: Li cathode electrochemistry', output: '命中 47 条记录\nTop-5 相关性: 0.95, 0.91, 0.88, 0.85, 0.82' },
        { name: 'LLM 调用: 相关性评估', duration: '2.1s', status: 'completed', input: 'Model: deepseek-chat\nTask: 评估检索结果与提取目标的相关性', output: '筛选 12 篇高度相关文献\n排除 35 篇低相关性记录\n平均相关性评分: 0.89' },
        { name: 'Tool: PDF 文档获取', duration: '0.8s', status: 'completed', input: 'Documents: 3 PDF files\nTotal: 42 pages', output: '成功获取 3 篇全文 PDF\nOCR 预处理完成' },
      ],
    }],
  },
  extraction: {
    agents: [{
      name: '提取 Agent', duration: '8.5s', status: 'completed',
      tools: [
        { name: 'Tool: VLM 数据提取', duration: '3.2s', status: 'completed', input: 'Model: GPT-4V\nInput: PDF page 1-15\nTask: 提取表格数据', output: '提取 24 个数据字段\n表格识别置信度: 0.92\n图表数据点: 36 个' },
        { name: 'Tool: OCR 验证', duration: '2.1s', status: 'completed', input: 'Engine: Tesseract 5.0\nPages: 16-42\nVerify: VLM 提取结果', output: '验证 18/24 字段\n修正 3 处识别错误\n置信度提升: 0.92 → 0.96' },
        { name: 'LLM 调用: 数据整合', duration: '3.2s', status: 'completed', input: 'Model: deepseek-chat\nTask: 整合 VLM + OCR 结果', output: '整合完成: 24 字段, 置信度 0.96' },
      ],
    }],
  },
  quality: {
    agents: [{
      name: '质量评估 Agent', duration: '3.2s', status: 'in_progress',
      tools: [
        { name: 'Tool: 完整性检查', duration: '1.1s', status: 'completed', input: 'Fields: 24\nSchema: cathode_material_v2', output: '完整字段: 21/24\n缺失: 循环首周容量, 库伦效率, 自放电率' },
        { name: 'Tool: 一致性验证', duration: '1.4s', status: 'in_progress', input: 'Cross-check: 3 篇文献\nFields: 21', output: '' },
        { name: 'LLM 调用: 质量报告生成', duration: '-', status: 'waiting', input: '', output: '' },
      ],
    }],
  },
  conflict: {
    agents: [{
      name: '冲突分析 Agent', duration: '-', status: 'waiting',
      tools: [
        { name: 'Tool: 跨文献冲突检测', duration: '-', status: 'waiting', input: '', output: '' },
        { name: 'LLM 调用: 冲突消解', duration: '-', status: 'waiting', input: '', output: '' },
      ],
    }],
  },
  normalization: {
    agents: [{
      name: '规范化 Agent', duration: '-', status: 'waiting',
      tools: [
        { name: 'Tool: 单位标准化', duration: '-', status: 'waiting', input: '', output: '' },
        { name: 'Tool: 格式规范化', duration: '-', status: 'waiting', input: '', output: '' },
        { name: 'LLM 调用: 语义对齐', duration: '-', status: 'waiting', input: '', output: '' },
      ],
    }],
  },
  export: {
    agents: [{
      name: '导出 Agent', duration: '-', status: 'waiting',
      tools: [
        { name: 'Tool: JSON 序列化', duration: '-', status: 'waiting', input: '', output: '' },
        { name: 'Tool: 格式转换', duration: '-', status: 'waiting', input: '', output: '' },
      ],
    }],
  },
}

const statusColors = {
  completed: 'var(--status-success)',
  in_progress: 'var(--status-progress)',
  waiting: 'var(--status-waiting)',
  error: 'var(--status-error)',
  running: 'var(--status-progress)',
}

/* ========== Main App ========== */
export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [detailOpen, setDetailOpen] = useState(true)
  const [selectedStage, setSelectedStage] = useState('intent')
  const [expandedStages, setExpandedStages] = useState({ intent: false, retrieval: false, extraction: false, quality: true, conflict: false, normalization: false, export: false })
  const [activeView, setActiveView] = useState('chat')

  const toggleStage = (id) => setExpandedStages((p) => ({ ...p, [id]: !p[id] }))
  const selectStage = (id) => { setSelectedStage(id); if (!detailOpen) setDetailOpen(true) }

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100%', overflow: 'hidden' }}>

      {/* ===== SIDEBAR ===== */}
      {sidebarOpen && (
        <aside style={{ width: 240, minWidth: 240, background: 'var(--sidebar-bg)', borderRight: '1px solid var(--sidebar-border)', display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '16px 16px 12px' }}>
            <Button variant="sidebar" className="w-full justify-start gap-2 text-sm font-normal">
              <Icon.Plus />
              <span>新建提取任务</span>
            </Button>
          </div>
          <ScrollArea className="flex-1 px-2 pb-2">
            <div style={{ padding: '4px 8px 8px', color: 'var(--sidebar-text-secondary)', fontSize: 11, fontWeight: 510, letterSpacing: '0.06em', textTransform: 'uppercase' }}>历史任务</div>
            {taskHistory.map((task) => {
              const isActive = task.id === currentTask.id
              return (
                <div key={task.id} style={{ padding: '8px 10px', borderRadius: 6, marginBottom: 2, cursor: 'pointer', background: isActive ? 'var(--sidebar-active)' : 'transparent' }}
                  onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--sidebar-hover)' }}
                  onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = isActive ? 'var(--sidebar-active)' : 'transparent' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ width: 6, height: 6, borderRadius: '50%', background: statusColors[task.status] || statusColors.completed, flexShrink: 0 }} />
                    <span style={{ color: isActive ? 'var(--sidebar-text)' : 'var(--content-fg-secondary)', fontSize: 13, fontWeight: isActive ? 510 : 400, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}>{task.title}</span>
                  </div>
                  <div style={{ color: 'var(--sidebar-text-secondary)', fontSize: 11, marginTop: 4, paddingLeft: 14 }}>{task.time}</div>
                </div>
              )
            })}
          </ScrollArea>
          <div style={{ padding: '12px 16px', borderTop: '1px solid var(--sidebar-border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--sidebar-text-secondary)', fontSize: 13, cursor: 'pointer' }}>
              <Icon.Settings /><span>设置</span>
            </div>
          </div>
        </aside>
      )}

      {/* ===== MAIN CONTENT ===== */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, background: 'var(--content-bg)' }}>
        {/* Toolbar */}
        <header style={{ display: 'flex', alignItems: 'center', padding: '10px 20px', background: 'var(--surface-bg)', borderBottom: '1px solid var(--surface-border)', gap: 12, flexShrink: 0 }}>
          {!sidebarOpen && (
            <Button variant="ghost" size="icon" onClick={() => setSidebarOpen(true)}>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M2 4h12M2 8h12M2 12h12" /></svg>
            </Button>
          )}
          <h1 style={{ fontSize: 15, fontWeight: 510, color: 'var(--content-fg)', flex: 1 }}>{currentTask.title}</h1>
          <div style={{ display: 'flex', background: 'var(--surface-secondary)', borderRadius: 6, padding: 2 }}>
            <Button variant={activeView === 'chat' ? 'secondary' : 'ghost'} size="sm" onClick={() => setActiveView('chat')} className="gap-1.5"><Icon.MessageSquare />对话</Button>
            <Button variant={activeView === 'workflow' ? 'secondary' : 'ghost'} size="sm" onClick={() => setActiveView('workflow')} className="gap-1.5"><Icon.Network />工作流</Button>
          </div>
          <Button variant="outline" size="icon" onClick={() => setDetailOpen(!detailOpen)}><Icon.PanelRight /></Button>
        </header>

        {/* Content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '24px 24px 16px' }}>
          {activeView === 'chat' ? (
            <div style={{ maxWidth: 760, margin: '0 auto' }}>
              {/* User message */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 20 }}>
                <div style={{ background: 'var(--accent)', color: '#fff', padding: '10px 16px', borderRadius: '12px 12px 2px 12px', maxWidth: 520, fontSize: 14, lineHeight: 1.6 }}>
                  请帮我检索并提取锂电池正极材料的电化学性能数据，包括比容量、循环寿命、倍率性能等关键参数
                </div>
              </div>
              {/* AI intro */}
              <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
                <div style={{ width: 28, height: 28, borderRadius: 6, background: 'var(--surface-secondary)', border: '1px solid var(--surface-border)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, color: 'var(--content-fg-secondary)' }}><Icon.Sparkle /></div>
                <div style={{ fontSize: 14, color: 'var(--content-fg-secondary)', lineHeight: 1.6, paddingTop: 3 }}>好的，我将自动检索相关文献并为您提取锂电池正极材料的电化学性能数据。任务将通过以下七个阶段完成：</div>
              </div>
              {/* Stage cards */}
              <div style={{ marginLeft: 38, display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
                {stages.map((stage) => {
                  const isExpanded = expandedStages[stage.id]
                  const detail = stageDetails[stage.id]
                  const isSelected = selectedStage === stage.id
                  return (
                    <div key={stage.id} style={{ background: 'var(--surface-bg)', border: `1px solid ${isSelected ? 'var(--accent)' : 'var(--surface-border)'}`, borderRadius: 8, overflow: 'hidden' }}>
                      <div style={{ display: 'flex', alignItems: 'center', padding: '10px 14px', cursor: 'pointer', borderLeft: `3px solid ${statusColors[stage.status]}` }} onClick={() => toggleStage(stage.id)}>
                        <div style={{ width: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', marginRight: 10, flexShrink: 0 }}>
                          {stage.status === 'completed' && <div style={{ width: 18, height: 18, borderRadius: '50%', background: 'var(--status-success-bg)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Icon.Check style={{ color: 'var(--status-success)' }} /></div>}
                          {stage.status === 'in_progress' && <div className="animate-pulse-dot" style={{ width: 18, height: 18, borderRadius: '50%', background: 'var(--status-progress-bg)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><div style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--status-progress)' }} /></div>}
                          {stage.status === 'waiting' && <div style={{ width: 18, height: 18, borderRadius: '50%', background: 'var(--status-waiting-bg)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><div style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--status-waiting)', opacity: 0.4 }} /></div>}
                        </div>
                        <span style={{ fontWeight: 510, fontSize: 14, color: 'var(--content-fg)' }}>阶段 {stages.indexOf(stage) + 1}：{stage.name}</span>
                        <span className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg-tertiary)', marginLeft: 12 }}>{stage.duration}</span>
                        <div style={{ flex: 1 }} />
                        <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); selectStage(stage.id) }} style={{ color: isSelected ? 'var(--accent-text)' : 'var(--content-fg-tertiary)', background: isSelected ? 'var(--accent-light)' : 'transparent', fontSize: 12, marginRight: 4 }}>详情</Button>
                        <div style={{ color: 'var(--content-fg-tertiary)', transform: isExpanded ? 'rotate(0deg)' : 'rotate(-90deg)', transition: 'transform 0.15s' }}><Icon.ChevronDown /></div>
                      </div>
                      {isExpanded && (
                        <div style={{ padding: '4px 14px 14px 42px', borderTop: '1px solid var(--surface-border-subtle)' }}>
                          <p style={{ fontSize: 13, color: 'var(--content-fg-secondary)', marginBottom: 12, lineHeight: 1.5 }}>{stage.summary}</p>
                          {detail && detail.agents.map((agent) => (
                            <div key={agent.name} style={{ marginBottom: 4 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0' }}>
                                <div style={{ width: 16, display: 'flex', justifyContent: 'center', flexShrink: 0 }}>
                                  {agent.status === 'completed' && <Icon.Check style={{ color: 'var(--status-success)' }} />}
                                  {agent.status === 'in_progress' && <div className="animate-pulse-dot" style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--status-progress)' }} />}
                                  {agent.status === 'waiting' && <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--status-waiting)', opacity: 0.5 }} />}
                                </div>
                                <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>{agent.name}</span>
                                <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginLeft: 'auto' }}>{agent.duration}</span>
                              </div>
                              <div style={{ paddingLeft: 24 }}>
                                {agent.tools.map((tool) => (
                                  <div key={tool.name} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '5px 0' }}>
                                    <div style={{ width: 16, display: 'flex', justifyContent: 'center', paddingTop: 2, flexShrink: 0 }}>
                                      {tool.status === 'completed' && <div style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--status-success)' }} />}
                                      {tool.status === 'in_progress' && <div className="animate-pulse-dot" style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--status-progress)' }} />}
                                      {tool.status === 'waiting' && <div style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--status-waiting)', opacity: 0.5 }} />}
                                    </div>
                                    <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
                                      <Icon.Wrench style={{ color: 'var(--content-fg-tertiary)', flexShrink: 0 }} />
                                      <span style={{ fontSize: 13, color: 'var(--content-fg-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{tool.name}</span>
                                      <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginLeft: 'auto', flexShrink: 0 }}>{tool.duration}</span>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
              {/* Streaming text */}
              <div style={{ marginLeft: 38, marginBottom: 20 }}>
                <div style={{ background: 'var(--surface-bg)', border: '1px solid var(--surface-border)', borderRadius: 8, padding: 16 }}>
                  <div style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)', marginBottom: 8 }}>质量评估进行中</div>
                  <div style={{ fontSize: 14, color: 'var(--content-fg-secondary)', lineHeight: 1.7 }}>
                    数据提取已完成，正在进行质量评估。完整性检查发现 21/24 个字段已填充，缺失字段：循环首周容量、库伦效率、自放电率。正在执行跨文献一致性验证<span className="streaming-cursor" />
                  </div>
                </div>
              </div>
            </div>
          ) : (
            /* Workflow View */
            <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100%' }}>
              <div style={{ padding: '20px 0 0' }}>
                <div style={{ overflowX: 'auto', paddingBottom: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0, minWidth: 'max-content', padding: '0 24px' }}>
                    {stages.map((stage, i) => (
                      <div key={stage.id} style={{ display: 'flex', alignItems: 'flex-start' }}>
                        <div onClick={() => selectStage(stage.id)} style={{ width: 128, padding: '12px 12px 10px', borderRadius: 10, border: `1.5px solid ${stage.status === 'completed' ? 'var(--status-success)' : stage.status === 'in_progress' ? 'var(--status-progress)' : 'var(--surface-border)'}`, background: 'var(--surface-bg)', cursor: 'pointer', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                            <div style={{ width: 7, height: 7, borderRadius: '50%', background: statusColors[stage.status], flexShrink: 0, ...(stage.status === 'in_progress' ? { animation: 'pulse-dot 2s ease-in-out infinite' } : {}) }} />
                            <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)', whiteSpace: 'nowrap' }}>{stage.name}</span>
                          </div>
                          <div className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginBottom: 4 }}>耗时: {stage.duration}</div>
                          <div style={{ fontSize: 11, color: 'var(--content-fg-secondary)', lineHeight: 1.4 }}>{stage.summary}</div>
                        </div>
                        {i < stages.length - 1 && (
                          <div style={{ display: 'flex', alignItems: 'center', paddingTop: 14, width: 20, justifyContent: 'center', flexShrink: 0 }}>
                            <svg width="18" height="10" viewBox="0 0 18 10" fill="none" style={{ overflow: 'visible' }}>
                              <path d="M0 5h12" stroke={stages[i].status === 'completed' ? 'var(--status-success)' : 'var(--surface-border)'} strokeWidth="1.5" strokeDasharray={stages[i].status === 'completed' ? 'none' : '3 2'} />
                              <path d="M10 1l5 4-5 4" stroke={stages[i].status === 'completed' ? 'var(--status-success)' : 'var(--surface-border)'} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
                            </svg>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
                <div style={{ maxWidth: 600, margin: '24px auto 0', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, padding: '0 24px' }}>
                  {[['总耗时', '14.9s', 'var(--content-fg)'], ['已完成阶段', '3 / 7', 'var(--status-success)'], ['已提取字段', '24', 'var(--content-fg)']].map(([label, value, color]) => (
                    <div key={label} style={{ background: 'var(--surface-bg)', border: '1px solid var(--surface-border)', borderRadius: 8, padding: '14px 16px' }}>
                      <div style={{ fontSize: 12, color: 'var(--content-fg-tertiary)', marginBottom: 4, fontWeight: 510, letterSpacing: '0.02em' }}>{label}</div>
                      <div className="font-mono" style={{ fontSize: 22, fontWeight: 510, color, letterSpacing: '-0.02em' }}>{value}</div>
                    </div>
                  ))}
                </div>
                {/* Execution Flow Graph */}
                {(() => {
                  const detail = stageDetails[selectedStage]
                  if (!detail) return null
                  const agent = detail.agents[0]
                  if (!agent) return null
                  const tools = agent.tools
                  const nodeW = 140, nodeH = 52, gapX = 48, startX = 24, startY = 16
                  const totalW = startX * 2 + tools.length * nodeW + (tools.length - 1) * gapX
                  const totalH = startY * 2 + nodeH
                  return (
                    <div style={{ margin: '24px 24px 0', background: 'var(--surface-bg)', border: '1px solid var(--surface-border)', borderRadius: 10, overflow: 'hidden' }}>
                      <div style={{ padding: '12px 16px 8px', borderBottom: '1px solid var(--surface-border-subtle)', display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{ width: 7, height: 7, borderRadius: '50%', background: statusColors[agent.status] }} />
                        <span style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>{agent.name}</span>
                        <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginLeft: 'auto' }}>{agent.duration}</span>
                      </div>
                      <div style={{ overflowX: 'auto', padding: '16px 8px' }}>
                        <svg width={totalW} height={totalH} style={{ display: 'block' }}>
                          {/* Edges */}
                          {tools.map((_, i) => i < tools.length - 1 && (
                            <g key={`edge-${i}`}>
                              <line x1={startX + nodeW + i * (nodeW + gapX)} y1={startY + nodeH / 2} x2={startX + nodeW + gapX + i * (nodeW + gapX) - 4} y2={startY + nodeH / 2} stroke={tools[i].status === 'completed' ? 'var(--status-success)' : 'var(--surface-border)'} strokeWidth="1.5" strokeDasharray={tools[i].status === 'completed' ? 'none' : '4 3'} />
                              <polygon points={`${startX + nodeW + gapX + i * (nodeW + gapX) - 2},${startY + nodeH / 2 - 4} ${startX + nodeW + gapX + i * (nodeW + gapX) + 4},${startY + nodeH / 2} ${startX + nodeW + gapX + i * (nodeW + gapX) - 2},${startY + nodeH / 2 + 4}`} fill={tools[i].status === 'completed' ? 'var(--status-success)' : 'var(--surface-border)'} />
                            </g>
                          ))}
                          {/* Nodes */}
                          {tools.map((tool, i) => {
                            const x = startX + i * (nodeW + gapX)
                            const y = startY
                            const isLLM = tool.name.startsWith('LLM')
                            const isTool = tool.name.startsWith('Tool')
                            const borderColor = tool.status === 'completed' ? 'var(--status-success)' : tool.status === 'in_progress' ? 'var(--status-progress)' : 'var(--surface-border)'
                            const bgColor = tool.status === 'completed' ? (isLLM ? '#f0fdf4' : isTool ? '#f0f9ff' : '#fafafa') : 'var(--surface-bg)'
                            const label = tool.name.replace('LLM 调用: ', '').replace('Tool: ', '')
                            return (
                              <g key={`node-${i}`} style={{ cursor: 'pointer' }} onClick={() => { setSelectedStage(selectedStage); if (!detailOpen) setDetailOpen(true) }}>
                                <rect x={x} y={y} width={nodeW} height={nodeH} rx="8" fill={bgColor} stroke={borderColor} strokeWidth="1.5" />
                                <text x={x + 10} y={y + 20} fontSize="11" fontWeight="510" fill="var(--content-fg)">{label.length > 14 ? label.slice(0, 14) + '…' : label}</text>
                                <text x={x + 10} y={y + 38} fontSize="10" fill="var(--content-fg-tertiary)" className="font-mono">{tool.duration}</text>
                                {tool.status === 'in_progress' && <circle cx={x + nodeW - 10} cy={y + 12} r="3" fill="var(--status-progress)" style={{ animation: 'pulse-dot 2s ease-in-out infinite' }} />}
                                {tool.status === 'completed' && <circle cx={x + nodeW - 10} cy={y + 12} r="3" fill="var(--status-success)" />}
                                {tool.status === 'waiting' && <circle cx={x + nodeW - 10} cy={y + 12} r="3" fill="var(--status-waiting)" opacity="0.4" />}
                              </g>
                            )
                          })}
                        </svg>
                      </div>
                    </div>
                  )
                })()}
              </div>
              <div style={{ flex: 1 }} />
            </div>
          )}
        </div>

        {/* Input bar */}
        <div style={{ padding: '12px 24px 20px', flexShrink: 0 }}>
          <div style={{ maxWidth: 760, margin: '0 auto' }}>
            <div style={{ background: 'var(--surface-bg)', border: '1px solid var(--surface-border)', borderRadius: 12, boxShadow: '0 2px 8px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
              <textarea placeholder="描述您的研究数据提取需求，智能体将自动检索文献并提取数据..." rows={2} style={{ width: '100%', padding: '14px 16px 8px', fontSize: 14, lineHeight: 1.5, color: 'var(--content-fg)', minHeight: 48 }} />
              <div style={{ display: 'flex', alignItems: 'center', padding: '6px 10px', gap: 4 }}>
                <Button variant="ghost" size="sm" className="gap-1.5 text-xs"><Icon.Network />选择数据源</Button>
                <div style={{ flex: 1 }} />
                <Button variant="accent" size="icon"><Icon.Send /></Button>
              </div>
            </div>
            <div style={{ textAlign: 'center', marginTop: 8, fontSize: 11, color: 'var(--content-fg-tertiary)' }}>AI Scientist 可能产生误差，请核实关键信息</div>
          </div>
        </div>
      </main>

      {/* ===== DETAIL PANEL ===== */}
      {detailOpen && (
        <aside style={{ width: 380, minWidth: 380, background: 'var(--surface-bg)', borderLeft: '1px solid var(--surface-border)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', padding: '12px 16px', borderBottom: '1px solid var(--surface-border)', flexShrink: 0 }}>
            <h2 style={{ fontSize: 14, fontWeight: 510, flex: 1 }}>{stages.find((s) => s.id === selectedStage)?.name || '详情'} — 执行详情</h2>
            <Button variant="ghost" size="icon" onClick={() => setDetailOpen(false)}><Icon.Close /></Button>
          </div>
          <ScrollArea className="flex-1 p-4">
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 11, fontWeight: 510, color: 'var(--content-fg-tertiary)', marginBottom: 10, letterSpacing: '0.06em', textTransform: 'uppercase' }}>执行概要</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                {[
                  ['状态', stages.find((s) => s.id === selectedStage)?.status === 'completed' ? '已完成' : stages.find((s) => s.id === selectedStage)?.status === 'in_progress' ? '执行中' : '等待中', stages.find((s) => s.id === selectedStage)?.status === 'completed' ? 'var(--status-success)' : stages.find((s) => s.id === selectedStage)?.status === 'in_progress' ? 'var(--status-progress)' : 'var(--status-waiting)'],
                  ['耗时', stages.find((s) => s.id === selectedStage)?.duration || '-', 'var(--content-fg)'],
                  ['Agent 数', '1', 'var(--content-fg)'],
                  ['工具调用', String(stageDetails[selectedStage]?.agents[0]?.tools.length || 0), 'var(--content-fg)'],
                ].map(([label, value, vc]) => (
                  <div key={label} style={{ padding: '10px 12px', background: 'var(--surface-secondary)', borderRadius: 6 }}>
                    <div style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginBottom: 4, fontWeight: 510, letterSpacing: '0.02em' }}>{label}</div>
                    <div className="font-mono" style={{ fontSize: 14, fontWeight: 510, color: vc }}>{value}</div>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, fontWeight: 510, color: 'var(--content-fg-tertiary)', marginBottom: 10, letterSpacing: '0.06em', textTransform: 'uppercase' }}>工具调用详情</div>
              {stageDetails[selectedStage]?.agents[0]?.tools.map((tool) => (
                <div key={tool.name} style={{ marginBottom: 12, border: '1px solid var(--surface-border-subtle)', borderRadius: 8, overflow: 'hidden' }}>
                  <div style={{ padding: '8px 12px', background: 'var(--surface-secondary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ width: 6, height: 6, borderRadius: '50%', background: statusColors[tool.status] }} />
                    <span style={{ fontSize: 13, fontWeight: 510, flex: 1 }}>{tool.name}</span>
                    <span className="font-mono" style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>{tool.duration}</span>
                  </div>
                  {tool.input ? (
                    <div style={{ padding: '10px 12px' }}>
                      <div style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginBottom: 4, fontWeight: 510, letterSpacing: '0.04em' }}>输入</div>
                      <pre className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg-secondary)', lineHeight: 1.6, whiteSpace: 'pre-wrap', margin: 0 }}>{tool.input}</pre>
                      {tool.output !== undefined && tool.output !== '' && (
                        <>
                          <div style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginBottom: 4, marginTop: 10, fontWeight: 510, letterSpacing: '0.04em' }}>输出</div>
                          <pre className="font-mono" style={{ fontSize: 12, color: 'var(--content-fg-secondary)', lineHeight: 1.6, whiteSpace: 'pre-wrap', margin: 0 }}>{tool.output}</pre>
                        </>
                      )}
                      {tool.output === '' && (
                        <>
                          <div style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginBottom: 4, marginTop: 10, fontWeight: 510, letterSpacing: '0.04em' }}>输出</div>
                          <span className="streaming-cursor" style={{ fontSize: 12 }} />
                        </>
                      )}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
            {stages.find((s) => s.id === selectedStage)?.status === 'completed' && (
              <div style={{ marginTop: 16 }}>
                <Button variant="outline" className="w-full gap-2"><Icon.Download />导出阶段数据</Button>
              </div>
            )}
          </ScrollArea>
        </aside>
      )}
    </div>
  )
}
