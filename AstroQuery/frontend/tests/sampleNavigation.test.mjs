import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const rootDir = join(__dirname, '..')

function readFile(relPath) {
  return readFileSync(join(rootDir, relPath), 'utf8')
}

test('App.jsx provides a back-to-samples button before the task title when viewing a sample', () => {
  const appJsx = readFile('src/App.jsx')

  // handleBackToSamples is defined and resets selection and view to sample gallery
  assert.match(appJsx, /const handleBackToSamples = \(\) => \{/)
  assert.match(appJsx, /setSelectedId\(null\)/)
  assert.match(appJsx, /setView\('chat'\)/)
  assert.match(appJsx, /setMode\('sample'\)/)
  assert.match(appJsx, /setSamplesExpanded\(true\)/)

  // Renders the back button inside .task-title before the title <h1>
  assert.match(appJsx, /<div className="task-title"[^>]*>[\s\S]*back-to-samples-btn[\s\S]*<h1/i)
  assert.match(appJsx, /mode === 'sample' && selected && !helpOpen/)
  assert.match(appJsx, /aria-label="返回演示样例"/)
  assert.match(appJsx, /<Icon\.ArrowLeft/)
})

test('icons.jsx defines ArrowLeft icon for return navigation', () => {
  const icons = readFile('src/components/icons.jsx')
  assert.match(icons, /ArrowLeft:\s*\(p\)\s*=>/)
})

test('styles.css styles .back-to-samples-btn with consistent title-strong color', () => {
  const css = readFile('src/styles.css')

  assert.match(css, /\.task-title\s*\{[^}]*display:flex;[^}]*align-items:center;[^}]*gap:8px;/s)
  assert.match(css, /\.back-to-samples-btn\s*\{[^}]*color:var\(--title-strong\);/s)
  assert.match(css, /\.back-to-samples-btn:hover\s*\{[^}]*color:var\(--title-hover/s)
})
