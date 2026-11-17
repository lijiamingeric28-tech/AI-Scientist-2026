import {test} from 'node:test'
import assert from 'node:assert/strict'
import {isCustomTitle, taskTitle} from './taskTitle.js'

for (const question of ['查 HD 209458 的有效温度。', '中'.repeat(120), '中'.repeat(121), '长中文需求'.repeat(40), '🌟'.repeat(119)+'🪐研究测量']) {
  test(`old API default prefix uses Unicode code points (${Array.from(question).length})`,()=>{
    const row={title:Array.from(question).slice(0,120).join('')}
    assert.equal(isCustomTitle(row,question),false)
    assert.equal(taskTitle(row,{question,target:'HD 209458'}),'HD 209458')
    assert.equal(taskTitle({...row,title_origin:'auto'},{target:'HD 209458'}),'HD 209458')
  })
}
test('explicit manual name wins even when equal to original prefix or question unavailable',()=>{
  const question='中'.repeat(140), row={title:question.slice(0,120),title_origin:'custom'}
  for (const identity of [{question,target:'HD 209458'},{target:'HD 209458'}]) {
    assert.equal(isCustomTitle(row,identity.question),true)
    assert.equal(taskTitle(row,identity),row.title)
  }
  assert.equal(taskTitle({title:'my name'},{question:'other',target:'SN 2011fe'}),'my name')
})
test('heading and sidebar resolve the same backend metadata without losing fallback text',()=>{
  assert.equal(taskTitle({title:'short input',title_origin:'auto'},{target:'δ Cep'}),'δ Cep')
  assert.equal(taskTitle({title:'short input',title_origin:'auto'},null),'short input')
  assert.equal(taskTitle(null,null),'')
})
