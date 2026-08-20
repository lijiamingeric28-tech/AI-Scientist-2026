import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useToast } from '@/components/ui/toast'
import * as api from '@/services/api'

/* 设置对话框（契约第 10 轮：API key 对照 .env.example 全键补齐）
 * 可编辑：DashScope(key+base_url) / ADS / Unpaywall；质量管线复用 DashScope 凭证（全 Qwen）
 * 契约 D10-1/2：PUT /api/config 写回 .env（持久化）；GET 只返回是否配置（无明文）
 */

const GROUPS = [
  {
    id: 'dashscope',
    name: 'Qwen 基座模型（DashScope 百炼 · 全系统统一）',
    fields: [
      { key: 'dashscope_api_key', label: 'DashScope API Key', placeholder: 'sk-…', required: true, note: '意图澄清 + 性质标准化(P1) + VLM 提取 + 质量管线（评估/清洗/冲突/洞察）共用，模型 qwen3.7-flash' },
      { key: 'dashscope_base_url', label: 'DashScope Base URL', placeholder: 'https://…（留空用官方默认）', required: false, note: '兼容模式端点；留空 = DashScope 官方' },
    ],
  },
  {
    id: 'papers',
    name: '论文检索（ADS / Unpaywall）',
    fields: [
      { key: 'ads_api_token', label: 'ADS API Token', placeholder: '…', required: false, note: 'NASA ADS 论文检索（ui.adsabs.harvard.edu 获取）' },
      { key: 'unpaywall_email', label: 'Unpaywall Email', placeholder: 'you@example.com', required: false, note: 'PDF 开放获取查询' },
    ],
  },
]

/* 当前生效模型（只读，来自后端 config.py 默认值） */
const CURRENT_MODELS = [
  { label: '意图澄清', value: 'qwen3.7-flash' },
  { label: '性质标准化 (P1)', value: 'qwen3.8-max' },
  { label: 'VLM 提取', value: 'qwen3.7-plus' },
  { label: 'BBox 标注', value: 'qwen3.7-flash' },
  { label: '质量管线', value: 'qwen3.7-flash' },
  { label: '研究领域', value: 'astrophysics' },
]

/* 本地 key ↔ 后端 env 键映射（契约 D10-1：PUT /api/config 写回 .env） */
const KEY_MAP = {
  dashscope_api_key: 'dashscope_api_key',
  dashscope_base_url: 'dashscope_base_url',
  ads_api_token: 'ads_api_token',
  unpaywall_email: 'unpaywall_email',
}

export default function SettingsDialog({ open, onClose }) {
  // values: 已配置的键 → ''（后端不回传明文，只表示"已配置"，D10-2）
  const [configuredKeys, setConfiguredKeys] = useState([])
  const [values, setValues] = useState({})
  const { toast } = useToast()

  // 打开时拉取配置状态（GET /api/config：只返回是否配置，无明文）
  useEffect(() => {
    if (!open) return
    let alive = true
    api.getConfig()
      .then((cfg) => {
        if (!alive) return
        const keys = Object.entries(cfg.configured || {})
          .filter(([, v]) => v)
          .map(([k]) => k)
        setConfiguredKeys(keys)
      })
      .catch(() => toast('配置状态加载失败', 'error'))
    return () => { alive = false }
  }, [open, toast])

  if (!open) return null

  const allFields = GROUPS.flatMap((g) => g.fields)
  // M-01: 后端 GET /api/config 返回大写键（DASHSCOPE_API_KEY…），KEY_MAP 为
  // 小写 → 此前 includes 恒 false，"已配置"徽标与计数永不命中
  const isConfigured = (f) => configuredKeys.includes(KEY_MAP[f.key].toUpperCase()) || Boolean((values[f.key] || '').trim())
  const configured = allFields.filter(isConfigured).length
  const requiredDone = allFields.filter((f) => f.required && isConfigured(f)).length
  const requiredTotal = allFields.filter((f) => f.required).length

  const save = async () => {
    // 只提交有值的字段（空 = 不改动）
    const body = {}
    for (const f of allFields) {
      const v = (values[f.key] || '').trim()
      if (v) body[f.key] = v
    }
    try {
      await api.putConfig(body)
      toast('配置已保存（写回 .env）', 'success')
      onClose()
    } catch (err) {
      toast(`保存失败：${err.message}`, 'error')
    }
  }

  return (
    <div
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 150, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="glass"
        style={{
          width: 520,
          maxWidth: '94vw',
          maxHeight: '88vh',
          display: 'flex',
          flexDirection: 'column',
          background: 'color-mix(in srgb, var(--seed-surface) 82%, transparent)',
          borderRadius: 12,
          boxShadow: '0 12px 40px rgba(0,0,0,0.15)',
          overflow: 'hidden',
        }}
      >
        {/* 头部 */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '14px 18px', borderBottom: '1px solid var(--surface-border)', flexShrink: 0 }}>
          <Icon.Settings style={{ color: 'var(--content-fg-tertiary)' }} />
          <h2 style={{ fontSize: 15, fontWeight: 510, marginLeft: 8, flex: 1 }}>设置</h2>
          <span style={{ fontSize: 12, color: 'var(--content-fg-tertiary)' }}>
            {configured}/{allFields.length} 项已填 · 必填 {requiredDone}/{requiredTotal}
          </span>
          <Button variant="ghost" size="icon" onClick={onClose} style={{ marginLeft: 8 }}>
            <Icon.Close />
          </Button>
        </div>

        {/* 表单（可滚动） */}
        <div style={{ padding: '14px 18px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 14 }}>
          {GROUPS.map((g) => (
            <div key={g.id}>
              <div style={{ fontSize: 12, fontWeight: 510, color: 'var(--accent-text)', marginBottom: 8, letterSpacing: '0.02em' }}>{g.name}</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {g.fields.map((f) => (
                  <div key={f.key}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <label style={{ fontSize: 13, fontWeight: 510, color: 'var(--content-fg)' }}>{f.label}</label>
                      {isConfigured(f) && (
                        <span style={{ fontSize: 11, padding: '1px 8px', borderRadius: 4, background: 'var(--status-success-bg)', color: 'var(--status-success)' }}>已配置</span>
                      )}
                      {f.required && <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)' }}>必填</span>}
                    </div>
                    <input
                      type="password"
                      value={values[f.key] || ''}
                      onChange={(e) => setValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
                      placeholder={f.placeholder}
                      style={{
                        width: '100%',
                        padding: '8px 10px',
                        fontSize: 13,
                        border: '1px solid var(--surface-border)',
                        borderRadius: 6,
                        outline: 'none',
                        background: 'var(--surface-secondary)',
                        color: 'var(--content-fg)',
                      }}
                    />
                    <div style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', marginTop: 3 }}>{f.note}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {/* 当前模型（只读） */}
          <div>
            <div style={{ fontSize: 12, fontWeight: 510, color: 'var(--accent-text)', marginBottom: 8 }}>当前生效配置（只读，改 .env 后重启生效）</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
              {CURRENT_MODELS.map((m) => (
                <div key={m.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 10px', background: 'var(--surface-secondary)', borderRadius: 6, fontSize: 12 }}>
                  <span style={{ color: 'var(--content-fg-secondary)' }}>{m.label}</span>
                  <span className="font-mono" style={{ color: 'var(--content-fg)' }}>{m.value}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 版本 + 输出目录（契约 D10-4） */}
          <div>
            <div style={{ fontSize: 12, fontWeight: 510, color: 'var(--accent-text)', marginBottom: 8 }}>系统信息</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', gap: 8, fontSize: 12 }}>
                <span style={{ width: 64, flexShrink: 0, color: 'var(--content-fg-secondary)' }}>Schema</span>
                <span className="font-mono" style={{ color: 'var(--content-fg)' }}>2.0.0</span>
              </div>
              <div style={{ display: 'flex', gap: 8, fontSize: 12 }}>
                <span style={{ width: 64, flexShrink: 0, color: 'var(--content-fg-secondary)' }}>输出目录</span>
                <span className="font-mono" style={{ color: 'var(--content-fg)', wordBreak: 'break-all' }}>
                  {'E:\\work\\frontend\\astroquery_final\\output\\<query_id>\\'}
                </span>
              </div>
            </div>
          </div>

          <div style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', lineHeight: 1.6, padding: '8px 10px', background: 'var(--surface-secondary)', borderRadius: 6 }}>
            配置保存在本地浏览器（mock）。对接后端后：key 经 PUT /api/config 提交，服务端运行时注入（不回传明文）；DEFAULT_RESEARCH_DOMAIN 不在本页配置。
          </div>
        </div>

        {/* 底部 */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '12px 18px', borderTop: '1px solid var(--surface-border)', flexShrink: 0 }}>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button variant="accent" onClick={save}>保存</Button>
        </div>
      </div>
    </div>
  )
}
