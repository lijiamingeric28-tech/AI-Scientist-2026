import test from 'node:test'
import assert from 'node:assert/strict'
test('editor explicitly requests full capabilities only on demand and caches its exact version',async()=>{
  const {readRegistryEditorCatalog,createRegistryReadCache}=await import('../src/lib/registryWorkbench.js')
  const calls=[],api={summary:async filters=>{calls.push(filters);return {capabilities:{}}}},cache=createRegistryReadCache()
  await readRegistryEditorCatalog(api,cache,{release_id:'R',keyword:'ignored'})
  await readRegistryEditorCatalog(api,cache,{release_id:'R'})
  assert.deepEqual(calls,[{release_id:'R',projection:'full'}])
})
test('version directories can request lightweight metadata without changing default callers',async()=>{
  const {createRegistryApi}=await import('../src/services/registryApi.js')
  const calls=[],signal=new AbortController().signal,api=createRegistryApi(async(path,options)=>{calls.push({path,options});return {items:[]}})
  await api.workspaces({projection:'directory',signal});await api.releases({projection:'directory',signal});await api.workspaces({signal})
  assert.deepEqual(calls.map(x=>x.path),['/registry-workbench/workspaces?projection=directory','/registry-workbench/releases?projection=directory','/registry-workbench/workspaces'])
  assert.equal(calls[0].options.signal,signal);assert.equal(calls[0].options.projection,undefined)
})
