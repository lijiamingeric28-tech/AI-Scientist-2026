import test from 'node:test'
import assert from 'node:assert/strict'
const module=await import('../src/lib/resultDetails.js').catch(()=>({}))
test('record navigation reuses only a record from the exact task, delivery and revision',()=>{
  assert.equal(typeof module.scopedRecordReference,'function')
  const scope={taskId:'t',deliveryId:'d',revision:7}
  const correct={record_id:'same-id',task_id:'t',delivery_id:'d',delivery_revision:7,field_value:'old',details_loaded:true}
  const current={...correct,delivery_revision:8,field_value:'new'}
  assert.equal(module.scopedRecordReference([current,correct],'same-id',scope),correct)
  for(const candidate of [current,{...correct,task_id:'other'},{...correct,delivery_id:'other'},{...correct,task_id:undefined}]){
    assert.deepEqual(module.scopedRecordReference([candidate],'same-id',scope),{record_id:'same-id',task_id:'t',delivery_id:'d',delivery_revision:7,details_loaded:false})
  }
})
test('drawer related caches are available only in the exact historical task, delivery and revision',()=>{
  assert.equal(typeof module.scopedDrawerResources,'function')
  const scope={taskId:'t',deliveryId:'d',revision:7}
  const resources=Object.fromEntries(['records','sources','materials','quality','figures'].map(key=>[key,{data:`${key}-old` }]))
  const data={taskId:'t',deliveryId:'d',deliveryRevision:7,resources}
  assert.equal(module.scopedDrawerResources(data,scope),resources)
  for(const other of [{...data,taskId:'other'},{...data,deliveryId:'other'},{...data,deliveryRevision:8}])assert.deepEqual(module.scopedDrawerResources(other,scope),{})
})

test('drawer cannot reuse unrestricted same-revision caches under a replay cutoff',()=>{
 const resources={sources:{data:[{source_id:'later'}]}}
 const data={taskId:'t',deliveryId:'d',deliveryRevision:7,resources}
 assert.deepEqual(module.scopedDrawerResources(data,{taskId:'t',deliveryId:'d',revision:7,atSeq:37,sealedOnly:true}),{})
 assert.equal(module.scopedDrawerResources({...data,atSeq:37,sealedOnly:true},{taskId:'t',deliveryId:'d',revision:7,atSeq:37,sealedOnly:true}),resources)
})
