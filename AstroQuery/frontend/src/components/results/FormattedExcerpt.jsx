import { useState, useMemo } from 'react'
import { Icon } from '@/components/icons'

export function parseExcerpt(rawText) {
  if (!rawText || typeof rawText !== 'string') return []

  // Un-hyphenate words broken by line break: e.g. "vi-\nsual" -> "visual"
  const cleaned = rawText.replace(/(\b[A-Za-z]+)-\s*\r?\n\s*([A-Za-z]+\b)/g, '$1$2')

  const rawLines = cleaned.split(/\r?\n/).map((l) => l.trim())
  const lines = []
  for (const l of rawLines) {
    if (l || (lines.length > 0 && lines[lines.length - 1] !== '')) {
      lines.push(l)
    }
  }

  const blocks = []
  let i = 0
  const n = lines.length

  while (i < n) {
    const line = lines[i]
    if (!line) {
      i++
      continue
    }

    // Standalone Page number / header: e.g. "515", "7", "p. 12"
    if (/^\d{1,4}$/.test(line) && (i === 0 || i === 1 || i === n - 1 || (i > 0 && lines[i - 1].length > 20))) {
      blocks.push({ type: 'page_num', value: line })
      i++
      continue
    }

    // Captions: "Table 2. ...", "Table 5. ...", "Figure 2. ..."
    const captionMatch = line.match(/^(Table|Tab\.|Figure|Fig\.|图|表)\s*(\d+[\.:]?)(.*)$/i)
    if (captionMatch) {
      const isTable = /^(t|表)/i.test(captionMatch[1])
      blocks.push({
        type: 'caption',
        kind: isTable ? 'table' : 'figure',
        prefix: `${captionMatch[1]} ${captionMatch[2]}`.trim(),
        title: captionMatch[3].trim(),
      })
      i++
      continue
    }

    // Consecutive short tokens indicating tabular cells/headers
    let shortCount = 0
    let j = i
    while (j < n && lines[j] && lines[j].length <= 25 && !/^(Table|Tab\.|Figure|Fig\.|图|表)\s*\d+/i.test(lines[j])) {
      shortCount++
      j++
    }

    if (shortCount >= 4) {
      const tableTokens = lines.slice(i, j)
      const tableStructure = tryReconstructTable(tableTokens)
      if (tableStructure) {
        blocks.push({ type: 'table', ...tableStructure })
      } else {
        blocks.push({ type: 'table_tokens', tokens: tableTokens })
      }
      i = j
      continue
    }

    // Continuous prose paragraph
    const proseLines = [line]
    i++
    while (i < n) {
      const curr = lines[i]
      if (!curr) {
        i++
        break
      }
      if (/^\d{1,4}$/.test(curr) || /^(Table|Tab\.|Figure|Fig\.|图|表)\s*\d+/i.test(curr)) {
        break
      }
      let nextShort = 0
      let k = i
      while (k < n && lines[k] && lines[k].length <= 20) {
        nextShort++
        k++
      }
      if (nextShort >= 4) {
        break
      }
      proseLines.push(curr)
      i++
    }

    blocks.push({ type: 'prose', text: proseLines.join(' ') })
  }

  return blocks
}

function tryReconstructTable(tokens) {
  if (!tokens || tokens.length < 4) return null
  const n = tokens.length

  // Strategy A: Sequential Row Numbers (1, 2, 3...)
  const idx1 = tokens.indexOf('1')
  if (idx1 > 0 && idx1 <= 15) {
    const idx2 = tokens.indexOf('2', idx1 + 1)
    if (idx2 > idx1 && idx2 - idx1 <= 16) {
      const headers = tokens.slice(0, idx1)
      const rows = []
      let expectedNum = 1
      let currentStart = idx1

      for (let i = idx1 + 1; i <= n; i++) {
        const isNextRow = (i < n && tokens[i] === String(expectedNum + 1)) || i === n
        if (isNextRow) {
          const rowSlice = tokens.slice(currentStart, i)
          while (rowSlice.length < headers.length) {
            rowSlice.push('—')
          }
          rows.push(rowSlice)
          expectedNum++
          currentStart = i
        }
      }

      if (rows.length >= 2) {
        return { headers, rows, k: headers.length }
      }
    }
  }

  // Strategy B: Repeated JD / float pattern (e.g. 6682.13, 6686.20...)
  const jdPattern = /^\d{4,5}\.\d+$/
  const jdIndices = []
  for (let i = 0; i < n; i++) {
    if (jdPattern.test(tokens[i])) jdIndices.push(i)
  }
  if (jdIndices.length >= 2) {
    const headerEnd = jdIndices[0]
    if (headerEnd > 0 && headerEnd <= 16) {
      const headers = tokens.slice(0, headerEnd)
      const rows = []
      for (let j = 0; j < jdIndices.length; j++) {
        const start = jdIndices[j]
        const end = j + 1 < jdIndices.length ? jdIndices[j + 1] : n
        const rowSlice = tokens.slice(start, end)
        while (rowSlice.length < headers.length) {
          rowSlice.push('—')
        }
        rows.push(rowSlice)
      }
      return { headers, rows, k: headers.length }
    }
  }

  // Strategy C: Fixed Column Divisibility fallback
  for (let k = 2; k <= Math.min(15, n); k++) {
    const headers = tokens.slice(0, k)
    const numNumericHeaders = headers.filter((t) => /^-?\d+(?:\.\d+)?$/.test(t)).length
    if (numNumericHeaders > Math.floor(k / 2)) continue

    if (k < n) {
      const firstCell = tokens[k]
      const isFirstCellNumeric = /^\d+(?:\.\d+)?$/.test(firstCell)
      if (isFirstCellNumeric) {
        if (2 * k < n) {
          const secondCell = tokens[2 * k]
          if (/^\d+(?:\.\d+)?$/.test(secondCell)) {
            const rows = []
            for (let r = k; r < n; r += k) {
              const rSlice = tokens.slice(r, r + k)
              while (rSlice.length < k) rSlice.push('—')
              rows.push(rSlice)
            }
            return { headers, rows, k }
          }
        } else {
          return { headers, rows: [tokens.slice(k, k + k)], k }
        }
      }
    }
  }
  return null
}

export default function FormattedExcerpt({ excerpt, role = '原文摘录', defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const [mode, setMode] = useState('formatted') // 'formatted' | 'raw'
  const [copied, setCopied] = useState(false)

  const text = typeof excerpt === 'string' ? excerpt.trim() : ''
  const blocks = useMemo(() => parseExcerpt(text), [text])
  const rawLines = useMemo(() => (text ? text.split(/\r?\n/) : []), [text])

  if (!text) return null

  const handleCopy = (e) => {
    e.stopPropagation()
    if (!navigator?.clipboard) return
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className={`formatted-excerpt-card ${open ? 'is-open' : ''}`}>
      <button
        type="button"
        className="excerpt-trigger"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <span className="excerpt-trigger-left">
          <Icon.FileText className="excerpt-icon" />
          <span className="excerpt-label">查看保存的摘录</span>
          {role && <span className="excerpt-role-pill">{role}</span>}
        </span>
        <span className="excerpt-trigger-right">
          <span className="excerpt-meta-pill">
            {rawLines.length} 行 · {text.length} 字符
          </span>
          <Icon.ChevronDown className={`excerpt-chevron ${open ? 'is-rotated' : ''}`} />
        </span>
      </button>

      {open && (
        <div className="excerpt-body-wrapper">
          <div className="excerpt-toolbar">
            <div className="excerpt-toolbar-left">
              <span className="excerpt-status-hint">
                {mode === 'formatted' ? '结构化智能排版 (已规整段落与表格)' : 'PDF 提取逐行原样 (带行号)'}
              </span>
            </div>
            <div className="excerpt-toolbar-right">
              <div className="excerpt-mode-toggle" role="group" aria-label="排版视图切换">
                <button
                  type="button"
                  className={`mode-btn ${mode === 'formatted' ? 'active' : ''}`}
                  onClick={() => setMode('formatted')}
                >
                  自然排版
                </button>
                <button
                  type="button"
                  className={`mode-btn ${mode === 'raw' ? 'active' : ''}`}
                  onClick={() => setMode('raw')}
                >
                  逐行原样
                </button>
              </div>
              <button
                type="button"
                className="excerpt-copy-btn"
                onClick={handleCopy}
                title="复制摘录文本"
              >
                {copied ? <Icon.Check className="copy-icon is-copied" /> : <Icon.Copy className="copy-icon" />}
                <span>{copied ? '已复制' : '复制'}</span>
              </button>
            </div>
          </div>

          <div className="excerpt-content-area">
            {mode === 'formatted' ? (
              <div className="excerpt-formatted-view">
                {blocks.map((block, idx) => {
                  if (block.type === 'page_num') {
                    return (
                      <div key={idx} className="excerpt-page-row">
                        <span className="excerpt-page-chip">原件第 {block.value} 页</span>
                      </div>
                    )
                  }
                  if (block.type === 'caption') {
                    return (
                      <div key={idx} className="excerpt-caption-card" data-caption-type={block.kind}>
                        <div className="caption-badge">
                          {block.kind === 'table' ? <Icon.Table /> : <Icon.FileText />}
                          <strong>{block.prefix}</strong>
                        </div>
                        <span className="caption-title">{block.title}</span>
                      </div>
                    )
                  }
                  if (block.type === 'table') {
                    return (
                      <div key={idx} className="excerpt-table-container">
                        <table className="excerpt-table">
                          <thead>
                            <tr>
                              {block.headers.map((h, hIdx) => (
                                <th key={hIdx}>{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {block.rows.map((row, rIdx) => (
                              <tr key={rIdx}>
                                {row.map((cell, cIdx) => (
                                  <td key={cIdx}>{cell}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )
                  }
                  if (block.type === 'table_tokens') {
                    return (
                      <div key={idx} className="excerpt-tokens-card">
                        <div className="tokens-grid">
                          {block.tokens.map((tok, tIdx) => (
                            <span key={tIdx} className="token-cell">
                              {tok}
                            </span>
                          ))}
                        </div>
                      </div>
                    )
                  }
                  return (
                    <p key={idx} className="excerpt-prose-para">
                      {block.text}
                    </p>
                  )
                })}
              </div>
            ) : (
              <div className="excerpt-raw-view">
                <div className="excerpt-raw-gutter">
                  {rawLines.map((_, idx) => (
                    <span key={idx} className="excerpt-gutter-num">
                      {String(idx + 1).padStart(2, '0')}
                    </span>
                  ))}
                </div>
                <div className="excerpt-raw-code">
                  {rawLines.map((line, idx) => (
                    <div key={idx} className="excerpt-raw-line">
                      {line || '\u00A0'}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
