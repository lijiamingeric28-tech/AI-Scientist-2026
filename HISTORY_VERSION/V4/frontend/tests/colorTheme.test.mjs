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

test('styles.css defines customized progress, running dot, and log level colors', () => {
  const css = readFile('src/styles.css')

  // Blue text: #2F6FA7
  assert.match(css, /--status-progress:\s*#2F6FA7;/i)

  // Breathing dot deep color: #5097B1
  assert.match(css, /--status-running:\s*#5097B1;/i)
  assert.match(css, /\.animate-pulse-dot\s*\{[^}]*color:\s*var\(--status-running,\s*#5097B1\);/s)

  // Progress bar fill: #A8C1D9; Progress track & border: #D2E2F2
  assert.match(css, /--progress-border:\s*#D2E2F2;/i)
  assert.match(css, /--progress-bar:\s*#A8C1D9;/i)
  assert.match(css, /--progress-track:\s*#D2E2F2;/i)

  // Real-time log level colors
  assert.match(css, /--log-info-bg:\s*#B6D2E8;/i)
  assert.match(css, /--log-warn-bg:\s*#FDEB9C;/i)
  assert.match(css, /--log-error-bg:\s*#F8C4C4;/i)

  // Active filter chip styles for log levels
  assert.match(css, /\.log-chip\.chip-info\.active/)
  assert.match(css, /\.log-chip\.chip-warn\.active/)
  assert.match(css, /\.log-chip\.chip-error\.active/)
})

test('StageCard, ClarificationCard, and StageDetailPanel use customized tokens for progress and dots', () => {
  const stageCard = readFile('src/components/chat/StageCard.jsx')
  const clarCard = readFile('src/components/chat/ClarificationCard.jsx')
  const detailPanel = readFile('src/components/workflow/StageDetailPanel.jsx')
  const statusFile = readFile('src/components/status.jsx')

  // Running StageCard border uses #D2E2F2
  assert.match(stageCard, /stage\.status === 'running'\s*\?\s*'var\(--progress-border,\s*#D2E2F2\)'/)

  // ClarificationCard border uses #D2E2F2 and pulse dot uses #5097B1
  assert.match(clarCard, /border:\s*'1px solid var\(--progress-border,\s*#D2E2F2\)'/)
  assert.match(clarCard, /animate-pulse-dot[^>]*var\(--status-running,\s*#5097B1\)/)

  // ProgressBar track uses #D2E2F2 and fill uses #A8C1D9
  assert.match(stageCard, /background:\s*'var\(--progress-track,\s*#D2E2F2\)'/)
  assert.match(stageCard, /background:\s*done\s*\?\s*'var\(--status-success\)'\s*:\s*'var\(--progress-bar,\s*#A8C1D9\)'/)

  // StageDetailPanel progress track uses #D2E2F2 and fill uses #A8C1D9
  assert.match(detailPanel, /background:\s*'var\(--progress-track,\s*#D2E2F2\)'/)
  assert.match(detailPanel, /background:\s*step\.status === 'completed'\s*\?\s*'var\(--status-success\)'\s*:\s*'var\(--progress-bar,\s*#A8C1D9\)'/)

  // STATUS_COLORS in status.jsx uses #5097B1 for running dots
  assert.match(statusFile, /running:\s*'var\(--status-running,\s*#5097B1\)'/)
})

test('LogLine and LogDrawer display distinct INFO, WARN, and ERROR colors', () => {
  const logLine = readFile('src/components/log/LogLine.jsx')
  const logDrawer = readFile('src/components/log/LogDrawer.jsx')

  // LogLine level mapping
  assert.match(logLine, /INFO:\s*\{[^}]*#B6D2E8/)
  assert.match(logLine, /WARN:\s*\{[^}]*#FDEB9C/)
  assert.match(logLine, /WARNING:\s*\{[^}]*#FDEB9C/)
  assert.match(logLine, /ERROR:\s*\{[^}]*#F8C4C4/)

  // LogDrawer level normalization
  assert.match(logDrawer, /normLevel/)
  assert.match(logDrawer, /chip-\$\{lv\.toLowerCase\(\)\}/)
})
