import test from 'node:test'
import assert from 'node:assert/strict'
import { parseMeasurement, measurementGroups, modificationReport, modifiedRecordIds, executionTraces, riskMessages, exactRecordIds } from './resultData.js'

test('plain values never acquire inferred errors or lose digits', () => {
  assert.deepEqual(parseMeasurement('3641'), { value: 3641 })
  assert.deepEqual(parseMeasurement('3600'), { value: 3600 })
  assert.deepEqual(parseMeasurement('3600 ± 66'), { value: 3600, lower: 3534, upper: 3666 })
  assert.deepEqual(parseMeasurement('7.5 x10^13'), { value: 7.5e13 })
  assert.deepEqual(parseMeasurement('18–21'), { lower: 18, upper: 21, interval: true })
  assert.deepEqual(parseMeasurement('20+5−3'), { value: 20, lower: 17, upper: 25 })
  assert.deepEqual(parseMeasurement('112^{+2}_{-26}'), { value:112, lower:86, upper:114 })
  assert.equal(parseMeasurement('112^{+-2}_{-26}'), null)
  assert.equal(parseMeasurement('not numeric 3641 K'), null)
  assert.equal(parseMeasurement(''), null)
})
test('units and entities stay in separate measurement groups', () => {
  assert.deepEqual(exactRecordIds({entity_name:'A',field_name:'radius',source_ids:['s1']}), [])
  assert.deepEqual(exactRecordIds({record_ids:['r1','r2'],source_ids:['s1']}), ['r1','r2'])
  const records = [ ['A','radius','AU'], ['A','radius','Rsun'], ['B','radius','AU'] ].map(([entity_name, field_name, field_unit]) => ({ entity_name, field_name, field_unit, field_value: 1 }))
  assert.equal(measurementGroups(records).length, 3)
})
test('layered modifications and execution traces have distinct counts', () => {
  const quality = { quality_report: { report_state: { normalization: { modifications: { total: 37, details: { generated: [{ record_id: 'a', before: '3650±25', after: '3650' }] } } } }, data_state: { data_trace: Array(65).fill({ tool: 'parallel' }) }, output_state: { quality_summary: { risk_indicators: { has_unconverted_units: true, unconverted_unit_count: 2, validation_passed: false } } } } }
  assert.equal(modificationReport(quality).count, 37)
  assert.equal(executionTraces(quality).length, 65)
  assert(modifiedRecordIds(quality).has('a'))
  assert.deepEqual(riskMessages(quality), ['2 项单位未转换', '输出校验未通过'])
  assert.equal(modificationReport({ quality_report: { report_state: { normalization: { modifications: [{ record_id: 'b' }] } } } }).count, 1)
})
