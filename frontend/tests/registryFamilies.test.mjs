import test from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {createServer} from 'vite'

async function filter(families, keyword) {
  const module = await import('../src/lib/registryFamilies.js').catch(() => ({}))
  assert.equal(typeof module.filterRegistryFamilies, 'function', '分类搜索尚未实现')
  return module.filterRegistryFamilies(families, keyword)
}
const families = [
  {id:'stellar-mass',label:'恒星质量',count:5},
  {id:'radial-velocity',label:'径向速度',count:8},
  {id:'distance',label:'天体距离',count:3},
  {id:'unlabelled'}
]
test('family search matches readable names and exact identifiers without changing selection data', async () => {
  assert.deepEqual((await filter(families,'质量')).map(x=>x.id),['stellar-mass'])
  assert.deepEqual((await filter(families,'VELOCITY')).map(x=>x.id),['radial-velocity'])
  assert.deepEqual((await filter(families,'unlabelled')).map(x=>x.id),['unlabelled'])
  assert.deepEqual(families[0],{id:'stellar-mass',label:'恒星质量',count:5})
})
test('family search accepts spaced multiword and full-width input and preserves catalogue order', async () => {
  assert.deepEqual((await filter(families,'  ＳＴＥＬＬＡＲ   质量  ')).map(x=>x.id),['stellar-mass'])
  assert.deepEqual(await filter(families,'  '),families)
  assert.deepEqual(await filter(families,'没有这个分类'),[])
})
test('family search reaches the end of a large directory without truncating or mutating rows', async () => {
  const large=Array.from({length:5000},(_,index)=>({id:`family-${index}`,label:`性质分类 ${index}`}))
  const matches=await filter(large,'family-4999')
  assert.deepEqual(matches,[{id:'family-4999',label:'性质分类 4999'}])
  assert.equal((await filter(large,'')).length,5000)
  assert.equal(matches[0],large[4999])
})
test('family picker keeps native labels, required selection, and an explicit missing current family', async () => {
  const server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'})
  try {
    const {default:Picker}=await server.ssrLoadModule('/src/components/registry/RegistryFamilySelect.jsx')
    const html=renderToStaticMarkup(React.createElement(Picker,{families,value:'historic-family',onChange:()=>{},required:true,disabled:true,emptyLabel:'请选择性质分类'}))
    assert.match(html,/<input[^>]*type="search"[^>]*aria-label="搜索性质分类"/)
    assert.doesNotMatch(html,/<input[^>]*required/)
    assert.match(html,/<select[^>]*name="family_id"[^>]*required=""/)
    assert.match(html,/<option[^>]*value="historic-family"[^>]*selected=""/)
    assert.match(html,/当前版本未提供/)
    assert.match(html,/请选择性质分类/)
    assert.equal((html.match(/disabled=""/g)||[]).length,2)
  } finally {await server.close()}
})
