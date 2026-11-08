import assert from 'node:assert/strict'
import {test} from 'node:test'
import {readingConditions,recordConditionText,reviewRows,reviewWording,rawCells} from './scienceReading.js'
import {buildDupIndex} from './dupMarkers.js'

test('common reading fields exclude registry bookkeeping; original row retains nulls and zeros',()=>{
  assert.deepEqual(readingConditions([{key:'native_unit_representation_and_main_state',state:'known',value:'linear'},
    {key:'band',state:'known',value:'I'},{key:'band',state:'known',value:'I'}]),[{label:'波段',value:'I'}])
  const cells=rawCells({text_origin:'original_cells',locator:{column:'DM'},raw_text:'{"cells":{"DM":0,"e_DM":null}}'})
  assert.equal(cells[0].raw,0);assert.equal(cells[0].is_main,true);assert.equal(cells[1].raw,null)
})
test('selection and evidence remain attached to each reported measurement',()=>{
  const review={question:'Does R1 match R2?',issue_kind:'comparison_contradiction',record_interpretations:{
    one:{record:{raw_value:'5.8',unit:'Å'},proposal:{result_role:'reported_result'},evidence_refs:[{id:'a'}]},
    two:{record:{raw_value:'27',unit:'mÅ'},proposal:{result_role:'model_prediction'},evidence_refs:[{id:'b'}]}}}
  assert.equal(reviewWording(review).original,review.question)
  assert.deepEqual(reviewRows(review).map(r=>[r.unit,...r.evidence]),[['Å','a'],['mÅ','b']])
})

test('record conditions treat real catalogue designations as literal text', () => {
  const subject = value => ({key:'source_subject_and_measurand',state:'known',value})
  for (const name of ['* alf Lyr', '* alf Boo', 'PSR B0329+54', '[ABC] (1).?']) {
    assert.equal(recordConditionText([subject(`${name.toUpperCase()}：整体恒星`)], name), '整体恒星')
    assert.equal(recordConditionText([subject(name)], name), '')
  }
  assert.equal(recordConditionText([subject('M31 companion'), null], 'M3'), 'M31 companion')
  assert.equal(recordConditionText([subject('已报告的测量')], null), '已报告的测量')
  assert.equal(recordConditionText(null, '* alf Lyr'), '')
})
test('archive groups still fold when the scoring report has not been opened',()=>{
  const group={group_id:'g',member_refs:[{id:'a'},{id:'b'}],display_anchor:{id:'b'}}
  const rows=['a','b'].map(record_id=>({record_id,archive_groups:[group]}))
  const index=buildDupIndex(rows,null)
  assert.equal(index.groups.length,1);assert.equal(index.byRecordId.b.isRepresentative,true)
})
