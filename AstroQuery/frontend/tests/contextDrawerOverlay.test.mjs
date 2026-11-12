import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const rootDir = join(__dirname, '..')

function readFile(relPath) {
  return readFileSync(join(rootDir, relPath), 'utf8')
}

test('ContextDrawer always renders as a top-layer overlay with focus trap and resize width', () => {
  const drawer = readFile('src/components/layout/ContextDrawer.jsx')

  assert.doesNotMatch(drawer, /\bdocked\b/)
  assert.doesNotMatch(drawer, /research-docked/)
  assert.doesNotMatch(drawer, /useMediaQuery/)
  assert.match(drawer, /useDialogFocus\(!!detail,\s*dismissal\.close,\s*\{\s*trap:\s*true\s*\}\)/)
  assert.match(drawer, /<div className="context-backdrop"/)
  assert.match(drawer, /aria-modal="true"/)
  assert.match(drawer, /className="context-drawer animate-drawer-in overlay"/)
  assert.match(drawer, /style=\{\{\s*width\s*\}\}/)
})

test('App mounts ContextDrawer outside .task-workspace as an .app-shell overlay sibling', () => {
  const app = readFile('src/App.jsx')

  assert.match(
    app,
    /<\/main>\s*<\/div>\s*\{detail && <ViewContent[^>]*><ContextDrawer\b/,
  )
})

test('Overlay drawer and backdrop sit above workspace/sidebar layers without locking desktop width', () => {
  for (const cssPath of ['src/styles.css', 'src/frontend-v1.css']) {
    const css = readFile(cssPath)
    assert.match(css, /\.context-backdrop\s*\{[^}]*z-index:\s*85\s*!important;/s)
    assert.match(css, /\.context-drawer\.overlay\s*\{[^}]*z-index:\s*90\s*!important;/s)
    const blocks = [...css.matchAll(/(?:^|\n)\.context-drawer\.overlay\s*\{[^}]*\}/g)].map(m => m[0])
    assert.ok(blocks.length > 0, `${cssPath} defines .context-drawer.overlay`)
    assert.match(blocks.at(-1), /max-width:\s*calc\(100vw\s*-\s*24px\)/)
    for (const block of blocks) {
      assert.doesNotMatch(block, /width:\s*min\([^)]+\)\s*!important/)
    }
  }

  const resultsCss = readFile('src/research-results.css')
  assert.match(resultsCss, /\.context-backdrop\s*\{[^}]*z-index:\s*85\s*!important;/s)
})
