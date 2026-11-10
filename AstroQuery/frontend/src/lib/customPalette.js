export const PALETTE_PRESETS = [
  {
    id: 'classic-emerald',
    name: '经典学术翡翠绿',
    description: '官方推荐默认风格，端庄稳重与学术严谨',
    colors: {
      accent: '#24583b',
      bg: '#ffffff',
      surface: '#f4f8f5',
      ink: '#1e2a22',
      aux: '#1e40af',
    },
  },
  {
    id: 'deep-space-cobalt',
    name: '深空探索钴蓝',
    description: '天文望远镜与深空巡天风格，科技通透',
    colors: {
      accent: '#1d4ed8',
      bg: '#ffffff',
      surface: '#f0f5ff',
      ink: '#111827',
      aux: '#059669',
    },
  },
  {
    id: 'minimalist-graphite',
    name: '现代极简石墨灰',
    description: '工业出版物质感，高清晰黑白灰低饱和度',
    colors: {
      accent: '#374151',
      bg: '#ffffff',
      surface: '#f9fafb',
      ink: '#111827',
      aux: '#4b5563',
    },
  },
  {
    id: 'nightfall-violet',
    name: '暗夜紫罗兰',
    description: '高端科研分析风格，神秘深邃',
    colors: {
      accent: '#6b21a8',
      bg: '#ffffff',
      surface: '#faf5ff',
      ink: '#1f1b2e',
      aux: '#0284c7',
    },
  },
  {
    id: 'academic-warm-amber',
    name: '暖调学术琥珀',
    description: '羊皮纸与古籍感，柔和温润护眼',
    colors: {
      accent: '#92400e',
      bg: '#fefdfb',
      surface: '#fbf5ed',
      ink: '#291e14',
      aux: '#15803d',
    },
  },
]

export const DEFAULT_PALETTE = PALETTE_PRESETS[0].colors
export const STORAGE_KEY = 'astroquery-custom-palette'

export function isValidHexColor(color) {
  return typeof color === 'string' && /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(color.trim())
}

export function normalizeHex(color) {
  if (!color) return '#000000'
  let c = color.trim()
  if (!c.startsWith('#')) c = '#' + c
  if (c.length === 4) {
    c = '#' + c[1] + c[1] + c[2] + c[2] + c[3] + c[3]
  }
  return c.toLowerCase()
}

export function applyPaletteToDOM(palette) {
  if (typeof document === 'undefined' || !document.documentElement) return
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark'
  const root = document.documentElement.style
  if (isDark) {
    root.removeProperty('--seed-accent')
    root.removeProperty('--seed-bg')
    root.removeProperty('--seed-surface')
    root.removeProperty('--seed-ink')
    root.removeProperty('--seed-aux')
    return
  }
  if (palette.accent && isValidHexColor(palette.accent)) {
    root.setProperty('--seed-accent', palette.accent)
  }
  if (palette.bg && isValidHexColor(palette.bg)) {
    root.setProperty('--seed-bg', palette.bg)
  }
  if (palette.surface && isValidHexColor(palette.surface)) {
    root.setProperty('--seed-surface', palette.surface)
  }
  if (palette.ink && isValidHexColor(palette.ink)) {
    root.setProperty('--seed-ink', palette.ink)
  }
  if (palette.aux && isValidHexColor(palette.aux)) {
    root.setProperty('--seed-aux', palette.aux)
  }
}

export function loadSavedPalette() {
  try {
    if (typeof localStorage !== 'undefined') {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw)
        return {
          accent: isValidHexColor(parsed.accent) ? parsed.accent : DEFAULT_PALETTE.accent,
          bg: isValidHexColor(parsed.bg) ? parsed.bg : DEFAULT_PALETTE.bg,
          surface: isValidHexColor(parsed.surface) ? parsed.surface : DEFAULT_PALETTE.surface,
          ink: isValidHexColor(parsed.ink) ? parsed.ink : DEFAULT_PALETTE.ink,
          aux: isValidHexColor(parsed.aux) ? parsed.aux : DEFAULT_PALETTE.aux,
        }
      }
    }
  } catch {
    /* fallback to default */
  }
  return { ...DEFAULT_PALETTE }
}

export function savePalette(palette) {
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(palette))
    }
  } catch {
    /* ignore */
  }
  applyPaletteToDOM(palette)
}

export function resetPaletteToDefault() {
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    /* ignore */
  }
  applyPaletteToDOM(DEFAULT_PALETTE)
  return { ...DEFAULT_PALETTE }
}
