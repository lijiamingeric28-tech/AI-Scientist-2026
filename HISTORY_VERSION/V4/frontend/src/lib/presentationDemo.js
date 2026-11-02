/**
 * 答辩展示录屏专用：两分半全流程自动化演示引擎 (Presentation Auto-Demo Engine)
 *
 * 功能特性：
 * 1. 模拟专业导览高亮演示光标（Spotlight Cursor，含缓动位移、Hover 悬停感知与点击波浪扩散动效）
 * 2. 状态驱动自适应时序编排（六幕剧本，总时长约 150 秒 / 2 分 30 秒）
 * 3. 动态事件监听（百倍速回放完成自适应侦测，不僵死盲等）
 * 4. 任意时刻按 Esc 键安全紧急中断
 */

// 状态单例
let demoRunning = false
let activeAbortController = null
let cursorEl = null
let countdownOverlayEl = null

/**
 * 缓动计算 (Cubic Ease In-Out)
 */
function easeInOutCubic(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

/**
 * 异步睡眠
 */
function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new Error('DEMO_ABORTED'))
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(new Error('DEMO_ABORTED'))
    }, { once: true })
  })
}

/**
 * 查找页面元素（支持 CSS 选择器、包含文本、或两者结合）
 */
function findElement(selector, textMatch = null) {
  const elements = Array.from(document.querySelectorAll(selector))
  if (!textMatch) return elements[0] || null
  const target = elements.find((el) => {
    const txt = (el.innerText || el.textContent || '').trim()
    return txt.includes(textMatch)
  })
  return target || null
}

/**
 * 动态等待指定条件满足（自带超时）
 */
async function waitFor(conditionFn, timeout = 75000, interval = 200, signal = null) {
  const startTime = Date.now()
  while (Date.now() - startTime < timeout) {
    if (signal?.aborted) throw new Error('DEMO_ABORTED')
    const result = conditionFn()
    if (result) return result
    await sleep(interval, signal)
  }
  return null
}

/**
 * 初始化高亮演示光标 DOM
 */
function ensureCursor() {
  if (cursorEl) return cursorEl
  cursorEl = document.createElement('div')
  cursorEl.id = 'demo-spotlight-cursor'
  cursorEl.innerHTML = `
    <div class="demo-cursor-pointer">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M4 3L11 20L14 13L21 10L4 3Z" fill="#1b4332" stroke="#ffffff" stroke-width="2" stroke-linejoin="round"/>
      </svg>
    </div>
    <div class="demo-cursor-halo"></div>
    <div class="demo-click-ripple"></div>
  `
  document.body.appendChild(cursorEl)
  return cursorEl
}

/**
 * 移除高亮光标
 */
function removeCursor() {
  if (cursorEl) {
    cursorEl.remove()
    cursorEl = null
  }
}

/**
 * 获取当前光标位置
 */
let currentCursorPos = { x: window.innerWidth * 0.8, y: window.innerHeight * 0.8 }

function setCursorPos(x, y) {
  currentCursorPos = { x, y }
  if (cursorEl) {
    cursorEl.style.transform = `translate3d(${x}px, ${y}px, 0)`
  }
}

/**
 * 平滑移动演示光标至指定视口坐标
 */
function smoothMoveToCoords(targetX, targetY, duration = 800, signal = null) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new Error('DEMO_ABORTED'))
    ensureCursor()

    const startX = currentCursorPos.x
    const startY = currentCursorPos.y
    const startTime = performance.now()

    function step(currentTime) {
      if (signal?.aborted) return reject(new Error('DEMO_ABORTED'))
      const elapsed = currentTime - startTime
      const progress = Math.min(1, elapsed / duration)
      const eased = easeInOutCubic(progress)

      const curX = startX + (targetX - startX) * eased
      const curY = startY + (targetY - startY) * eased
      setCursorPos(curX, curY)

      if (progress < 1) {
        requestAnimationFrame(step)
      } else {
        resolve()
      }
    }

    requestAnimationFrame(step)
  })
}

/**
 * 移动演示光标至元素中心
 */
async function moveToElement(elOrSelector, text = null, duration = 800, offset = { x: 0, y: 0 }, signal = null) {
  const el = typeof elOrSelector === 'string' ? findElement(elOrSelector, text) : elOrSelector
  if (!el) return null

  // 确保元素可见，平滑微调视口
  try {
    const rBefore = el.getBoundingClientRect()
    if (rBefore.top < 60 || rBefore.bottom > window.innerHeight - 60) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      await sleep(300, signal)
    }
  } catch {}

  const rect = el.getBoundingClientRect()
  const targetX = rect.left + rect.width / 2 + offset.x
  const targetY = rect.top + rect.height / 2 + offset.y

  await smoothMoveToCoords(targetX, targetY, duration, signal)

  // 触发 hover
  try {
    el.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }))
    el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
  } catch {}

  return el
}

/**
 * 点击元素（附带波纹扩散效果与真实事件下发）
 */
async function clickElement(elOrSelector, text = null, moveDuration = 800, signal = null) {
  const el = await moveToElement(elOrSelector, text, moveDuration, { x: 0, y: 0 }, signal)
  if (!el) return false

  await sleep(150, signal)

  // 触发波纹动效
  if (cursorEl) {
    const ripple = cursorEl.querySelector('.demo-click-ripple')
    if (ripple) {
      ripple.classList.remove('active')
      void ripple.offsetWidth
      ripple.classList.add('active')
    }
  }

  // 触发真实 DOM 交互
  try {
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    el.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    el.dispatchEvent(new MouseEvent('pointerup', { bubbles: true }))
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    if (typeof el.click === 'function') el.click()
  } catch {}

  await sleep(250, signal)
  return true
}

/**
 * 智能探查并获取真正具备垂直滚动能力的容器元素
 */
function getScrollableContainer(selectorOrEl) {
  if (!selectorOrEl) return null
  if (typeof selectorOrEl !== 'string') return selectorOrEl

  const candidates = Array.from(document.querySelectorAll(selectorOrEl))
  if (!candidates.length) return null

  // 1. 优先寻找计算样式有 auto/scroll 且实际发生溢出的元素
  const scrollable = candidates.find((el) => {
    try {
      const style = window.getComputedStyle(el)
      const isOverflow = (
        style.overflowY === 'auto' || style.overflowY === 'scroll' ||
        style.overflow === 'auto' || style.overflow === 'scroll'
      )
      return isOverflow && (el.scrollHeight > el.clientHeight + 5)
    } catch {
      return false
    }
  })
  if (scrollable) return scrollable

  // 2. 兜底寻找内容超出可视高度的容器
  const hasOverflow = candidates.find((el) => el.scrollHeight > el.clientHeight + 10)
  if (hasOverflow) return hasOverflow

  return candidates[0] || null
}

/**
 * 容器内部平滑滚动 (自带 EaseInOutCubic 缓动、智能容器探查与 scroll-behavior 冲突防护)
 */
async function smoothScrollContainer(containerSelectorOrEl, deltaY, duration = 800, signal = null) {
  const container = getScrollableContainer(containerSelectorOrEl)
  if (!container) return

  const prevBehavior = container.style.scrollBehavior
  container.style.scrollBehavior = 'auto'

  const startY = container.scrollTop
  const maxScroll = Math.max(0, container.scrollHeight - container.clientHeight)
  const targetY = Math.min(maxScroll, Math.max(0, startY + deltaY))
  if (Math.abs(targetY - startY) < 2) {
    container.style.scrollBehavior = prevBehavior
    return
  }
  const startTime = performance.now()

  return new Promise((resolve) => {
    function step(now) {
      if (signal?.aborted) {
        container.style.scrollBehavior = prevBehavior
        return resolve()
      }
      const p = Math.min(1, (now - startTime) / duration)
      container.scrollTop = startY + (targetY - startY) * easeInOutCubic(p)
      if (p < 1) {
        requestAnimationFrame(step)
      } else {
        container.scrollTop = targetY
        container.style.scrollBehavior = prevBehavior
        resolve()
      }
    }
    requestAnimationFrame(step)
  })
}

/**
 * 显示倒计时通知
 */
function showCountdown(seconds = 5) {
  return new Promise((resolve, reject) => {
    countdownOverlayEl = document.createElement('div')
    countdownOverlayEl.className = 'demo-countdown-toast'
    document.body.appendChild(countdownOverlayEl)

    let remain = seconds
    const updateText = () => {
      countdownOverlayEl.innerHTML = `
        <div class="demo-countdown-content">
          <span class="demo-badge">🎬 答辩录屏演示就绪</span>
          <span class="demo-timer">${remain}</span>
          <p>请切换到 Recordly 录屏软件准备录制（随时按 <b>Esc</b> 退出）</p>
          <div class="demo-actions">
            <button id="demo-now-btn" class="demo-btn-primary">立即开始</button>
            <button id="demo-cancel-btn" class="demo-btn-ghost">取消</button>
          </div>
        </div>
      `
      document.getElementById('demo-now-btn')?.addEventListener('click', () => {
        clearInterval(timer)
        finish()
      })
      document.getElementById('demo-cancel-btn')?.addEventListener('click', () => {
        clearInterval(timer)
        cleanup()
        reject(new Error('DEMO_CANCELLED'))
      })
    }

    const cleanup = () => {
      if (countdownOverlayEl) {
        countdownOverlayEl.remove()
        countdownOverlayEl = null
      }
    }

    const finish = () => {
      cleanup()
      resolve()
    }

    updateText()
    const timer = setInterval(() => {
      remain -= 1
      if (remain <= 0) {
        clearInterval(timer)
        finish()
      } else {
        updateText()
      }
    }, 1000)
  })
}

/**
 * 六幕全流程演播主控逻辑 (~150 秒 / 2 分半)
 */
async function executeChoreographedDemo(signal) {
  console.log('[AutoDemo] 🎬 演播开始')
  ensureCursor()
  setCursorPos(window.innerWidth * 0.7, window.innerHeight * 0.7)

  // ==========================================
  // 第一幕：系统首页与定位 (约 12 秒)
  // ==========================================
  console.log('[AutoDemo] 幕一：系统首页与定位')
  // 1. 光标滑入任务标题区
  await smoothMoveToCoords(window.innerWidth * 0.45, 45, 900, signal)
  await sleep(1200, signal)

  // 2. 悬浮展示智能提示词芯片
  const promptChip = findElement('.empty-state .filter-chip, .filter-chip')
  if (promptChip) {
    await moveToElement(promptChip, null, 1000, { x: 0, y: 0 }, signal)
    await sleep(2000, signal)
  }

  // 3. 悬浮展示下方输入舱
  const chatInput = findElement('textarea, input[placeholder*="输入需求"]')
  if (chatInput) {
    await moveToElement(chatInput, null, 900, { x: 0, y: 0 }, signal)
    await sleep(1800, signal)
  }

  // 4. 移向左侧栏切换区
  const sampleTab = findElement('button', '演示样例')
  if (sampleTab) {
    await moveToElement(sampleTab, null, 900, { x: 0, y: 0 }, signal)
    await sleep(1200, signal)
  }

  // ==========================================
  // 第二幕：演示样例生态画廊 (约 14 秒)
  // ==========================================
  console.log('[AutoDemo] 幕二：演示样例画廊')
  if (sampleTab) {
    await clickElement(sampleTab, null, 400, signal)
    await sleep(1200, signal)
  }

  // 精准寻找“昴星团 M45（09-01 版）”样例卡片（首字为「昴」mǎo，避免与「昂」或「参宿四」混淆）
  const findM45Card = () => {
    const cards = Array.from(document.querySelectorAll('.hover-lift'))
    return cards.find((el) => {
      const txt = (el.innerText || el.textContent || '').replace(/\s+/g, '')
      return (txt.includes('昴星团') || txt.includes('昂星团') || txt.includes('M45')) && txt.includes('09-01')
    }) || cards.find((el) => {
      const txt = (el.innerText || el.textContent || '').replace(/\s+/g, '')
      return (txt.includes('昴星团') || txt.includes('昂星团')) && txt.includes('M45')
    }) || null
  }

  const m45Card = findM45Card()
  if (!m45Card) {
    console.error('[AutoDemo] 严重错误：未在画廊中找到「昴星团 M45（09-01 版）」卡片')
    throw new Error('M45_CARD_NOT_FOUND')
  }

  // 平滑将 M45 卡片移入视口中央并悬停展示
  try {
    m45Card.scrollIntoView({ behavior: 'smooth', block: 'center' })
    await sleep(700, signal)
  } catch {}

  await moveToElement(m45Card, null, 900, { x: 0, y: 0 }, signal)
  await sleep(1800, signal) // 悬停展示名称、质量分 86.51 与 111 条记录

  // ==========================================
  // 第三幕：多智能体自主执行与百倍速回放 (动态侦测成果与人工确认)
  // ==========================================
  console.log('[AutoDemo] 幕三：昂星团 M45 回放执行')
  // 严格在 M45 卡片内部寻找【回放过程】按钮，绝不跨越到其它卡片
  const targetReplayBtn = Array.from(m45Card.querySelectorAll('button')).find((b) => {
    const txt = (b.innerText || b.textContent || '').trim()
    return txt.includes('回放')
  })
  
  if (!targetReplayBtn) {
    console.error('[AutoDemo] 严重错误：未在 M45 卡片内找到回放按钮')
    throw new Error('M45_REPLAY_BTN_NOT_FOUND')
  }

  await clickElement(targetReplayBtn, null, 600, signal)
  await sleep(2500, signal)

  // 回放开始：动态跟随时间线与阶段，并自动处理人工确认 (HITL)
  const replayStartTime = Date.now()
  let hasOutcome = false

  while (Date.now() - replayStartTime < 90000) {
    if (signal?.aborted) throw new Error('DEMO_ABORTED')

    // 1. 终态检测：成果卡片是否出现
    const outcomeCard = findElement('.completion-outcome, [data-component="completion-outcome"]')
    if (outcomeCard) {
      hasOutcome = true
      break
    }

    // 2. 核心：检测是否出现人工确认卡片 (HITL 确认/澄清/复核)
    // 页面上的确认按钮通常为 "确认 (y)"、"确认"
    const confirmBtn = Array.from(document.querySelectorAll('button')).find((b) => {
      const txt = (b.innerText || b.textContent || '').trim()
      return (txt === '确认 (y)' || txt.includes('确认 (y)') || txt.includes('确认(y)')) && !b.disabled && b.offsetParent !== null
    })

    if (confirmBtn) {
      console.log('[AutoDemo] 💡 侦测到人工确认步骤 [确认 (y)]，平滑移动并自动确认...')
      try {
        confirmBtn.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        await sleep(300, signal)
      } catch {}

      // 演示光标平滑移动到确认按钮并悬停展示
      await moveToElement(confirmBtn, null, 800, { x: 0, y: 0 }, signal)
      await sleep(600, signal) // 稍作悬停，展示人机交互真实感
      await clickElement(confirmBtn, null, 400, signal)
      console.log('[AutoDemo] ✅ 已成功点击确认 (y)，执行继续推进')
      await sleep(2000, signal)
      continue
    }

    // 若顶栏有待处理提示按钮（如 "待确认 · 去处理"），点击它唤起定位
    const pendingHeaderBtn = Array.from(document.querySelectorAll('button')).find((b) => {
      const txt = (b.innerText || b.textContent || '').trim()
      return (txt.includes('待确认') || txt.includes('待复核')) && txt.includes('去处理') && !b.disabled
    })
    if (pendingHeaderBtn && !findElement('.clarification-card, [style*="border: 1px solid var(--progress-border"]')) {
      await clickElement(pendingHeaderBtn, null, 500, signal)
      await sleep(800, signal)
      continue
    }

    // 3. 正常执行中：平滑跟随时间线内活跃/进行中阶段
    const activeStage = findElement('.stage-card', '进行中') || findElement('.animate-pulse-dot')
    if (activeStage) {
      await moveToElement(activeStage, null, 1200, { x: 40, y: 0 }, signal)
    }

    // 4. 平滑微滚动跟随时间线
    await smoothScrollContainer('.app-reading, .task-views, .task-view, .chat-view', 80, 800, signal)
    await sleep(2000, signal)
  }

  console.log('[AutoDemo] 回放执行完成或成果呈现')
  await sleep(1500, signal)

  // 成果卡展示（第三张图片效果）
  const outcomeCard = findElement('.completion-outcome, [data-component="completion-outcome"]')
  if (outcomeCard) {
    await moveToElement(outcomeCard, null, 1000, { x: 0, y: -40 }, signal)
    await sleep(3500, signal) // 重点停留展示 111 记录、28 来源、77 图像、86.51 综合评分
  }

  // ==========================================
  // 第四幕：数据结果、证据溯源与质量洞察
  // ==========================================
  console.log('[AutoDemo] 幕四：数据结果、证据溯源与质量洞察')
  // 1. 点击查看数据结果按钮（优先成果卡片内“查看数据结果 →”，或顶栏“数据结果”标签）
  const openDataBtn = findElement('button', '查看数据结果') || findElement('.primary-tab', '数据结果')
  if (openDataBtn) {
    await clickElement(openDataBtn, null, 700, signal)
    await sleep(1600, signal)
  }

  // 确保处于“记录”子标签
  const recordsTab = findElement('.data-tabs button, .tab-btn', '记录')
  if (recordsTab && !recordsTab.classList.contains('active')) {
    await clickElement(recordsTab, null, 400, signal)
    await sleep(800, signal)
  }

  // ========================================================
  // [需求 1] 精准点击第一条数据行，滑出出处与证据抽屉；
  // 先展开全屏定位图灯箱展示红框论文页，关闭灯箱后；
  // 深度向下平滑滚动直达底部，完整展示“测量方法与条件”及“处理历程 1 步”（原始测量、数值整理与当前测量）；
  // 驻留 2 秒后，再严格使用 button[aria-label="关闭记录详情"] 关闭抽屉（绝不误触 (i) 图标）
  // ========================================================
  console.log('[AutoDemo] 点击第一条记录展示出处与证据抽屉...')
  try { window.getSelection()?.removeAllRanges?.() } catch {}

  const firstRow = findElement('.records-table tbody tr.record-row, .records-table tbody tr')
  if (firstRow) {
    const targetCell = firstRow.querySelector('td:nth-child(2)') || firstRow.querySelector('td') || firstRow
    await clickElement(targetCell, null, 800, signal)
    await sleep(1500, signal)

    let drawer = await waitFor(() => findElement('.context-drawer, [data-component="record-detail"]'), 3000, 200, signal)
    if (!drawer) {
      try { window.getSelection()?.removeAllRanges?.() } catch {}
      await clickElement(firstRow, null, 400, signal)
      drawer = await waitFor(() => findElement('.context-drawer, [data-component="record-detail"]'), 3000, 200, signal)
    }

    if (drawer) {
      console.log('[AutoDemo] 出处与证据抽屉已展开，光标移入抽屉上半部...')
      const drawerRect = drawer.getBoundingClientRect()
      await smoothMoveToCoords(drawerRect.left + drawerRect.width * 0.5, drawerRect.top + 160, 700, signal)
      await sleep(1000, signal)

      // ① 先点击原文定位图，弹出全屏灯箱（展示带有红框的 ApJ 论文页）
      const paperThumbnail = drawer.querySelector('div[aria-label="查看原文定位图"], img[alt="溯源定位图"]')
      if (paperThumbnail) {
        console.log('[AutoDemo] 点击原文定位图展开全屏灯箱...')
        await clickElement(paperThumbnail, null, 700, signal)
        await sleep(2000, signal) // 弹出全屏 SourceImageLightbox

        // 精准关闭定位图灯箱（寻找 aria-label="关闭定位图" 或 title="关闭" 的关闭按钮）
        const lightboxModal = findElement('div[aria-label="原文定位图"], [role="dialog"][aria-label="原文定位图"]')
        const closeLightboxBtn = lightboxModal ? (
          lightboxModal.querySelector('button[aria-label="关闭定位图"], button[title="关闭"]') ||
          Array.from(lightboxModal.querySelectorAll('button')).find(b => (b.getAttribute('aria-label') || '').includes('关闭') || (b.getAttribute('title') || '').includes('关闭') || (b.innerText || '').includes('✕'))
        ) : null

        if (closeLightboxBtn) {
          console.log('[AutoDemo] 精准点击定位图灯箱关闭按钮 [✕]...')
          await clickElement(closeLightboxBtn, null, 600, signal)
          await sleep(900, signal)
        } else {
          window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
          await sleep(600, signal)
        }
      }

      // ② 向下滑动抽屉内容区（.record-detail-body）大幅下滑直达底部，完整揭示“测量方法与条件”及“处理历程 1 步”（图 1 效果）
      console.log('[AutoDemo] 抽屉深度向下滑动直达底部，展示测量方法与处理历程（1 步）及当前测量...')
      await smoothScrollContainer('.record-detail-body', 920, 1200, signal)
      // 光标平滑移入处理历程区并悬停展示
      const changeCard = drawer.querySelector('.record-changes, .record-history')
      if (changeCard) {
        await moveToElement(changeCard, null, 700, { x: 0, y: 30 }, signal)
      }
      await sleep(2400, signal) // 充分停留让评委看清原始测量 -> 整理数值与误差格式 -> 当前测量

      // ③ 正确关闭记录详情抽屉：严格锁定 aria-label="关闭记录详情"，绝对避免误点击 DefinitionNote 的 ⓘ 按钮
      const closeDrawerBtn = drawer.querySelector('button[aria-label="关闭记录详情"], .record-detail-heading button[aria-label="关闭记录详情"]')
      if (closeDrawerBtn) {
        console.log('[AutoDemo] 正确关闭记录详情抽屉（严格锁定关闭按钮，绝不误触 ⓘ）...')
        await clickElement(closeDrawerBtn, null, 600, signal)
        await sleep(900, signal)
      }
    }
  }

  // ========================================================
  // [需求 2] 适当向下滑动数据表格，展示数据来源多样性（ApJ 1999, AJ 2001, A&A 2004 等）
  // ========================================================
  console.log('[AutoDemo] 向下滑动记录表格，展示数据来源多样性...')
  await smoothMoveToCoords(window.innerWidth * 0.45, window.innerHeight * 0.55, 600, signal)
  await smoothScrollContainer('.records-table-region, .data-workbench', 260, 1000, signal)
  await sleep(1800, signal)

  // ========================================================
  // [需求 2 & 来源与图像] 切换至【来源与图像】，点开论文详情并向下滑动展示细节后正确关闭，
  // 点开科研图像弹出高清灯箱并精准关闭
  // ========================================================
  const evidenceTab = findElement('.data-tabs button, .tab-btn', '来源与图像')
  if (evidenceTab) {
    console.log('[AutoDemo] 切换至「来源与图像」标签页...')
    await clickElement(evidenceTab, null, 700, signal)
    await sleep(1400, signal)

    // 点开论文详情卡片（图片四效果）
    const firstPaperTitleBtn = findElement('.source-title, .report-section button.source-title')
    if (firstPaperTitleBtn) {
      console.log('[AutoDemo] 点击打开论文详情（来源详情抽屉）...')
      await clickElement(firstPaperTitleBtn, null, 700, signal)
      await sleep(1500, signal)

      // 来源详情抽屉滑出后，向下滑动展示作者、DOI与摘要细节
      const sourceDrawer = await waitFor(() => findElement('.context-drawer'), 2500, 200, signal)
      if (sourceDrawer) {
        await smoothMoveToCoords(sourceDrawer.getBoundingClientRect().left + 160, 220, 600, signal)
        await sleep(1000, signal)

        console.log('[AutoDemo] 来源详情向下滑动展示作者与摘要细节...')
        await smoothScrollContainer('.context-content, .source-reading, .context-drawer', 260, 900, signal)
        await sleep(1800, signal)

        // 正确关闭来源详情抽屉
        const closeSourceBtn = sourceDrawer.querySelector('.settings-header button') ||
          Array.from(sourceDrawer.querySelectorAll('button')).find(b => (b.innerText || '').includes('关闭'))
        if (closeSourceBtn) {
          console.log('[AutoDemo] 正确关闭来源详情抽屉...')
          await clickElement(closeSourceBtn, null, 600, signal)
          await sleep(900, signal)
        }
      }
    }

    // 点击科研图像卡片，弹出全屏灯箱，并精准点击关闭按钮
    const firstFig = findElement('.figure-card button, .figure-button')
    if (firstFig) {
      console.log('[AutoDemo] 点击查看高清科研图像灯箱...')
      await clickElement(firstFig, null, 700, signal)
      await sleep(2000, signal)

      const lightboxModal = findElement('[data-component="figure-lightbox"]')
      const closeLightboxBtn = lightboxModal ? (
        lightboxModal.querySelector('button[title*="关闭"]') ||
        Array.from(lightboxModal.querySelectorAll('button')).find(b => (b.getAttribute('title') || '').includes('关闭') || (b.innerText || '').includes('✕')) ||
        lightboxModal.querySelector('header button:last-child, div > button:last-child')
      ) : null

      if (closeLightboxBtn) {
        console.log('[AutoDemo] 精准点击科研图像灯箱关闭按钮 [✕]...')
        await clickElement(closeLightboxBtn, null, 600, signal)
        await sleep(900, signal)
      } else {
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
        await sleep(600, signal)
      }
    }
  }

  // ========================================================
  // [需求 3 & 4] 切换至【质量与洞察】
  // 1. 六维雷达图顶点交互锁定与细分指标说明展示 (图 5)
  // 2. 依次点击跳转并展示：来源评分、修改记录、数据洞察
  // ========================================================
  const analysisTab = findElement('.data-tabs button, .tab-btn', '质量与洞察')
  if (analysisTab) {
    console.log('[AutoDemo] 切换至「质量与洞察」标签页...')
    await clickElement(analysisTab, null, 700, signal)
    await sleep(1500, signal)

    // A. 六维质量雷达图交互与顶点锁定 (需求 3)
    const radarSvg = findElement('svg[aria-label*="雷达图"], .radar-data, svg')
    if (radarSvg) {
      const dimGroups = Array.from(radarSvg.querySelectorAll('g[tabIndex="0"]'))
      const targetGroup = dimGroups.find(el => (el.textContent || '').includes('格式规范')) ||
                          dimGroups.find(el => (el.textContent || '').includes('一致性')) ||
                          dimGroups[0]

      if (targetGroup) {
        console.log('[AutoDemo] 交互点击六维雷达图顶点「格式规范」并锁定展示说明...')
        await clickElement(targetGroup, null, 700, signal)
        await sleep(2500, signal) // 重点停留展示底部细分指标说明 Tooltip (图 5 效果)
      }
    }

    // B. 来源评分子界面 (需求 2: 点击论文名滑出侧边栏展示并关闭)
    console.log('[AutoDemo] 切换至「来源评分」子界面...')
    const sourcesSubTab = findElement('.analysis-view .tab-btn, .section-tabs .tab-btn', '来源评分')
    if (sourcesSubTab) {
      await clickElement(sourcesSubTab, null, 600, signal)
      await sleep(1200, signal)
      // 向下滑动来源评分表格展示各源评分
      await smoothScrollContainer('.data-workbench', 180, 800, signal)
      await sleep(1000, signal)
      // 点击第一行的“查看解释”按钮展开多维评分细项
      const explainBtn = findElement('.analysis-pane table button.text-link', '查看解释')
      if (explainBtn) {
        console.log('[AutoDemo] 点击展开来源评分多维解释...')
        await clickElement(explainBtn, null, 600, signal)
        await sleep(1800, signal) // 停留展示维度分、抽取质量与具体影响
      }

      // [需求 2 核心] 点击论文名称（button.source-title），滑出右侧“来源详情”侧边栏（图 2 效果）
      const sourceTitleBtn = findElement('.analysis-pane table button.source-title, .analysis-pane table button.text-link')
      if (sourceTitleBtn) {
        console.log('[AutoDemo] 点击来源论文标题，滑出右侧文献详情侧边栏...')
        await clickElement(sourceTitleBtn, null, 600, signal)
        await sleep(1800, signal) // 侧边栏滑出后展示文献作者、DOI与元数据

        // 关闭滑出的来源详情侧边栏
        const closeSourceDrawerBtn = findElement('.context-drawer .settings-header button', '关闭') ||
          findElement('.context-drawer button[aria-label*="关闭"]') ||
          findElement('.context-drawer .settings-header button')
        if (closeSourceDrawerBtn) {
          console.log('[AutoDemo] 正确关闭来源详情侧边栏...')
          await clickElement(closeSourceDrawerBtn, null, 500, signal)
          await sleep(900, signal)
        }
      }
    }

    // C. 修改记录子界面 (需求 3: 向下滑动展示天体性质清洗记录)
    console.log('[AutoDemo] 切换至「修改记录」子界面...')
    const modSubTab = findElement('.analysis-view .tab-btn, .section-tabs .tab-btn', '修改记录')
    if (modSubTab) {
      await clickElement(modSubTab, null, 600, signal)
      await sleep(1200, signal)
      // 光标滑入并向下滑动 .data-workbench 360px，展示前后数值对比与处理规则（图 3 效果）
      await smoothMoveToCoords(window.innerWidth * 0.45, window.innerHeight * 0.52, 600, signal)
      console.log('[AutoDemo] 修改记录表格向下滑动展示天体性质清洗前后数值对比...')
      await smoothScrollContainer('.data-workbench', 360, 1000, signal)
      await sleep(2200, signal) // 停留展示数据清洗处理历程
    }

    // D. 数据洞察子界面 (需求 4: 三大子项逐一展开并向下滑动展示)
    console.log('[AutoDemo] 切换至「数据洞察」子界面...')
    const insightSubTab = findElement('.analysis-view .tab-btn, .section-tabs .tab-btn', '数据洞察')
    if (insightSubTab) {
      await clickElement(insightSubTab, null, 600, signal)
      await sleep(1200, signal)

      // ① 子项 1：展开「✦ 字段洞察」并向下滑动
      const fieldInsightToggle = findElement('.insight-section-toggle', '字段洞察')
      if (fieldInsightToggle) {
        console.log('[AutoDemo] 展开 1/3「字段洞察」手风琴并下滚展示...')
        await clickElement(fieldInsightToggle, null, 600, signal)
        await sleep(1200, signal)
        await smoothScrollContainer('.data-workbench', 240, 700, signal)
        await sleep(1500, signal) // 停留展示字段观察与科学解释
      }

      // ② 子项 2：展开「📊 测量分布」并向下滑动
      const measureToggle = findElement('.insight-section-toggle', '测量分布')
      if (measureToggle) {
        console.log('[AutoDemo] 展开 2/3「测量分布」手风琴并下滚展示...')
        await clickElement(measureToggle, null, 600, signal)
        await sleep(1200, signal)
        await smoothScrollContainer('.data-workbench', 300, 700, signal)
        await sleep(1600, signal) // 停留展示多源散点与已有误差对比
      }

      // ③ 子项 3：展开「🕸 字段关系」并向下滑动
      const relationToggle = findElement('.insight-section-toggle', '字段关系')
      if (relationToggle) {
        console.log('[AutoDemo] 展开 3/3「字段关系」手风琴并下滚展示...')
        await clickElement(relationToggle, null, 600, signal)
        await sleep(1200, signal)
        await smoothScrollContainer('.data-workbench', 300, 700, signal)
        await sleep(1800, signal) // 停留展示天体物理性质关联网络图
      }
    }
  }

  // 5. 点击【导出结果】
  const exportBtn = findElement('button', '导出结果')
  if (exportBtn) {
    await clickElement(exportBtn, null, 600, signal)
    await sleep(2000, signal)

    // 关闭导出模态框
    const closeExportBtn = findElement('.export-center header button, .settings-header button')
    if (closeExportBtn) {
      await clickElement(closeExportBtn, null, 500, signal)
      await sleep(800, signal)
    }
  }

  // ==========================================
  // 第五幕：工作流全链路审计与阶段下钻 (约 16 秒)
  // ==========================================
  console.log('[AutoDemo] 幕五：工作流与审计日志')
  // 1. 切换到顶部“工作流”主导航
  const workflowNav = findElement('.primary-tab', '工作流')
  if (workflowNav) {
    await clickElement(workflowNav, null, 700, signal)
    await sleep(1500, signal)
  }

  // 2. 点击进入第 4 部分导航「4 质量检查」（展示 86.51 评分与六维雷达图，图 2 效果）
  const stageNavButtons = Array.from(document.querySelectorAll('.workflow-stage-nav button'))
  const stageNavBtn = findElement('.workflow-stage-nav button', '质量检查') ||
    stageNavButtons.find(b => {
      const txt = (b.innerText || '').replace(/\s+/g, '')
      return txt.includes('质量检查') || txt.includes('4')
    }) ||
    stageNavButtons[3]

  if (stageNavBtn) {
    console.log('[AutoDemo] 点击工作流第 4 部分「4 质量检查」...')
    await clickElement(stageNavBtn, null, 700, signal)
    await sleep(1500, signal)

    // 光标平滑移动至右侧质量评分成果区（86.51 分与六维雷达图），停留展示
    const qualityScoreArea = findElement('.workflow-stage-content .stage-card, .workflow-stage-content')
    if (qualityScoreArea) {
      await smoothMoveToCoords(window.innerWidth * 0.62, window.innerHeight * 0.42, 800, signal)
      await sleep(2200, signal) // 充分停留让观众看清 86.51 分、六维质量雷达图与下方的 ProfilingAgent / QualityAssessmentAgent 执行步骤
    }
  }

  // 3. 点击切换到“日志与错误”
  const logsTab = findElement('.data-tabs button, .tab-btn', '日志与错误')
  if (logsTab) {
    await clickElement(logsTab, null, 700, signal)
    await sleep(1600, signal)

    // 光标扫过 INFO / WARN / ERROR 芯片
    const warnChip = findElement('.log-chip, .chip-warn')
    if (warnChip) {
      await moveToElement(warnChip, null, 600, { x: 0, y: 0 }, signal)
      await sleep(1000, signal)
    }
  }

  // 4. 点击切换到“全过程概览”（展示任务历时 1253.5s 与全过程七阶段耗时报表）
  const statsTab = findElement('.data-tabs button, .tab-btn', '全过程概览')
  if (statsTab) {
    console.log('[AutoDemo] 点击切换至工作流「全过程概览」标签页...')
    await clickElement(statsTab, null, 700, signal)
    await sleep(1500, signal)

    // 光标移入左上角任务历时 KPI 卡片展示总耗时（1253.5s，含等待确认）
    const kpiCard = findElement('.kpi-card, [data-component="execution-overview"] .kpi-card')
    if (kpiCard) {
      await moveToElement(kpiCard, null, 600, { x: 0, y: 0 }, signal)
      await sleep(1200, signal)
    }

    // 光标移向全过程七阶段耗时报表表格并悬停展示
    const reportTable = findElement('.execution-overview table, table.report-table')
    if (reportTable) {
      await moveToElement(reportTable, null, 700, { x: 0, y: 20 }, signal)
      await sleep(2200, signal) // 重点停留展示任务理解至数据洞察的阶段耗时与状态
    }
  }

  // 5. 点击顶栏标题左侧新增的【← 返回图标】，平滑返回演示样例
  const backBtn = findElement('.back-to-samples-btn, button[title*="返回演示样例"]')
  if (backBtn) {
    await clickElement(backBtn, null, 700, signal)
    await sleep(1200, signal)
  }

  // ==========================================
  // 第六幕：使用帮助、科学设置与主题切换 (约 18 秒)
  // ==========================================
  console.log('[AutoDemo] 幕六：使用帮助与设置')
  // 1. 点击左下角【使用帮助】(彻底向下深滚展示五步流程、样例回放、发起真实查询及三个主页面)
  const helpBtn = findElement('.sidebar-help, button', '使用帮助')
  if (helpBtn) {
    await clickElement(helpBtn, null, 700, signal)
    await sleep(1800, signal)

    // 精准锁定具有 overflow: auto 的 .help-page，大幅平滑向下深度滚动 1050px，彻底展示完整科研指南（图 3 效果）
    console.log('[AutoDemo] 大幅深度向下滚动使用帮助页面 1050px，彻底展示科研指南与主页面说明...')
    await smoothMoveToCoords(window.innerWidth * 0.55, window.innerHeight * 0.45, 600, signal)
    await smoothScrollContainer('.help-page', 1050, 1400, signal)
    await sleep(2500, signal) // 充分停留让评委看清发起真实查询步骤与三个主页面结构

    // 点击返回原页面
    const returnHelpBtn = findElement('button', '返回原页面')
    if (returnHelpBtn) {
      await clickElement(returnHelpBtn, null, 600, signal)
      await sleep(1000, signal)
    }
  }

  // 2. 点击左下角【设置】(需求 6: 依次展示连接与密钥、界面与回放、模型与系统三大触发内容)
  const settingsBtn = findElement('button span', '设置')?.parentElement || findElement('button', '设置')
  if (settingsBtn) {
    await clickElement(settingsBtn, null, 700, signal)
    await sleep(1800, signal)

    // ① 展示「连接与密钥」（默认打开）：移动光标展示 4 项科研服务连接凭证
    console.log('[AutoDemo] 展示设置 1/3：连接与密钥配置状态...')
    const connTab = findElement('.settings-nav button, button', '连接与密钥') || findElement('button', '连接')
    if (connTab) {
      await moveToElement(connTab, null, 500, { x: 0, y: 0 }, signal)
      await sleep(1200, signal)
    }

    // ② 展示「界面与回放」：切换标签，展示 100x 速度滑块与主题切换
    console.log('[AutoDemo] 展示设置 2/3：界面与回放（100x 回放速度与主题）...')
    const prefTab = findElement('.settings-nav button, button', '界面与回放') || findElement('button', '偏好')
    if (prefTab) {
      await clickElement(prefTab, null, 600, signal)
      await sleep(1200, signal)

      const speedSlider = findElement('#replay-speed, input[type="range"]')
      if (speedSlider) {
        await moveToElement(speedSlider, null, 600, { x: 20, y: 0 }, signal)
        await sleep(1000, signal)
      }

      const themeToggle = findElement('.preference-row button', '切换主题')
      if (themeToggle) {
        await moveToElement(themeToggle, null, 500, { x: 0, y: 0 }, signal)
        await sleep(800, signal)
      }
    }

    // ③ 展示「模型与系统」：展示生效的多智能体大模型矩阵与输出目录
    console.log('[AutoDemo] 展示设置 3/3：多智能体大模型与系统架构...')
    const sysTab = findElement('.settings-nav button, button', '模型与系统') || findElement('button', '模型')
    if (sysTab) {
      await clickElement(sysTab, null, 600, signal)
      await sleep(1500, signal)
    }

    // 正确关闭设置弹窗
    const closeSettingsBtn = findElement('.settings-footer button, .settings-header button', '关闭') ||
      findElement('.settings-header button[aria-label="关闭设置"]')
    if (closeSettingsBtn) {
      await clickElement(closeSettingsBtn, null, 600, signal)
      await sleep(1000, signal)
    }
  }

  // 3. 完美收官
  await smoothMoveToCoords(window.innerWidth * 0.5, window.innerHeight * 0.5, 1000, signal)
  await sleep(1500, signal)
  console.log('[AutoDemo] 🎉 答辩演示录屏脚本执行完毕')
}

export function isDemoRunning() {
  return demoRunning
}

/**
 * 启动演示
 */
export async function startAstroDemo(options = { countdown: 5 }) {
  if (demoRunning) {
    stopAstroDemo()
    return
  }

  demoRunning = true
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('astro-demo-status', { detail: { running: true } }))
  }
  activeAbortController = new AbortController()
  const signal = activeAbortController.signal

  try {
    if (options.countdown && options.countdown > 0) {
      await showCountdown(options.countdown)
    }
    await executeChoreographedDemo(signal)
  } catch (err) {
    if (err.message === 'DEMO_ABORTED' || err.message === 'DEMO_CANCELLED') {
      console.log('[AutoDemo] 演示已主动终止')
    } else {
      console.error('[AutoDemo] 演播发生异常:', err)
    }
  } finally {
    demoRunning = false
    activeAbortController = null
    removeCursor()
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('astro-demo-status', { detail: { running: false } }))
    }
  }
}

/**
 * 停止演示
 */
export function stopAstroDemo() {
  if (activeAbortController) {
    activeAbortController.abort()
  }
  demoRunning = false
  removeCursor()
  if (countdownOverlayEl) {
    countdownOverlayEl.remove()
    countdownOverlayEl = null
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('astro-demo-status', { detail: { running: false } }))
  }
}

/**
 * 挂载全局全局控制与快捷键
 */
export function initPresentationDemo() {
  if (typeof window === 'undefined') return

  // 暴露给控制台直接调用
  window.startAstroDemo = startAstroDemo
  window.stopAstroDemo = stopAstroDemo
  window.isAstroDemoRunning = isDemoRunning

  // 监听键盘快捷键
  window.addEventListener('keydown', (e) => {
    // Esc: 紧急停止
    if (e.key === 'Escape' && demoRunning) {
      stopAstroDemo()
      return
    }
    // Ctrl + Shift + D 或 Alt + D: 切换演示
    if ((e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'd') || (e.altKey && e.key.toLowerCase() === 'd')) {
      e.preventDefault()
      if (demoRunning) {
        stopAstroDemo()
      } else {
        startAstroDemo({ countdown: 5 })
      }
    }
  })
}
