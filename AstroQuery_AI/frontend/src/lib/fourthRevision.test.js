import test from 'node:test'
import assert from 'node:assert/strict'
import { reportParagraphs, operationLabel, modificationView, recordChanges, sourceExplanation, isDatabaseRecord, SOURCE_TYPES, sourceType, extractionLabel } from './readableData.js'
import { intervalSeconds, stageSeconds, taskSeconds, timingEvent } from './executionFacts.js'
import { parseMeasurement } from './resultData.js'
import { createPropertyLabel } from './propertyLabel.js'

test('public source and record model variants preserve database and supplement provenance', () => {
  assert.equal(SOURCE_TYPES.supplement, SOURCE_TYPES.supplementary)
  assert.equal(sourceType('supplementary'), 'supplement')
  assert.equal(extractionLabel('vlm_pdf'), 'VLM PDF')
  assert.equal(extractionLabel('vlm_figure'), 'VLM 图像')
  assert.equal(extractionLabel('vlm_future_method'), 'vlm_future_method')
  assert.equal(extractionLabel('database_query'), '数据库查询')
  for (const extraction_method of ['database', 'database_query']) assert.equal(isDatabaseRecord({ extraction_method }), true)
  assert.equal(isDatabaseRecord({}, { source_type:'db' }), true)
  assert.equal(operationLabel('future_unit_tool'), 'future_unit_tool')
  assert.equal(modificationView({ stage:'LegacyStage', original_value:0, new_value:1, from_unit:'mas', to_unit:'pc' }).before, '0 mas')
  assert.equal(modificationView({ original:{field_value:0,field_unit:'K'}, new:{field_value:1,field_unit:'K'} }).after, '1 K')
  assert.deepEqual(reportParagraphs({ observation:'Observation', interpretation:'Interpretation', debug:{raw:1} }), ['Observation','Interpretation'])
  assert.deepEqual(reportParagraphs({unexpected:{secret:1}}), [])
  assert.ok(sourceExplanation({}, 'Normalization affects the observation in this source.').impacts.includes('Normalization affects the observation in this source.'))
  assert.equal(sourceExplanation({ conflict_risk:{conflicts:[{record_id:'r1'}]} }).impacts.length, 1)
  assert.equal(parseMeasurement(0).value, 0)
  assert.equal(parseMeasurement('0 ± 0.1').lower, -0.1)
  assert.equal(parseMeasurement('unsupported numeric formula'), null)
  for (const value of ['1e999', '1e999 ± 2', '1 ± 1e999', '1e999 + 2 - 1']) assert.equal(parseMeasurement(value), null)
  const label = createPropertyLabel([{property_id:'new_scientific_field',name_cn:'本次定义'}])
  assert.equal(label('new_scientific_field'),'本次定义')
  assert.equal(label('new_scientific_field_alias'),'new_scientific_field_alias')
})

test('record history keeps rounds and exact associations, merges producer trace copies one to one', () => {
  const base = {record_id:'r1',tool:'numeric_convert',before:'0',after:0,reason:'parsed'}
  const traces = [{...base,timestamp:'2026-01-01',iteration:1},{...base,timestamp:'2026-01-02',iteration:2},{record_id:'r2',tool:'trim',before:' 2',after:'2'}]
  const quality = {quality_report:{data_state:{data_trace:traces},output_state:{traceability:{per_record_trace:{r1:{original_value:'0',original_unit:'mas',modifications:traces.slice(0,2).map(({tool,...row})=>({...row,stage:tool}))}}}},report_state:{normalization:{modifications:[{source_id:'s1',tool:'not_record_specific'},{record_id:'r1',tool:'new_tool',original_value:0,new_value:1,timestamp:'2026-01-03'}]}}}}
  const result = recordChanges({record_id:'r1',source_id:'s1'}, quality)
  assert.equal(result.rows.length, 3)
  assert.equal(result.rows[0].iteration, 1)
  assert.equal(result.rows[1].iteration, 2)
  assert.equal(modificationView(result.rows[2]).operation,'new_tool')
  assert.equal(result.trace.original_value,'0')
  assert.equal(recordChanges({record_id:'unknown',source_id:'s1'},quality).rows.length,0)
})

test('whole-task timing unions parallel intervals and excludes quality wrapper time', () => {
  assert.equal(intervalSeconds([[0,10],[5,15],[20,25]]),20)
  const events = [{type:'stage_completed',stage_id:'quality_check',duration:100,ts:100}, {type:'agent_completed',stage_id:'quality_check',duration:10,ts:20},{type:'agent_completed',stage_id:'quality_check',duration:10,ts:25}]
  assert.equal(stageSeconds(events,'quality_check'),15)
  assert.equal(stageSeconds([{type:'agent_completed',stage_id:'clean',duration:0,ts:30}],'clean'),0)
  assert.equal(stageSeconds([{type:'agent_completed',stage_id:'clean',duration:10}],'clean'),null)
  assert.equal(stageSeconds([{type:'stage_completed',stage_id:'retrieve',duration:5}],'retrieve'),5)
  assert.equal(timingEvent({type:'agent_completed',stage_id:'deliver',agent:'SynthesisAgent'}).stage_id,'insight')
  assert.equal(taskSeconds([{type:'task_started',ts:10},{type:'task_completed',ts:110}],{status:'completed'}).seconds,100)
  assert.equal(taskSeconds([],{status:'completed'}).seconds,null)
})
