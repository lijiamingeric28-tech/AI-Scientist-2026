import {test} from 'node:test'
import assert from 'node:assert/strict'
import {parseConnectionCsv} from './connectionCsv.js'

test('Bailian key-value and quoted header exports import both connection fields',()=>{
 const url='https://dashscope.aliyuncs.com/compatible-mode/v1'
 for(const csv of [`apiKey,key\nopenAiCompatible,${url}`,`\ufeffapiKey,openAiCompatible\r\n"key","${url}"`]) {
  assert.deepEqual(parseConnectionCsv(csv),{dashscope_api_key:'key',dashscope_base_url:url})
 }
})
test('Unrelated text and incomplete exports cannot replace a connection',()=>{
 for(const csv of ['apiKey,key','x,y',''])assert.throws(()=>parseConnectionCsv(csv))
})
