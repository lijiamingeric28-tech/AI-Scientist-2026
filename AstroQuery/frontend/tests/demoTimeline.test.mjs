import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {subtitles,stamp} from '../../tools/demo/timeline.mjs'
const shots=JSON.parse(fs.readFileSync(new URL('../../tools/demo/shots.json',import.meta.url)))
test('complete and short edits retain every chapter within approved durations',()=>{
 assert.equal(shots.reduce((n,s)=>n+s.seconds,0),180)
 assert.equal(shots.reduce((n,s)=>n+s.edit,0),86)
 assert.equal(new Set(shots.map(s=>s.id)).size,13)
 assert.equal(shots.find(s=>s.id==='followup').edit,19)
 assert.ok(shots.every(s=>s.seconds>=s.edit&&s.edit>0))
 const srt=subtitles(shots)
 assert.ok(srt.includes('00:02:53,000 --> 00:03:00,000'))
 assert.equal(stamp(86),'00:01:26,000')
})

test('V2 allocates reading time to content instead of padding the chapter tail',()=>{
 for(const shot of shots){
  assert.ok(Object.keys(shot.beats||{}).length>0,shot.id)
  assert.ok(Object.values(shot.beats).every(seconds=>seconds>0),shot.id)
  assert.ok(Object.values(shot.beats).reduce((sum,n)=>sum+n,0)<=shot.seconds,shot.id)
 }
 assert.ok(shots.find(s=>s.id==='material').beats.main>=6)
 assert.ok(shots.find(s=>s.id==='followup').beats.table>=4)
 assert.ok(shots.find(s=>s.id==='replay').beats.firstReview>=7)
 assert.ok(shots.find(s=>s.id==='theme').seconds<shots.find(s=>s.id==='material').seconds)
})
