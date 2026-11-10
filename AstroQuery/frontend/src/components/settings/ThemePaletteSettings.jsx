import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import {
  PALETTE_PRESETS,
  DEFAULT_PALETTE,
  isValidHexColor,
  normalizeHex,
  loadSavedPalette,
  savePalette,
  resetPaletteToDefault,
  applyPaletteToDOM,
} from '@/lib/customPalette'

const SEED_ROLES = [
  {
    key: 'accent',
    name: 'Accent',
    label: '品牌主色 (Accent)',
    desc: '主按钮、高光指示滑块、数据实体名、聚焦环',
    fallback: DEFAULT_PALETTE.accent,
  },
  {
    key: 'bg',
    name: 'Background',
    label: '基底画布 (Canvas Base)',
    desc: '全屏主窗口底色、白底卡片容器底色',
    fallback: DEFAULT_PALETTE.bg,
  },
  {
    key: 'surface',
    name: 'Card Surface',
    label: '卡片表面 (Card Surface)',
    desc: '卡片底色、表格交替行、侧栏底色、表头底色',
    fallback: DEFAULT_PALETTE.surface,
  },
  {
    key: 'ink',
    name: 'Foreground',
    label: '结构墨水 (Foreground / Ink)',
    desc: '驱动 100% 文本色阶（标题/正文）、发丝分割线',
    fallback: DEFAULT_PALETTE.ink,
  },
  {
    key: 'aux',
    name: 'Auxiliary',
    label: '辅助指示 (Auxiliary Accent)',
    desc: '星表与外部数据库徽标、辅助胶囊、引用标记',
    fallback: DEFAULT_PALETTE.aux,
  },
]

export default function ThemePaletteSettings({ theme = 'light', onToggleTheme, onToast }) {
  const [palette, setPalette] = useState(loadSavedPalette)
  const [activePresetId, setActivePresetId] = useState(() => {
    const cur = loadSavedPalette()
    const match = PALETTE_PRESETS.find(p =>
      Object.keys(p.colors).every(k => normalizeHex(p.colors[k]) === normalizeHex(cur[k]))
    )
    return match ? match.id : 'custom'
  })

  // 视觉对比度偏好
  const [contrast, setContrast] = useState(() => {
    try {
      return localStorage.getItem('astroquery-contrast-pref') || 'default'
    } catch {
      return 'default'
    }
  })

  // 字体偏好
  const [fontPref, setFontPref] = useState(() => {
    try {
      return localStorage.getItem('astroquery-font-pref') || 'default'
    } catch {
      return 'default'
    }
  })

  const handleContrastChange = (val) => {
    setContrast(val)
    try {
      localStorage.setItem('astroquery-contrast-pref', val)
      if (val === 'strong') {
        document.documentElement.setAttribute('data-contrast', 'strong')
      } else {
        document.documentElement.removeAttribute('data-contrast')
      }
    } catch {}
  }

  const handleFontChange = (val) => {
    setFontPref(val)
    try {
      localStorage.setItem('astroquery-font-pref', val)
      if (val === 'google-sans') {
        document.documentElement.style.setProperty('--font-custom-override', "'Google Sans', system-ui, -apple-system, sans-serif")
      } else if (val === 'serif') {
        document.documentElement.style.setProperty('--font-custom-override', "'Times New Roman', 'STIX Two Text', 'Songti SC', serif")
      } else {
        document.documentElement.style.removeProperty('--font-custom-override')
      }
    } catch {}
  }

  // 监听即时变化并动态注入 DOM
  const handleColorChange = (key, rawValue) => {
    const next = { ...palette, [key]: rawValue }
    setPalette(next)
    setActivePresetId('custom')
    if (isValidHexColor(rawValue)) {
      applyPaletteToDOM(next)
    }
  }

  useEffect(() => {
    applyPaletteToDOM(palette)
  }, [theme])

  const handlePresetSelect = (preset) => {
    setPalette(preset.colors)
    setActivePresetId(preset.id)
    applyPaletteToDOM(preset.colors)
  }

  const handleSave = () => {
    const invalid = Object.entries(palette).find(([k, val]) => !isValidHexColor(val))
    if (invalid) {
      onToast?.(`颜色格式错误：${invalid[0]} 必须为合法的十六进制代码（如 #24583b）`, 'error')
      return
    }
    savePalette(palette)
    onToast?.('界面配色已保存并全局生效', 'success')
  }

  const handleResetToDefault = () => {
    const def = resetPaletteToDefault()
    setPalette(def)
    setActivePresetId('classic-emerald')
    onToast?.('已恢复官方默认学术翡翠绿配色', 'success')
  }

  const currentPreset = PALETTE_PRESETS.find(p => p.id === activePresetId)

  return (
    <div className="theme-settings-container">
      {/* 头部说明 */}
      <div className="theme-settings-intro">
        <h3 className="theme-settings-title">外观与配色 (Appearance & Theme)</h3>
        <p className="theme-settings-desc">
          配置系统界面主题、对比度与 5 色调色盘。修改后全系统所有页面与组件均实时联动生效。
        </p>
      </div>

      {/* 第一分区：外观模式 (Appearance) */}
      <section className="theme-config-section">
        <div className="theme-config-section-header">
          <span className="theme-config-section-title">外观模式 (Appearance)</span>
        </div>

        <div className="theme-config-rows-group">
          {/* 色彩模式 */}
          <div className="theme-config-row">
            <div className="theme-config-row-label">
              <strong>色彩模式 (Theme)</strong>
              <span>选择系统明暗视觉风格</span>
            </div>
            <div className="theme-config-row-control">
              <div className="settings-segmented-group" role="radiogroup" aria-label="主题色彩">
                <button
                  type="button"
                  className={`settings-segmented-btn ${theme === 'light' ? 'is-active' : ''}`}
                  onClick={() => { if (theme !== 'light') onToggleTheme?.() }}
                  aria-checked={theme === 'light'}
                >
                  <Icon.Sun style={{ width: 14, height: 14 }} />
                  <span>浅色</span>
                </button>
                <button
                  type="button"
                  className={`settings-segmented-btn ${theme === 'dark' ? 'is-active' : ''}`}
                  onClick={() => { if (theme !== 'dark') onToggleTheme?.() }}
                  aria-checked={theme === 'dark'}
                >
                  <Icon.Moon style={{ width: 14, height: 14 }} />
                  <span>深色</span>
                </button>
              </div>
            </div>
          </div>

          {/* 视觉对比度 */}
          <div className="theme-config-row">
            <div className="theme-config-row-label">
              <strong>视觉对比度 (Contrast)</strong>
              <span>强化边框线条与正文文本层次</span>
            </div>
            <div className="theme-config-row-control">
              <div className="settings-segmented-group" role="radiogroup" aria-label="界面对比度">
                <button
                  type="button"
                  className={`settings-segmented-btn ${contrast === 'default' ? 'is-active' : ''}`}
                  onClick={() => handleContrastChange('default')}
                  aria-checked={contrast === 'default'}
                >
                  <span>标准</span>
                </button>
                <button
                  type="button"
                  className={`settings-segmented-btn ${contrast === 'strong' ? 'is-active' : ''}`}
                  onClick={() => handleContrastChange('strong')}
                  aria-checked={contrast === 'strong'}
                >
                  <span>强化</span>
                </button>
              </div>
            </div>
          </div>

          {/* 正文字体 */}
          <div className="theme-config-row">
            <div className="theme-config-row-label">
              <strong>正文字体 (Font)</strong>
              <span>天体物理量与英文文献显示字体</span>
            </div>
            <div className="theme-config-row-control">
              <div className="theme-select-container">
                <select
                  className="settings-select-control"
                  value={fontPref}
                  onChange={(e) => handleFontChange(e.target.value)}
                  aria-label="正文字体"
                >
                  <option value="default">系统默认 (System Sans)</option>
                  <option value="google-sans">Google Sans</option>
                  <option value="serif">学术衬线 (Academic Serif)</option>
                </select>
                <Icon.ChevronDown className="theme-select-chevron" />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 第二分区：界面配色方案 (Color Palette) */}
      <section className="theme-config-section">
        <div className="theme-config-section-header">
          <span className="theme-config-section-title">界面配色方案 (Color Palette)</span>
          <span className="theme-config-section-badge">WCAG AA 认证</span>
        </div>

        <div className="theme-config-rows-group">
          {/* 配色预设 */}
          <div className="theme-config-row">
            <div className="theme-config-row-label">
              <strong>配色预设 (Preset)</strong>
              <span>
                {currentPreset ? currentPreset.description : '自定义 5 色调色盘组合'}
              </span>
            </div>
            <div className="theme-config-row-control theme-preset-control-wrapper">
              <button
                type="button"
                className="theme-reset-icon-btn"
                title="重置为官方默认翡翠绿预设"
                disabled={activePresetId === 'classic-emerald'}
                onClick={handleResetToDefault}
              >
                <Icon.RotateCcw style={{ width: 13, height: 13 }} />
              </button>
              <div className="theme-select-container">
                <select
                  className="settings-select-control theme-preset-select"
                  value={activePresetId}
                  onChange={(e) => {
                    const found = PALETTE_PRESETS.find(p => p.id === e.target.value)
                    if (found) handlePresetSelect(found)
                  }}
                  aria-label="配色预设"
                >
                  {PALETTE_PRESETS.map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                  {activePresetId === 'custom' && (
                    <option value="custom">自定义配色 (Custom)</option>
                  )}
                </select>
                <Icon.ChevronDown className="theme-select-chevron" />
              </div>
            </div>
          </div>

          {/* 5 个核心 Hex 代码输入行 */}
          {SEED_ROLES.map(({ key, label, desc }) => {
            const hexVal = palette[key] || ''
            const safeColor = isValidHexColor(hexVal) ? normalizeHex(hexVal) : '#000000'
            return (
              <div key={key} className="theme-config-row">
                <div className="theme-config-row-label">
                  <strong>{label}</strong>
                  <span>{desc}</span>
                </div>
                <div className="theme-config-row-control">
                  <div className="theme-color-pill">
                    <label
                      className="theme-color-swatch"
                      style={{ backgroundColor: safeColor }}
                      title="点击取色或直接输入 Hex 代码"
                    >
                      <input
                        type="color"
                        value={safeColor}
                        onChange={(e) => handleColorChange(key, e.target.value)}
                        className="theme-native-color-input"
                        aria-label={`选择${label}`}
                      />
                    </label>
                    <input
                      type="text"
                      spellCheck={false}
                      value={hexVal}
                      placeholder="#000000"
                      maxLength={7}
                      onChange={(e) => handleColorChange(key, e.target.value)}
                      className="theme-color-hex-input font-mono"
                      aria-label={`${label} Hex 码`}
                    />
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* 第三分区：实时效果预览小样 */}
      <section className="theme-config-section">
        <div className="theme-config-section-header">
          <span className="theme-config-section-title">实时效果预览 (Live Preview)</span>
        </div>
        <div className="theme-preview-widget-card">
          <div className="theme-preview-header-row">
            <span className="theme-preview-entity-title">SN 2014J 物理量测量小样</span>
            <span className="theme-preview-badge-paper">论文提取</span>
            <span className="theme-preview-badge-aux">星表目录</span>
          </div>
          <div className="theme-preview-table-row">
            <div className="theme-preview-cell entity">SN 2014J</div>
            <div className="theme-preview-cell property">
              原报极大视星等
              <span className="theme-preview-cond-pill">B band</span>
            </div>
            <div className="theme-preview-cell value font-mono">11.91</div>
            <div className="theme-preview-cell unit">mag</div>
            <div className="theme-preview-cell source">CoSka 2018</div>
          </div>
        </div>
      </section>

      {/* 底部操作栏 */}
      <div className="theme-palette-action-bar">
        <Button variant="outline" size="sm" onClick={handleResetToDefault}>
          恢复官方默认配色
        </Button>
        <Button variant="accent" size="sm" onClick={handleSave}>
          保存配色配置
        </Button>
      </div>
    </div>
  )
}
