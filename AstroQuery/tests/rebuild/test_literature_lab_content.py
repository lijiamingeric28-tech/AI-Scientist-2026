"""Material evidence binding is not a scientific accuracy assertion."""
import pytest
from astroquery_ai.runtime.errors import DomainError
from tests.support.literature.content import checked


def context(status='U'):
    return {'source_identity':{'subject':'synthetic target','quantity':'synthetic length',
        'estimator':'synthetic direct measurement','coordinate':'source native linear',
        'reference_context':'synthetic local measurement baseline',
        'role':'adopted_result' if status=='U' else 'unknown'},
        'scope_match':'exact' if status=='U' else 'insufficient'}


def test_u_has_real_page_and_verbatim_excerpt_but_no_measurement():
    row={**context(),'status':'U','match_reason':'synthetic explicitly adopted length for target',
        'evidence':[{'page':2,'quote':'Reported length 1 +/- 2 units','role':'adopted'}]}
    result=checked(row,{2:'Table header\nReported length 1 +/- 2 units\nfootnote'})
    assert result['formal_measurement'] is False
    assert result['evidence'][0]['binding']=='native_text_verified'
    with pytest.raises(DomainError):checked(row,{3:'Reported length 1 +/- 2 units'})
    with pytest.raises(DomainError):checked(row,{2:'A related but different quantity'})
    with pytest.raises(DomainError):checked({**row,'evidence':[]},{2:'text'})


def test_visual_quote_is_anchored_to_actual_page_not_claimed_native_text_verified():
    row={**context(),'status':'U','match_reason':'synthetic table read on original image',
        'evidence':[{'page':1,'quote':'Actual imaged value','role':'reported'}]}
    result=checked(row,{1:''},visual=True)
    assert result['evidence'][0]['binding']=='actual_image_page_executor_check_required'
    with pytest.raises(DomainError):checked(row,{2:''},visual=True)


def test_unknown_is_separate_from_scientific_absence():
    row={**context('Q'),'status':'Q','match_reason':'Native layer does not expose table; inspect original page','evidence':[]}
    assert checked(row,{1:''})['status']=='Q'


def test_block_selection_preserves_formula_and_original_errors_without_model_recopy():
    from tests.support.literature.content import evidence_blocks
    text='Table header and target\nraw native formula +/- components\nfootnote'
    blocks=evidence_blocks({3:text})
    response={**context(),'status':'U','match_reason':'synthetic exact requested result in supplied block',
              'evidence':[{'blocks':['B1'],'role':'adopted'}]}
    result=checked(response,{3:text},blocks=blocks)
    assert result['evidence'][0]['quote']==text
    assert result['evidence'][0]['source_char_range']==[0,len(text)]
    assert result['evidence'][0]['page']==3
    response['evidence'][0]['blocks']=['B99']
    with pytest.raises(DomainError):checked(response,{3:text},blocks=blocks)


def test_u_cannot_override_a_structured_different_scope_or_fixed_assumption():
    row={**context(),'status':'U','match_reason':'A related source coordinate is not the native requested coordinate',
         'evidence':[{'page':1,'quote':'Original native source text','role':'reported'}]}
    row['scope_match']='related'
    with pytest.raises(DomainError):checked(row,{1:'Original native source text'})
    row['scope_match']='exact';row['source_identity']['role']='fixed_assumption'
    with pytest.raises(DomainError):checked(row,{1:'Original native source text'})
    row['status']='F'
    assert checked(row,{1:'Original native source text'})['status']=='F'
