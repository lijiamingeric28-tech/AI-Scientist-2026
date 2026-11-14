"""Typed boundaries, not a catalogue of object/quantity-specific answers."""
from copy import deepcopy
from decimal import Decimal
import pytest
from pydantic import ValidationError
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.models import UncertaintyComponent
from astroquery_ai.science.measurements.uncertainty_values import canonical_error_values
from astroquery_ai.science.measurements.uncertainty_components import assemble_uncertainties
from astroquery_ai.science.measurements.admission_contracts import QuantityIdentity,AdmissionCheck
from astroquery_ai.science.archive_comparison import checked_parts,checked_reply


@pytest.mark.parametrize('kind,values,expected',[
    ('asymmetric_delta',{'minus':'-0.0230','plus':'0.0410'},{'minus':'0.0230','plus':'0.0410'}),
    ('asymmetric_delta',{'minus':'0.12','plus':'0.18'},{'minus':'0.12','plus':'0.18'}),
    ('asymmetric_delta',{'minus':'-7.2','plus':None},{'minus':'7.2','plus':None}),
    ('asymmetric_delta',{'minus':'-0.123456789012345678901234567890123456789','plus':'0.2'},
        {'minus':'0.123456789012345678901234567890123456789','plus':'0.2'}),
    ('asymmetric_delta',{'minus':None,'plus':'3.2'},{'minus':None,'plus':'3.2'}),
    ('asymmetric_delta',{'minus':'-2','plus':'-1'},{'minus':'-2','plus':'-1'}),
    ('interval_endpoints',{'kind':'interval','lower':'-8','upper':'-2','lower_closed':True,'upper_closed':True},
        {'kind':'interval','lower':'-8','upper':'-2','lower_closed':True,'upper_closed':True}),
    ('covariance',{'matrix':[['-0.4']]},{'matrix':[['-0.4']]}),
    ('symmetric_delta',{'delta':'-2'},{'delta':'-2'}),
])
def test_only_typed_lower_offsets_are_adapted(kind,values,expected):
    before=deepcopy(values);actual,receipt=canonical_error_values(kind,values)
    assert values==before and actual==expected
    if actual!=before:
        assert receipt['input_values']==before and receipt['output_values']==expected


def test_actual_assembly_retains_signed_values_and_independent_roles():
    ref={'id':'real-ref','version':1,'content_sha256':'a'*64}
    def error(role,minus,plus):
        return {'location':role,'raw_text':f'{minus} / +{plus}','kind':'asymmetric_delta',
            'values':{'minus':minus,'plus':plus},'role':role,'meaning':'reported_error',
            'interpretation_state':'parsed','reason':None,'source_unit':'km',
            'level_kind':None,'level_values':[],'level_raw_text':None}
    doc={'unit':'km','representation':'linear','errors':[error('stat','-0.012','0.017'),error('sys','-0.004','0.009')]}
    before=deepcopy(doc)
    parts,units,bases=assemble_uncertainties(doc=doc,source={},owner='M06',mid='m',evref=ref,ur=ref,ir=ref,component_parent_ids={})[:3]
    assert doc==before and [p['role'] for p in parts]==['stat','sys']
    assert all(p['interpretation_state']=='parsed' and p['level'] is None for p in parts)
    assert [p['values']['minus'] for p in parts]==['0.012','0.004']
    assert parts[0]['value_adaptation']['input_values']['minus']=='-0.012'
    assert UncertaintyComponent.model_validate(parts[0]).model_dump()['value_adaptation']['input_values']['minus']=='-0.012'
    assert units[0]['unit_text']=='km' and not bases


@pytest.mark.parametrize('wire,canonical',[('different','related_or_different'),('unknown','insufficient'),('same','same'),('requires_derivation','requires_derivation')])
def test_quantity_wire_alias_keeps_scientific_meaning(wire,canonical):
    value=QuantityIdentity.model_validate({'reported_quantity':'given quantity','subject_scale':'whole',
        'native_representation':'linear','relation':wire,'evidence':[{'page':1,'quote':'actual source'}]})
    assert value.relation==canonical


def test_negative_relation_cannot_become_exact_through_alias():
    with pytest.raises(ValidationError):
        AdmissionCheck.model_validate({'index':0,'subject':'target','printed_subject':'a','subject_evidence':[],
            'result_role':'reported_result','role_evidence':[],'reason':'actual source', 'quantity_match':'exact',
            'quantity_identity':{'reported_quantity':'another quantity','subject_scale':'whole',
                'native_representation':'linear','relation':'different','evidence':[{'page':1,'quote':'actual source'}]}})


def archive_input():
    labels={k:{} for k in ('R1','R2','R3','R4')}
    evidence={'E'+k[1:]:{'record':k} for k in labels}
    group={'members':['R1','R2'],'evidence':['E1','E2'],'reason':'same author result at two locations',
        'basis':'repeated_author_result','member_evidence':{'R1':['E1'],'R2':['E2']}}
    return labels,evidence,group


def test_archive_local_bad_group_does_not_erase_good_group():
    labels,evidence,good=archive_input()
    bad={**good,'members':['R3','R4'],'evidence':['E3'],'member_evidence':{'R3':['E3'],'R4':['E3']}}
    reply,errors=checked_parts({'checked_members':list(labels),'duplicates':[good,bad]},labels,evidence)
    assert len(reply.duplicates)==1 and reply.duplicates[0].members==['R1','R2']
    assert len(errors)==1 and errors[0]['index']==1


def test_same_number_does_not_supply_missing_duplicate_basis():
    labels,evidence,group=archive_input();group.pop('basis')
    reply,errors=checked_parts({'checked_members':list(labels),'duplicates':[group]},labels,evidence)
    assert not reply.duplicates and errors


def test_answer_reuse_checks_current_members_and_evidence_not_group_name():
    labels,evidence,_=archive_input()
    suspicion={'members':['R1','R2'],'evidence':['E1','E2'],'shared_premise':'same asserted definition',
        'claims':{'R1':'claim one','R2':'incompatible claim'},'question':'已经核过的实际主张',
        'member_evidence':{'R1':['E1'],'R2':['E2']},'reuse_review_id':'answered'}
    raw={'checked_members':list(labels),'suspicions':[suspicion]}
    answered=[{'review_id':'answered','members':['R1','R2','R3'],'evidence':['E1','E2','E3']}]
    assert checked_reply(raw,labels,evidence,answered).suspicions[0].reuse_review_id=='answered'
    evidence['Enew']={'record':'R1'}
    # Additional unselected context is not a new proposition. A reuse which
    # actually relies on new evidence must fail instead of swallowing it.
    assert checked_reply(raw,labels,evidence,answered).suspicions[0].reuse_review_id=='answered'
    suspicion['evidence'].append('Enew');suspicion['member_evidence']['R1'].append('Enew')
    with pytest.raises(DomainError):checked_reply(raw,labels,evidence,answered)
