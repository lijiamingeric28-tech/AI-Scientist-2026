import test from 'node:test'
import assert from 'node:assert/strict'
import {typedValueText,limitedValueText} from './valueDisplay.js'
test('zero and false remain visible rather than missing or blank',()=>{
 assert.equal(typedValueText({kind:'real',value:'0.000'}),'0.000')
 assert.equal(typedValueText({kind:'boolean',value:false}),'否')
})
test('limits remain limits without inventing strict versus inclusive signs',()=>{
 assert.equal(limitedValueText({kind:'real',value:'3.40'},'upper'),'上限 3.40')
 assert.equal(limitedValueText({kind:'real',value:'3.40'},'lower'),'下限 3.40')
})
test('interval endpoint closure is preserved and unrecorded closure stays unknown',()=>{
 assert.equal(typedValueText({kind:'interval',lower:'1',upper:'2',lower_closed:false,upper_closed:true}),'(1, 2]')
 assert.match(typedValueText({kind:'interval',lower:'1',upper:'2'}),/边界开闭未记录/)
})
