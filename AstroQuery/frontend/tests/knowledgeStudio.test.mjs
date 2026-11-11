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

test('icons.jsx defines all required vector icons for Knowledge Studio without emojis', () => {
  const icons = readFile('src/components/icons.jsx')
  const requiredIcons = [
    'Network',
    'Star',
    'StarFilled',
    'Edit',
    'Plus',
    'Trash',
    'Fork',
    'Grid',
    'Sliders',
    'ZoomIn',
    'ZoomOut',
    'FitScreen',
    'Atom',
  ]
  for (const name of requiredIcons) {
    assert.match(
      icons,
      new RegExp(`${name}:\\s*\\(p\\)\\s*=>`),
      `Icon.${name} must be defined in icons.jsx`
    )
  }
})

test('api.js exports all required knowledge endpoints', () => {
  const api = readFile('src/services/api.js')
  const requiredEndpoints = [
    'getKnowledge',
    'getKnowledgeItem',
    'createKnowledge',
    'updateKnowledge',
    'deleteKnowledge',
    'setKnowledgePreference',
    'getKnowledgeGraph',
  ]
  for (const ep of requiredEndpoints) {
    assert.match(
      api,
      new RegExp(`export\\s+const\\s+${ep}\\s*=`),
      `api.js must export ${ep}`
    )
  }
})

test('App.jsx provides the 4th top-level navigation tab: knowledge', () => {
  const appJsx = readFile('src/App.jsx')
  assert.match(appJsx, /const KnowledgeWorkspace = lazy\(/)
  assert.match(appJsx, /\['knowledge',\s*'知识图谱与理论库'/)
  assert.match(appJsx, /paneProps\('knowledge',/)
  assert.match(appJsx, /<KnowledgeWorkspace/)
})

test('KnowledgeWorkspace and components exist and have no emojis in JSX', () => {
  const files = [
    'src/components/knowledge/KnowledgeWorkspace.jsx',
    'src/components/knowledge/KnowledgeGraphView.jsx',
    'src/components/knowledge/KnowledgeListView.jsx',
    'src/components/knowledge/KnowledgeDrawer.jsx',
    'src/components/knowledge/KnowledgeEditorModal.jsx',
    'src/components/knowledge/knowledgeConstants.js',
    'src/components/knowledge/knowledge.css',
  ]
  const emojiRegex = /[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u

  for (const rel of files) {
    assert.ok(existsSync(join(rootDir, rel)), `${rel} must exist`)
    const content = readFile(rel)
    assert.ok(!emojiRegex.test(content), `${rel} must strictly contain NO emojis`)
  }
})

test('knowledgeConstants exports Chinese property & edge translation helpers', async () => {
  const { translateProperty, translateEdgeLabel, isValidFormula } = await import(
    '../src/components/knowledge/knowledgeConstants.js'
  )
  assert.equal(translateProperty('flux_density'), '流量密度')
  assert.equal(translateProperty('prop_luminosity'), '光度 (Luminosity)')
  assert.equal(translateProperty('w1_mag'), 'W1 波段星等')
  assert.equal(translateEdgeLabel('关联Luminosity'), '关联光度')
  assert.equal(isValidFormula('L = 4πR^2 σ T^4'), true)
  assert.equal(isValidFormula('电子简并压支撑白矮星的极限质量'), false)
})

test('KnowledgeDetail.jsx contains in-situ actions for preference and edit/fork without emojis', () => {
  const detail = readFile('src/components/results/KnowledgeDetail.jsx')
  const emojiRegex = /[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u
  assert.ok(!emojiRegex.test(detail), 'KnowledgeDetail.jsx must strictly contain NO emojis')
  assert.match(detail, /setKnowledgePreference/)
  assert.match(detail, /设为科研优选/)
  assert.match(detail, /编辑\/派生该理论/)
})
