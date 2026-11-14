import test from 'node:test'
import assert from 'node:assert/strict'
import { resultSection, primaryReading, citationItems, uniqueParagraphs, analysisVersion } from '../src/lib/readingLayers.js'

test('default is data and old coverage bookmarks remain quality audits',()=>{
 assert.equal(resultSection(), 'details')
 assert.equal(resultSection('insights'), 'details')
 assert.equal(resultSection('comparison'), 'comparison')
 assert.equal(resultSection('property-comparison'), 'property-comparison')
})
test('a usable saved supplement replaces the original summary as the primary text',()=>{
 const report={sections:{found:[{text:'saved observation'}]}}
 assert.equal(primaryReading(report,{text:'original'}).report,report)
 assert.equal(primaryReading({sections:{found:[]}},{text:'original'}).text,'original')
 assert.deepEqual(uniqueParagraphs([{text:'one'},{text:'one'},{text:'two'}]).map(p=>p.text),['one','two'])
})
test('citations include only explicit claims and preserve different fragments of one entry',()=>{
 const blocks=[{entry_id:'a',title:'Frozen A',claim:{claim_id:'c1'}},{entry_id:'a',claim:{claim_id:'c2'}},{entry_id:'b',claim:{claim_id:'background'}}]
 const result=citationItems({claim_ids:['c1','c2','absent'],measurement_ids:['m','m']},blocks)
 assert.equal(result.length,2)
 assert.deepEqual(result[0].blocks.map(b=>b.claim.claim_id),['c1','c2'])
 assert.equal(result[1].id,'m')
 assert.deepEqual(citationItems({},blocks),[])
})

test('explicit report versions belong to their full reading scope',()=>{
 assert.equal(analysisVersion({'scope-a':'2'},'scope-b'),'')
 assert.equal(analysisVersion({'scope-a':'2'},'scope-a'),'2')
})

test('identical paragraphs merge their actual citations without mutating saved rows',()=>{
 const rows=[{text:'same',claim_ids:['a'],measurement_ids:['m']},{text:'same',claim_ids:['b'],measurement_ids:['n']}]
 const before=JSON.stringify(rows)
 const merged=uniqueParagraphs(rows)
 assert.deepEqual(merged[0].claim_ids,['a','b']);assert.deepEqual(merged[0].measurement_ids,['m','n'])
 assert.equal(JSON.stringify(rows),before)
})
