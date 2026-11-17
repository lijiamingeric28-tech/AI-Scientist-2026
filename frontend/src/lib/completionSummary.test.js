import test from 'node:test'
import assert from 'node:assert/strict'
import { completionSummary } from './completionSummary.js'
const stage = { properties: [{property_id:'z',name:'红移'},{property_id:'t',name:'气体温度'}], deliverySummary:{records:35,materials:21,figures:10}, recordCounts:{z:2,t:36} }
test('uses full pinned aggregates, not working counts or visible page length', () => {
  const rows=Object.assign([{field_name:'气体温度'}],{page:{},aggregates:{total:35,fields:[{property_id:'z',count:1},{property_id:'t',count:34}]}})
  const result=completionSummary(stage,{records:{status:'success',data:rows},head:{status:'success',data:{display_counts:{records:35,material_groups:17,figures:10}}}})
  assert.deepEqual(result.recordCounts,{z:1,t:34});assert.equal(result.summary.records,35);assert.equal(result.summary.materials,17)
})
test('pending or failed reads never use preliminary counts', () => {
  assert.deepEqual(completionSummary(stage).recordCounts,{})
  assert.equal(completionSummary(stage).summary.materials,null)
  assert.deepEqual(completionSummary(stage,{records:{status:'error'}}).recordCounts,{})
})
test('a pinned header supplies real zero counts without fabricated defaults', () => {
  const result=completionSummary({...stage,deliverySummary:{records:0,figures:0}}, {head:{status:'success',data:{display_counts:{records:0,material_groups:0,figures:0}}}})
  assert.equal(result.summary.records,0);assert.equal(result.summary.materials,0);assert.equal(result.summary.figures,0)
  assert.equal(completionSummary({}).summary,null)
})
test('a delivered property with no records shows zero', () => {
  assert.deepEqual(completionSummary(stage,{records:{status:'success',data:Object.assign([],{aggregates:{total:34,fields:[{property_id:'t',count:34}]}})}}).recordCounts,{z:0,t:34})
})
test('legacy full rows are supported, but a page is never treated as all rows', () => {
  const rows=[{field_name:'红移'},{field_name:'气体温度'}]
  assert.deepEqual(completionSummary(stage,{records:{status:'success',data:rows}}).recordCounts,{z:1,t:1})
  assert.deepEqual(completionSummary(stage,{records:{status:'success',data:Object.assign(rows,{page:{}})}}).recordCounts,{})
})
