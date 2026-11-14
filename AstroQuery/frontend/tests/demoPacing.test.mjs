import test from 'node:test'
import assert from 'node:assert/strict'
import {createReviewPacing,needsNavigation,pointerMotion} from '../../tools/demo/pacing.mjs'
import {continueHistoricalReview} from '../../tools/demo/scenes.mjs'

test('a saved review is submitted once, with only the first review given a reading pause',()=>{
 const pacing=createReviewPacing()
 assert.deepEqual(pacing.claim('review-a:1:seq1'),{first:true,readSeconds:8,choiceSeconds:2})
 assert.equal(pacing.claim('review-a:1:seq1'),null)
 assert.deepEqual(pacing.claim('review-b:1:seq2'),{first:false,readSeconds:.25,choiceSeconds:0})
 assert.equal(pacing.claim('review-b:1:seq2'),null)
 // A new revision of the same review remains a different historical question.
 assert.equal(pacing.claim('review-a:2:seq3').first,false)
 assert.equal(pacing.count,3)
 assert.throws(()=>pacing.claim(''),/identity/)
})

test('already selected navigation is not clicked, while meaningful back-to-directory action is',()=>{
 assert.equal(needsNavigation({current:'page'}),false)
 assert.equal(needsNavigation({selected:'true'}),false)
 assert.equal(needsNavigation({pressed:'true'}),false)
 assert.equal(needsNavigation({active:true}),false)
 assert.equal(needsNavigation({current:null,active:false}),true)
 assert.equal(needsNavigation({current:'page',returnToDirectory:true}),true)
})

test('pointer motion has a bounded readable duration and arrives at the requested hotspot',()=>{
 const motion=pointerMotion({x:0,y:0},{x:800,y:300})
 assert.ok(motion.length>=12)
 assert.deepEqual(motion.at(-1),{x:800,y:300})
 assert.deepEqual(pointerMotion({x:12,y:34},{x:12,y:34}).at(-1),{x:12,y:34})
 assert.ok(motion.every(p=>p.x>=0&&p.x<=800&&p.y>=0&&p.y<=300))
})

test('first historical review reads evidence and the saved choice before submitting; later reviews do not repeat that tour',async()=>{
 const events=[],evidence={kind:'evidence'},choice={kind:'saved choice'},button={click:async()=>events.push('submit')}
 const review={locator:()=>({first:()=>evidence}),getByRole:()=>choice}
 const deps={review,button,read:async(name,node)=>events.push([name,node?.kind]),click:async target=>target.click(),pause:async ms=>events.push(['wait',ms])}
 await continueHistoricalReview({...deps,policy:{first:true,readSeconds:8,choiceSeconds:2}})
 assert.deepEqual(events,[['firstReview','evidence'],['reviewChoice','saved choice'],'submit',['reviewReceipt',undefined]])
 events.length=0
 await continueHistoricalReview({...deps,policy:{first:false,readSeconds:.25,choiceSeconds:0}})
 assert.deepEqual(events,[['wait',250],'submit'])
})
