import test from 'node:test'
import assert from 'node:assert/strict'
import { matchesRecordSearch } from './recordSearch.js'

const record = { entity_name: 'Betelgeuse', field_name: 'teff', field_value: 0, field_unit: 'K', source_id: '2007A&A...474..599P', extraction_method: 'vlm_text' }
const source = { source_id: record.source_id, title: 'The molecular and dusty composition', journal: 'Astronomy and Astrophysics', year: 2007 }
const label = field => field === 'teff' ? '有效温度' : field
test('record search matches visible property and source labels as well as exact identifiers', () => {
  for (const query of ['有效温度', 'teff', 'Betelgeuse', 'dusty composition', 'A&A 2007', 'Astronomy and Astrophysics', record.source_id, 'VLM 文本', '0', 'K']) {
    assert.equal(matchesRecordSearch(record, query, source, label), true, query)
  }
  assert.equal(matchesRecordSearch(record, '半径', source, label), false)
})
test('search preserves unknown names, missing sources, zero values and empty queries', () => {
  const unknown = { entity_name: 'M45', field_name: 'custom_field', field_value: 0, field_unit: 'custom_unit', source_id: 'new_source', extraction_method: 'new_method' }
  for (const query of ['custom_field', 'custom_unit', 'new_source', 'new_method', '0', '  ']) assert.equal(matchesRecordSearch(unknown, query), true, query)
  assert.equal(matchesRecordSearch(unknown, 'undefined'), false)
})
