/* P1-6：展示数值/坐标格式化工具（只格式化"展示性"数值，ID/来源编号原样保留）
 *
 * - fmtRaDec / fmtRa / fmtDec：度 → 时角/度分秒制（天文标准）
 *   RA 88.79293899077537 → RA 05:55:10.29 · Dec +07:24:25.4
 * - fmtNum：保留 digits 位小数并去尾 0（分数/置信度等展示数值）
 * - fmtPair：before → after 展示串（traces / RecordDetail 复用）
 */

export function fmtRa(ra) {
  const n = Number(ra)
  if (!Number.isFinite(n) || n < 0) return null
  // 度 → 时角：1 小时 = 15 度
  const h = n / 15
  const hh = Math.floor(h)
  const m = (h - hh) * 60
  const mm = Math.floor(m)
  const ss = (m - mm) * 60
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:${ss.toFixed(2).padStart(5, '0')}`
}

export function fmtDec(dec) {
  const n = Number(dec)
  if (!Number.isFinite(n)) return null
  const sign = n >= 0 ? '+' : '-'
  const a = Math.abs(n)
  const dd = Math.floor(a)
  const m = (a - dd) * 60
  const mm = Math.floor(m)
  const ss = (m - mm) * 60
  return `${sign}${String(dd).padStart(2, '0')}:${String(mm).padStart(2, '0')}:${ss.toFixed(1).padStart(4, '0')}`
}

export function fmtRaDec(ra, dec) {
  const raStr = fmtRa(ra)
  const decStr = fmtDec(dec)
  if (!raStr && !decStr) return null
  return `RA ${raStr || '—'} · Dec ${decStr || '—'}`
}

/* 耗时统一一位小数（P1-8：卡头/Agent 全站一致；<0.05s 显示 <0.1s 避免 0.0s）
 * 兼容数字与已带 "s" 的字符串（后端 round(duration,2) 的历史数据） */
export function fmtDuration(v) {
  if (v == null || v === '') return null
  const n = typeof v === 'number' ? v : parseFloat(String(v).replace(/s$/, ''))
  if (!Number.isFinite(n)) return String(v)
  if (n < 0.05) return '<0.1s'
  return `${n.toFixed(1)}s`
}

export function fmtNum(v, digits = 2) {
  const n = Number(v)
  if (!Number.isFinite(n)) return v == null ? '' : String(v)
  return n.toFixed(digits).replace(/\.?0+$/, '')
}

export function fmtPair(before, after) {
  const b = before === undefined || before === null ? '—' : String(before)
  const a = after === undefined || after === null ? '—' : String(after)
  return `${b} → ${a}`
}

/* 历史澄清原文的 CLI 骨架清洗：过滤 ==== 分隔线与"您的选择/请输入 (y/m/n)"
 * 交互行，保留信息内容（旧事件无 fields 字段时 question 是后端 CLI 风格文本） */
export function cleanCliQuestion(q) {
  if (!q) return q
  return q
    .split('\n')
    .filter((line) => !/^[=_-]{4,}$/.test(line.trim()))
    .filter((line) => !/^(您的选择|请输入\s*[（(]?y\/m\/n[）)]?|请选择)[：:]?\s*$/.test(line.trim()))
    .join('\n')
    .trim()
}
