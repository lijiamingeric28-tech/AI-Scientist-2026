import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const rootDir = join(__dirname, '..')

function readFile(relPath) {
  return readFileSync(join(rootDir, relPath), 'utf8')
}

test('presentationDemo.js exports required interface and control lifecycle', () => {
  const code = readFile('src/lib/presentationDemo.js')

  // Exports startAstroDemo, stopAstroDemo, initPresentationDemo, isDemoRunning
  assert.match(code, /export\s+(async\s+)?function\s+startAstroDemo/)
  assert.match(code, /export\s+function\s+stopAstroDemo/)
  assert.match(code, /export\s+function\s+initPresentationDemo/)
  assert.match(code, /export\s+function\s+isDemoRunning/)

  // Exposes to window for direct console triggering
  assert.match(code, /window\.startAstroDemo\s*=\s*startAstroDemo/)
  assert.match(code, /window\.stopAstroDemo\s*=\s*stopAstroDemo/)
  assert.match(code, /window\.isAstroDemoRunning\s*=\s*isDemoRunning/)

  // Dispatches status event
  assert.match(code, /astro-demo-status/)
})

test('presentationDemo.js implements smooth easing, spotlight cursor, and ripple animation', () => {
  const code = readFile('src/lib/presentationDemo.js')

  // Cubic Ease In-Out algorithm
  assert.match(code, /easeInOutCubic/)
  assert.match(code, /4\s*\*\s*t\s*\*\s*t\s*\*\s*t/)

  // Spotlight cursor with halo and ripple
  assert.match(code, /demo-spotlight-cursor/)
  assert.match(code, /demo-cursor-halo/)
  assert.match(code, /demo-click-ripple/)

  // Keyboard shortcut listener (Esc, Alt+D, Ctrl+Shift+D)
  assert.match(code, /e\.key\s*===\s*'Escape'/)
  assert.match(code, /e\.key\.toLowerCase\(\)\s*===\s*'d'/)
})

test('presentationDemo.js accurately targets M45 09-01 and auto-clicks human confirmation step', () => {
  const code = readFile('src/lib/presentationDemo.js')

  // Act 1: Homepage & chips
  assert.match(code, /第一幕：系统首页与定位/)
  assert.match(code, /filter-chip/)

  // Act 2: Sample gallery targets 昴星团 M45 (09-01 版)
  assert.match(code, /第二幕：演示样例生态画廊/)
  assert.match(code, /昴星团/)
  assert.match(code, /09-01/)
  assert.match(code, /findM45Card/)

  // Act 3: 100x Replay with human confirmation auto-click and completion-outcome dynamic detection
  assert.match(code, /第三幕：多智能体自主执行与百倍速回放/)
  assert.match(code, /确认 \(y\)/)
  assert.match(code, /completion-outcome/)

  // Act 4: Data view, evidence drawer, figure lightbox, quality radar, and 3 subtabs
  assert.match(code, /第四幕：数据结果、证据溯源与质量洞察/)
  assert.match(code, /查看数据结果/)

  // 需求 1: 抽屉先点开定位图灯箱，关闭后大幅下滚 920px 直达“处理历程 1 步”，绝不误触 (i) 图标
  assert.match(code, /getScrollableContainer/)
  assert.match(code, /record-detail-body/)
  assert.match(code, /查看原文定位图/)
  assert.match(code, /关闭定位图/)
  assert.match(code, /920/)
  assert.match(code, /button\[aria-label="关闭记录详情"\]/)

  // 需求 2: 向下滑动记录表格展示来源多样性，并向下滑动来源详情展示学术细节
  assert.match(code, /records-table-region/)
  assert.match(code, /source-title/)
  assert.match(code, /来源详情向下滑动展示/)

  // 需求 3: 交互点击六维雷达图顶点并锁定展示细分指标说明
  assert.match(code, /格式规范/)
  assert.match(code, /radarSvg/)

  // 需求 4 & 细化: 质量与洞察下的三大子界面串联跳转（来源评分、修改记录、数据洞察三项手风琴）
  assert.match(code, /来源评分/)
  assert.match(code, /查看解释/)
  assert.match(code, /点击来源论文标题，滑出右侧文献详情侧边栏/)
  assert.match(code, /修改记录/)
  assert.match(code, /修改记录表格向下滑动展示天体性质清洗前后数值对比/)
  assert.match(code, /数据洞察/)
  assert.match(code, /字段洞察/)
  assert.match(code, /测量分布/)
  assert.match(code, /字段关系/)
  assert.match(code, /导出结果/)

  // Act 5: Workflow audit & return to samples - 精准点击第 4 部分「4 质量检查」、日志与错误及「全过程概览」
  assert.match(code, /第五幕：工作流全链路审计与阶段下钻/)
  assert.match(code, /工作流/)
  assert.match(code, /质量检查/)
  assert.match(code, /全过程概览/)
  assert.match(code, /kpiCard/)
  assert.match(code, /back-to-samples-btn/)

  // Act 6: Help page deep scroll 1050px & Settings 3-way showcase
  assert.match(code, /第六幕：使用帮助、科学设置与主题切换/)
  assert.match(code, /使用帮助/)
  assert.match(code, /大幅深度向下滚动使用帮助页面 1050px/)
  assert.match(code, /1050/)
  assert.match(code, /设置/)
  assert.match(code, /连接与密钥/)
  assert.match(code, /界面与回放/)
  assert.match(code, /模型与系统/)
  assert.match(code, /replay-speed/)
})

test('styles.css contains styling for spotlight cursor, ripple, and countdown toast', () => {
  const css = readFile('src/styles.css')

  // Cursor & ripple
  assert.match(css, /#demo-spotlight-cursor/)
  assert.match(css, /\.demo-cursor-pointer/)
  assert.match(css, /\.demo-cursor-halo/)
  assert.match(css, /\.demo-click-ripple/)
  assert.match(css, /@keyframes demoRippleAnim/)

  // Countdown toast
  assert.match(css, /\.demo-countdown-toast/)
  assert.match(css, /\.demo-badge/)
  assert.match(css, /\.demo-timer/)
})

test('App.jsx mounts presentation demo engine without UI button clutter (clean UI mode)', () => {
  const appJsx = readFile('src/App.jsx')

  // Imported and mounted
  assert.match(appJsx, /import\s+\{[^}]*initPresentationDemo[^}]*\}\s+from\s+'@\/lib\/presentationDemo'/)
  assert.match(appJsx, /initPresentationDemo\(\)/)

  // Clean UI mode: NO demo-record-launcher button in App.jsx DOM
  assert.doesNotMatch(appJsx, /className=\{`demo-record-launcher/)
  assert.doesNotMatch(appJsx, /<span className="launcher-dot"/)
})

test('start_demo.py launcher script exists and triggers demo via Win32 Alt+D', () => {
  const pyPath = join(rootDir, '..', 'scripts', 'start_demo.py')
  assert.ok(existsSync(pyPath), 'start_demo.py must exist in scripts')
  const pyCode = readFileSync(pyPath, 'utf8')
  assert.match(pyCode, /find_astroquery_hwnd/)
  assert.match(pyCode, /trigger_alt_d/)
  assert.match(pyCode, /VK_MENU/)
  assert.match(pyCode, /VK_D/)
})
