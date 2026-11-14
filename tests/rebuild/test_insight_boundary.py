"""Source-owner decisions bind real blocks; no value, title or reason guessing."""
import pytest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.insight_boundary import verify


@pytest.mark.parametrize('subject,role,state',[
    ('other_scope','reported_result','rejected'),
    ('within_requested_scope','assumption','rejected'),
    ('within_requested_scope','calibration_constant','rejected'),
    ('within_requested_scope','reported_result','passed'),
    ('within_requested_scope','adopted_measurement','passed'),
    ('unknown','reported_result','unresolved'),
])
def test_explicit_owner_semantics_have_bounded_report_consequences(subject,role,state):
    blocks=[{'block_id':'p3:b2','page':3,'text':'SYNTHETIC original passage; no numerical answer seed.'}]
    result=verify({'item_id':'I1','target_relation':subject,'result_role':role,
        'evidence_blocks':['p3:b2'],'reason':'SYNTHETIC semantic owner decision'},blocks)
    assert result['state']==state
    assert result['original_anchors'][0]['quote']==blocks[0]['text']
    assert result['scope']=='subject_and_result_role_only'


def test_selected_evidence_must_exist_and_a_reason_is_not_evidence():
    with pytest.raises(DomainError,match='责任判断'):
        verify({'item_id':'I1','target_relation':'other_scope','result_role':'reported_result',
            'evidence_blocks':['invented'],'reason':'This explanation cannot manufacture an original.'},[])


def test_bad_reference_does_not_destroy_available_original_references():
    actual=[{'block_id':'p4:b1','page':4,'text':'SYNTHETIC actual source'}]
    result=verify({'item_id':'I1','target_relation':'within_requested_scope','result_role':'adopted_measurement',
        'evidence_blocks':['invented','p4:b1'],'reason':'SYNTHETIC available original supports this judgment'},actual)
    assert result['state']=='passed'
    assert result['check']['evidence_blocks']==['p4:b1']
    assert result['ignored_invalid_evidence_blocks']==['invented']
