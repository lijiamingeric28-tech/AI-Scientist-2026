import test from 'node:test'
import assert from 'node:assert/strict'
import {buildDupIndex} from './dupMarkers.js'
import {runtimeStage} from './runtimeStages.js'

test('archive folding consumes actual backend group, never equal numbers or confidence ranking', () => {
  const records=['one','two','independent'].map(record_id => ({record_id,field_value:'0.03',source_id:record_id,extraction_confidence:record_id==='two'?1:0}))
  const result=buildDupIndex(records,{archive_groups:[{group_id:'g',member_refs:[{id:'one'},{id:'two'}],display_anchor:null,
    reason:'SYNTHETIC actual same-source result evidence',evidence_refs:[]}]})
  assert.equal(result.groups.length,1)
  assert.equal(result.groups[0].rep.recordId,'one')
  assert.equal(result.byRecordId.independent,undefined)
  assert.equal(result.groups[0].archive,true)
  assert.deepEqual(result.groups[0].recordIds,['one','two'])
})

test('disabled insight stage is explicit skipped scope, not failure or generated work', () => {
  const result=runtimeStage({id:'insight'},{jobs:[],status:'not_run',scope:'disabled_pending_content'},{lifecycle:'completed'})
  assert.equal(result.status,'skipped')
  assert.match(result.summary,/未启用/)
  assert.equal(result.agents.length,0)
})
