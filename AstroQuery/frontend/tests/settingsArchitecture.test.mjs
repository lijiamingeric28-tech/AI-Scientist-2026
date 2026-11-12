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

test('SettingsDialog organizes all sections into 5 clean non-overlapping tabs with unified row layout', () => {
  const dialog = readFile('src/components/settings/SettingsDialog.jsx')
  const emojiRegex = /[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u
  assert.ok(!emojiRegex.test(dialog), 'SettingsDialog.jsx must strictly contain NO emojis')

  for (const tabKey of ['preferences', 'theme', 'connections', 'knowledge', 'system']) {
    assert.match(dialog, new RegExp(`'${tabKey}'`), `SettingsDialog defines tab ${tabKey}`)
  }

  // No duplicate theme toggle inside preferences tab
  assert.doesNotMatch(dialog, /aria-label="界面主题"/)
  // Uses unified config row & intro markup
  assert.match(dialog, /settings-panel-intro/)
  assert.match(dialog, /settings-config-section/)
  assert.match(dialog, /settings-config-row/)
  // Launches SettingsKnowledgeStudio
  assert.match(dialog, /<SettingsKnowledgeStudio/)
})

test('LibraryStatus upgrades corpus status to unified rows and provides Knowledge Studio launcher', () => {
  const lib = readFile('src/components/settings/LibraryStatus.jsx')
  assert.match(lib, /settings-config-section/)
  assert.match(lib, /settings-config-row/)
  assert.match(lib, /settings-knowledge-launcher/)
  assert.match(lib, /onLaunchStudio\?\.\('graph'\)/)
  assert.match(lib, /onLaunchStudio\?\.\('matrix'\)/)
})

test('SettingsKnowledgeStudio provides return-to-settings and large workspace modal framing', () => {
  const studio = readFile('src/components/settings/SettingsKnowledgeStudio.jsx')
  assert.match(studio, /settings-studio-dialog/)
  assert.match(studio, /返回设置/)
  assert.match(studio, /initialMode=\{initialMode\}/)
})

test('Sidebar triggers unified 系统设置 and App.jsx hides knowledge tab from task/home navigation', () => {
  const sidebar = readFile('src/components/layout/Sidebar.jsx')
  const app = readFile('src/App.jsx')

  assert.match(sidebar, /<span>系统设置<\/span>/)
  assert.match(app, /\['chat',\s*'对话'/)
  assert.match(app, /\['data',\s*'数据结果'/)
  assert.match(app, /\['workflow',\s*'执行明细'/)
  assert.doesNotMatch(app, /\['knowledge'/)
})
