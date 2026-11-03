import { test } from 'node:test'
import assert from 'node:assert/strict'
import { papersValue, preferencesFromConfig, ADS_SORTS } from './retrievalPreferences.js'
test('custom targets keep valid values above twenty and reject malformed counts',()=>{
  for(const n of [1,10,15,20,30,40]) assert.equal(papersValue(n),n)
  for(const n of ['',0,-1,41,2.5,'1e1',true]) assert.equal(papersValue(n),null)
})
test('the form reads effective user defaults with the historical fallback',()=>{
  assert.deepEqual(preferencesFromConfig(null),{papers_per_property:20,ads_sort:'score desc'})
  assert.deepEqual(preferencesFromConfig({effective_values:{literature_papers_per_property:'15',ads_sort:'date desc'}}),{papers_per_property:15,ads_sort:'date desc'})
  assert.equal(ADS_SORTS.length,4)
})
