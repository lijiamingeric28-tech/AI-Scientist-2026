from copy import deepcopy
import pytest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.metadata_wire import bind_metadata_row


def test_observed_field_aliases_and_single_property_are_mechanical_only():
    raw={'id':'W1','decision':'relevant','evidence_labels':['E1'],'relation_reason':'actual supplied metadata','rank':1}
    original=deepcopy(raw);row,changes=bind_metadata_row(raw,{'P1':'verified-property'})
    assert raw==original and row['evidence']==['E1'] and row['properties']==['P1']
    assert row['decision']=='relevant' and row['reason']=='actual supplied metadata'
    assert len(changes)==3


def test_explicit_property_choice_is_never_replaced():
    row,_=bind_metadata_row({'id':'W1','decision':'relevant','properties':['P99'],'evidence_ids':['E1']},{'P1':'p'})
    assert row['properties']==['P99']
    with pytest.raises(DomainError):bind_metadata_row({'decision':'relevant'}, {'P1':'p','P2':'q'})


def test_conflicting_fields_and_foreign_evidence_are_not_merged_or_corrected():
    with pytest.raises(DomainError):
        bind_metadata_row({'decision':'relevant','evidence':['E1'],'evidence_ids':['E2']},{'P1':'p'})
    row,_=bind_metadata_row({'decision':'relevant','evidence_ids':['E99']},{'P1':'p'})
    assert row['evidence']==['E99']  # Existing ownership resolver must reject it.


def test_production_consumer_binds_only_the_requested_property_and_owned_evidence():
    from tests.rebuild.test_consolidation_retrieval import spec
    from tests.rebuild.test_two_tier_materials import document
    from astroquery_ai.science.literature import parse_record
    from astroquery_ai.science.literature_selection import relevance_bindings,relevance_outcome
    s=spec();s['run_policy']['literature']['experiment']={'F':'F1'}
    works=[{'work_id':'w'+str(i),'records':[parse_record(document(i))]} for i in range(2)]
    scope,_=relevance_bindings(s,works)
    owned=next(tag for tag,e in scope['groups']['E'].items() if e['work_id']=='w0')
    foreign=next(tag for tag,e in scope['groups']['E'].items() if e['work_id']=='w1')
    row={'id':'W1','decision':'relevant','evidence_ids':[owned],'relation_reason':'SYNTHETIC supplied relation','rank':1}
    out=relevance_outcome({'works':[row]},works,s,scope=scope,only_ids={'w0'})
    assert out['decisions']['w0']['property_ids']==['p']
    assert out['decisions']['w0']['wire_adaptations']
    row['evidence_ids']=[foreign]
    rejected=relevance_outcome({'works':[row]},works,s,scope=scope,only_ids={'w0'})
    assert not rejected['decisions'] and rejected['errors'][0]['reason']=='LITERATURE_RELEVANCE_EVIDENCE'
    s['run_policy']['literature']['experiment']={'F':'F0'}
    original=relevance_outcome({'works':[row]},works,s,scope=scope,only_ids={'w0'})
    assert not original['decisions']  # Production baseline protocol is unchanged.
def test_repair_fits_the_same_batch_when_every_row_omits_evidence():
    from astroquery_ai.runtime.calls import input_upper_bound
    from astroquery_ai.science.workflow.literature_service import metadata_batches,metadata_repair_message
    from astroquery_ai.science.literature_selection import relevance_messages
    from tests.rebuild.test_consolidation_retrieval import spec
    from tests.rebuild.test_two_tier_materials import document
    from astroquery_ai.science.literature import parse_record
    frozen=spec();frozen['run_policy']['literature']['experiment']={'F':'F1'}
    works=[{'work_id':str(i),'records':[parse_record(dict(document(i),abstract='X' * 8000))]} for i in range(40)]
    batches=list(metadata_batches(frozen,works,96000))
    assert len(batches)>2 and [w for batch in batches for w in batch]==works
    errors=[{'reason':'LITERATURE_RELEVANCE_SCHEMA','message':'missing evidence','response_item':{'id':f'W{i+1}'}} for i in range(40)]
    repair=metadata_repair_message(errors)
    assert repair==metadata_repair_message(errors[:1])
    for batch in batches:
        messages=relevance_messages(frozen,batch)
        assert 'output_schema' in messages[-1]['content']
        assert input_upper_bound([*messages,repair])<=96000
