import React, { useMemo } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'

export function renderMath(input, displayMode) {
  if (typeof input !== 'string') return null
  const raw = input.trim()
  const delimiters = [['$$', '$$'], ['\\[', '\\]'], ['\\(', '\\)'], ['$', '$']]
  const pair = delimiters.find(([start, end]) => raw.length > start.length + end.length && raw.startsWith(start) && raw.endsWith(end))
  const expression = pair ? raw.slice(pair[0].length, -pair[1].length).trim() : raw
  if (!expression) return null
  try {
    return katex.renderToString(expression, {
      displayMode, trust: false, throwOnError: true, maxExpand: 500, maxSize: 18, output: 'htmlAndMathml',
    })
  } catch {
    return null
  }
}

export function LatexMath({ math, formula, displayMode = false, className = '' }) {
  const input = math || formula
  const html = useMemo(() => renderMath(input, displayMode), [input, displayMode])
  if (typeof input !== 'string' || !input) return null
  const Element = displayMode ? 'div' : 'span'
  const styles = 'latex-math-container ' + (displayMode ? 'is-display ' : 'is-inline ') + className
  return html ? <Element className={styles} dangerouslySetInnerHTML={{ __html: html }} /> :
    <Element className={styles}><code className="katex-fallback">{input}</code></Element>
}

export function LatexText({ text, className = '' }) {
  if (typeof text !== 'string' || !text) return null
  const hasDelimiters = /(\$|\\\(|\\\[)/.test(text)
  if (!hasDelimiters && !/\\[a-zA-Z]+|[a-zA-Z0-9][_^][{0-9]/.test(text)) {
    return <span className={className}>{text}</span>
  }
  if (!hasDelimiters) {
    // Only render the full string in KaTeX when it is concise pure math without Chinese prose or newlines
    const hasChineseOrMultiline = /[\u4e00-\u9fa5\n]/.test(text)
    if (!hasChineseOrMultiline && text.length <= 100) {
      return <LatexMath math={text} className={className} />
    }
    // Extract bare math tokens inside mixed prose so Chinese paragraphs wrap naturally
    const inlineParts = text.split(/(\\[a-zA-Z]+(?:\{[^}]*\})?|[A-Za-z0-9\u0370-\u03FF]+(?:\^(?:\{[^}]+\}|[0-9+\-]+)|_(?:\{[^}]+\}|[0-9]+))+)/g)
    return (
      <span className={className}>
        {inlineParts.map((part, i) =>
          i % 2 ? <LatexMath math={part} key={i} /> : part
        )}
      </span>
    )
  }
  const pieces = text.split(/(\$\$[\s\S]+?\$\$|\$[^$\n]+\$|\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\])/g)
  return <span className={className}>{pieces.map((piece, i) =>
    i % 2 ? <LatexMath math={piece} key={i} /> : piece,
  )}</span>
}

export default LatexMath
