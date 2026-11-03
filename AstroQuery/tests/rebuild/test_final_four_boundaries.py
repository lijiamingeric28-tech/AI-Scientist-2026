"""Final-four release: semantic quantity/method separation and local repair state."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.calls import ModelProfile
from astroquery_ai.science import archive_comparison as archive
from astroquery_ai.science.measurements.admission_contracts import QuantityScope
from astroquery_ai.science.unified_quality import paper_item_wire


def scope(requirement='not_restricted',match=None,physical='same'):
    return dict(reported_quantity='SYNTHETIC Q',subject_scale='whole target',native_representation='linear',
        native_coordinate_kind='linear',physical_relation=physical,evidence=[{'page':2,'block_ids':['b2']}],
        estimator=dict(requirement=requirement,selected_requirement='SYNTHETIC registered scope' if requirement=='required' else None,
            reported_estimator='SYNTHETIC actual method B',match=match,evidence=[{'page':2,'block_ids':['b2']}]))


@pytest.mark.parametrize('requirement,match,physical,expected',[
    ('not_restricted',None,'same','same'),('required','same','same','same'),
    ('required','different','same','related_or_different'),('required','insufficient','same','insufficient'),
    ('insufficient',None,'same','insufficient'),('not_restricted',None,'related_or_different','related_or_different'),
    ('required','same','requires_derivation','requires_derivation')])
def test_quantity_and_method_generate_one_admission(requirement,match,physical,expected):
    decision=QuantityScope.model_validate(scope(requirement,match,physical));identity=decision.identity()
    assert identity.relation==expected
    raw={'quantity_scope':decision.model_dump(mode='json'),'assessment':{}}
    before=deepcopy(raw)
    result=paper_item_wire(raw,0,visible_blocks=[{'block_id':'b2','page':2}],require_quantity_scope=True)
    assert result['assessment']['quantity_identity']['relation']==expected and raw==before
    assert result['native_representation']=='linear'
    assert identity.estimator_identity.reported_estimator=='SYNTHETIC actual method B'


def test_conflicting_duplicate_decision_and_unrestricted_method_match_are_rejected():
    with pytest.raises(ValidationError):QuantityScope.model_validate(scope('not_restricted','different'))
    with pytest.raises(ValidationError):QuantityScope.model_validate(scope('required',None))
    with pytest.raises(DomainError):paper_item_wire({'quantity_scope':scope('required','different'),
        'assessment':{'quantity_match':'exact'}},0)
    with pytest.raises(DomainError):paper_item_wire({'assessment':{}},0,require_quantity_scope=True)


def test_unrestricted_wire_needs_no_comparison_and_known_block_supplies_page():
    q=scope();q['estimator'].pop('match');q['estimator'].pop('selected_requirement')
    q['evidence']=[{'anchor':{'block_ids':['b2']}}]
    result=paper_item_wire({'quantity_scope':q,'assessment':{}},0,visible_blocks=[{'block_id':'b2','page':2}],keep_scopes=True)
    assert result['quantity_scope'].evidence[0].page==2
    assert result['assessment']['quantity_identity']['estimator_identity']['relation']=='not_restricted'
    q['evidence']=[{'anchor':{'block_ids':['not-in-material']}}]
    with pytest.raises(ValidationError):
        paper_item_wire({'quantity_scope':q,'assessment':{}},0,visible_blocks=[{'block_id':'b2','page':2}])


def test_quality_repair_identifies_field_without_echoing_model_inputs():
    from astroquery_ai.science.unified_quality import quality_repair
    repair=quality_repair(['I2'],[{'item':'I1','code':'other'},dict(item='I2',code='QUALITY_ITEM_SCHEMA',
        field_hint='estimator.match: omit for an unrestricted method',details='untrusted raw reply')])
    assert repair['errors']==[{'item':'I2','code':'QUALITY_ITEM_SCHEMA','field_hint':'estimator.match: omit for an unrestricted method'}]


def material():
    labels={k:dict(measurement_id=k,revision=1,content_sha256=k) for k in ('R1','R2','R3','R4')}
    evidence={'E'+k[1:]:dict(record=k,ref={'id':'e'+k[1:],'version':1,'content_sha256':k}) for k in labels}
    group=dict(members=['R1','R2'],evidence=['E1','E2'],reason='SYNTHETIC original repeated result',
        basis='repeated_author_result',member_evidence={'R1':['E1'],'R2':['E2']})
    return labels,evidence,group


def test_interpretation_issue_requires_own_record_evidence_but_allows_comparison():
    labels,evidence,_=material()
    raw=dict(checked_members=list(labels),interpretation_issues=[dict(member='R1',evidence=['E2'],problem='SYNTHETIC issue')])
    reply,errors=archive.checked_parts(raw,labels,evidence)
    assert errors and not reply.interpretation_issues
    raw['interpretation_issues'][0]['evidence']=['E1','E2']
    reply,errors=archive.checked_parts(raw,labels,evidence)
    assert not errors and len(reply.interpretation_issues)==1


@pytest.mark.parametrize('repair,expected',[('overlap','partial'),('legal','checked'),('none','checked')])
def test_repair_merge_retains_good_groups_and_unresolved_state(monkeypatch,repair,expected):
    labels,evidence,good=material()
    bad={**good,'members':['R3','R4'],'evidence':['E3'],'member_evidence':{'R3':['E3'],'R4':['E3']}}
    first={'checked_members':list(labels),'duplicates':[] if repair=='none' else [good,bad]}
    members=['R2','R3'] if repair=='overlap' else ['R3','R4']
    second={'checked_members':list(labels),'duplicates':[{**good,'members':members,
        'evidence':['E'+k[1:] for k in members],'member_evidence':{k:['E'+k[1:]] for k in members}}]}
    responses=[first,second];saved=[];calls=[]
    @contextmanager
    def transaction():yield None
    repo=SimpleNamespace(read=transaction,transaction=transaction,validate_lease=lambda *a:None,
        put_object=lambda *a:saved.append(a[-1]),finish_job=lambda *a:None)
    monkeypatch.setattr(archive,'comparison_input',lambda *a:({'answered_questions':[]},labels,evidence))
    async def model(*args,**kw):
        calls.append(kw);return responses[len(calls)-1],{'attempt_id':str(len(calls))}
    service=SimpleNamespace(repo=repo,spec=lambda *a:{},steps=SimpleNamespace(model=model),
        model_profile=lambda *a,**k:ModelProfile(model='qwen3.7-plus',**k))
    asyncio.run(archive.compare_results(service,dict(task_id='synthetic',payload=dict(property_id='p',
        input_hash='hash',measurement_refs=[]))))
    report=saved[-1];assert report['state']==expected
    assert len(report['duplicates'])==({'overlap':1,'legal':2,'none':0}[repair])
    if repair=='overlap':assert any(x.get('code')=='COMPARISON_GROUP_OVERLAP' for x in report['diagnostics'])
    assert len(calls)==(1 if repair=='none' else 2)
