"""Unified evidence-stage routing, stable repair roots and source coverage."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.codec import content_hash
from astroquery_ai.runtime.run_policy import CONSOLIDATION_RUN_POLICY
from astroquery_ai.runtime.stages import JOB_STAGE
from astroquery_ai.science.unified_quality import plan_checks,apply_item,PaperQualityReply
from astroquery_ai.science.source_review import SourceItemCheck
from tests.rebuild.test_paper_admission import paper_proposal
from tests.rebuild.test_scientific_review_gate import check_data
from astroquery_ai.science.unified_quality import paper_item_wire
from astroquery_ai.runtime.errors import DomainError
import pytest
from pydantic import ValidationError


def test_unified_paper_input_keeps_local_subject_identity_before_quantity():
    from astroquery_ai.science.unified_quality import _paper_input
    from astroquery_ai.science.paper_admission import verification_instruction
    proposal=paper_proposal()
    binding={'property_id':proposal.property_id,'definition':{
        'name_cn':'合成整体长度','name_en':'Synthetic whole length','quantity_key':'synthetic.length',
        'quantity_kind':'length','scope':'whole','description':'Source-reported whole length.',
        'aliases':[],'measurement_conditions_schema':[],
        'explanation':{'quantity':'Source-reported whole length','subject':'identified whole target',
            'representation':'native linear length','boundary':'Retain related model context.'}},
        'output_profile':{'unit':{'kind':'physical','dimension':'length','canonical_symbol':'m'},
            'representation':{'kind':'linear'}}}
    spec={'target':{'main_id':'SYNTHETIC_REQUEST','aliases':['SYNTHETIC_ALIAS']},'properties':[binding]}
    pages={3:'SYNTHETIC_OTHER is measured relative to SYNTHETIC_REQUEST; the local value belongs to the former.'}
    original=verification_instruction(spec,[],pages,compact=True)
    body,_,_,_=_paper_input(spec,binding,{'pages':[{'page':3,'text':pages[3]}]},
        [{'proposal':proposal.model_dump(mode='json')}],[])
    assert body['target']==original['target']
    for key in ('subject_rule','subject_and_role_cautions'):
        assert body[key]==original[key]
    assert 'quantity_scope.physical_relation' in body['independent_decisions']
    assert 'quantity_identity' not in body['schema']['$defs']['AdmissionCheck']['properties']
    assert body['instruction'].index('physical subject') < body['instruction'].index('reported concrete quantity')
    assert 'subject_role' not in body['items'][0]['proposal']
    assert 'subject' not in body['schema']['$defs']['AdmissionCheck']['properties']
    assert 'relation' not in body['schema']['$defs']['SubjectLink']['properties']
    assert 'physical_subject' in body['schema']['$defs']['PaperQualityItem']['required']


def test_physical_subject_decision_maps_once_without_name_or_reason_parsing():
    raw={'physical_subject':{'source_referent':'SYNTHETIC_OTHER','relation_to_requested':'different_object',
        'local_blocks':['v'],'scope_blocks':['s'],'reason':'SYNTHETIC explicit local source relation'},'assessment':{}}
    blocks=[{'block_id':'v','page':3},{'block_id':'s','page':2}]
    fixed=paper_item_wire(raw,0,visible_blocks=blocks,require_physical_subject=True)
    assert fixed['assessment']['subject']=='other'
    assert fixed['assessment']['printed_subject']=='SYNTHETIC_OTHER'
    assert fixed['assessment']['subject_link']['relation']=='other'
    assert 'physical_subject' not in fixed and 'subject' not in raw['assessment']
    with pytest.raises(DomainError):paper_item_wire({'assessment':{}},0,require_physical_subject=True)
    with pytest.raises(DomainError):paper_item_wire({**raw,'assessment':{'subject':'target'}},0,visible_blocks=blocks)
    with pytest.raises(DomainError):paper_item_wire(raw,0,visible_blocks=[])
    raw['physical_subject'].update(source_referent=None,relation_to_requested='insufficient')
    assert paper_item_wire(raw,0,visible_blocks=blocks)['assessment']['subject']=='unresolved'


def test_known_anchor_wrapper_reuses_actual_block_page_without_inventing_evidence():
    raw={'assessment':{'subject_evidence':[{'anchor':{'block_ids':['actual-block'],'quote':None}}]}}
    fixed=paper_item_wire(raw,0,visible_blocks=[{'block_id':'actual-block','page':7}])
    assert fixed['assessment']['subject_evidence']==[{'block_ids':['actual-block'],'quote':None,'page':7}]
    unknown=paper_item_wire(raw,0,visible_blocks=[])
    assert unknown['assessment']['subject_evidence']==[{'block_ids':['actual-block'],'quote':None}]
    assert raw['assessment']['subject_evidence'][0].get('anchor')


@pytest.mark.parametrize('unified',[False,True])
def test_candidate_commit_only_schedules_its_actual_quality_owner(tmp_path,unified):
    from astroquery_ai.science.workflow.context import ScienceContext
    repo=Repository(tmp_path/'db');tid=repo.create_task('SYNTHETIC quality owner')['task_id']
    ctx=ScienceContext(SimpleNamespace(repository=repo))
    spec={'run_policy':deepcopy(CONSOLIDATION_RUN_POLICY)} if unified else {}
    candidate={'state':'review_candidate','proposal':paper_proposal().model_dump(mode='json'),
        'assembly_context':{'spec':spec,'source':{'source_id':'synthetic-source'},'owner':'M03'}}
    with repo.transaction() as c:
        ctx.commit_candidates(c,tid,[candidate],'initial-synthetic-batch')
        saved=repo.objects(c,tid,'candidate');assert len(saved)==1
        jobs=list(c.execute("select payload from jobs where task_id=? and kind='assess_batch'",(tid,)))
        if unified:
            assert not jobs
            links=repo.objects(c,tid,'quality_candidate_link')
            roots=repo.objects(c,tid,'quality_candidate_root')
            assert len(roots)==len(links)==1 and links[0]['candidate_ref']['id']==saved[0]['candidate_id']
        else:
            from astroquery_ai.runtime.codec import loads
            assert len(jobs)==1 and loads(jobs[0][0])['candidate_ids']==[saved[0]['candidate_id']]


def test_empty_initial_batch_keeps_completion_event_without_empty_assessment(tmp_path):
    from astroquery_ai.science.workflow.context import ScienceContext
    repo=Repository(tmp_path/'db');tid=repo.create_task('SYNTHETIC empty batch')['task_id']
    ctx=ScienceContext(SimpleNamespace(repository=repo))
    with repo.transaction() as c:
        ctx.commit_candidates(c,tid,[],'empty-synthetic-batch')
        assert not c.execute('select 1 from jobs where task_id=?',(tid,)).fetchone()
    event=repo.events(tid)[-1]
    assert event['kind']=='batch_committed' and event['payload']['candidate_count']==0


def test_initial_quality_output_groups_cover_every_candidate_without_failure_splitting():
    from astroquery_ai.science.unified_quality import output_groups
    items=list(range(17))
    paper=list(output_groups(items,paper=True));catalog=list(output_groups(items,paper=False))
    assert [len(g) for g in paper]==[6,6,5]
    assert [i for g in paper for i in g]==items
    assert [len(g) for g in catalog]==[12,5]
    assert [i for g in catalog for i in g]==items


def test_truncated_review_keeps_only_complete_items_for_independent_schema_validation():
    from astroquery_ai.runtime.calls import complete_array_items
    assert complete_array_items('{"items":[{"item_id":"I1","assessment":{"subject":"other"}},{"item_id":"I2"', 'items')['items']==[
        {'item_id':'I1','assessment':{'subject':'other'}}]
    assert complete_array_items('{"items":[{"item_id":', 'items') is None
    # A complete JSON object is not a scientific pass; it still needs the full
    # anchored quality schema, so this deliberately incomplete verdict fails.
    with pytest.raises(ValidationError):
        PaperQualityReply.model_validate({'items':[{'item_id':'I1','assessment':{'subject':'other'}}]})


def fixture(tmp_path):
    repo=Repository(tmp_path/'db');tid=repo.create_task('SYNTHETIC unified quality')['task_id']
    source={'source_id':'s','kind':'paper'};proposal=paper_proposal().model_dump(mode='json')
    candidate={'candidate_id':'candidate-synthetic','state':'review_candidate','proposal':proposal,
        'assembly_context':{'source':source,'owner':'M06'}}
    ref={'id':candidate['candidate_id'],'version':1,'content_sha256':content_hash(candidate)}
    with repo.transaction() as c:
        repo.mutate_task(c,tid,lifecycle='running',science_state='open')
        repo.put_object(c,tid,'candidate',candidate['candidate_id'],1,candidate)
        repo.put_object(c,tid,'quality_candidate_link',candidate['candidate_id'],1,{'candidate_ref':ref,'root_id':'root'})
        repo.put_object(c,tid,'quality_candidate_root','root',1,{'root_id':'root','initial_ref':ref,'required':True})
        repo.enqueue(c,tid,'M07','quality_verify',{})
    svc=SimpleNamespace(repo=repo);job=repo.claim_job('synthetic',lease_seconds=600)
    spec={'task_id':tid,'run_policy':deepcopy(CONSOLIDATION_RUN_POLICY),'target':{'main_id':'SYNTHETIC_TARGET','aliases':[]}}
    return repo,tid,svc,job,spec,source,candidate


def check(*,different=False):
    pages,anchors,raw=check_data();raw['quantity_identity']={'reported_quantity':'SYNTHETIC source coordinate',
        'subject_scale':'whole target','native_representation':'linear','relation':'related_or_different' if different else 'same',
        'evidence':anchors}
    raw['quantity_match']='different' if different else 'exact'
    return pages,anchors,SourceItemCheck.model_validate({'item_id':'I1','assessment':raw,
        'native_representation':'linear','value_match':'different','native_numeric_literal':'26.7','errors_match':'exact'})


def test_wire_moves_misnested_coordinate_without_guessing_or_changing_verdict():
    _,_,item=check();raw=item.model_dump(mode='json');raw['assessment']['coordinate_reference_unit']='yr'
    raw.pop('coordinate_reference_unit',None);original=deepcopy(raw)
    parsed=SourceItemCheck.model_validate(paper_item_wire(raw,0))
    assert parsed.coordinate_reference_unit=='yr' and parsed.value_match=='different' and raw==original
    raw['coordinate_reference_unit']='s'
    with pytest.raises(DomainError,match='冲突'):paper_item_wire(raw,0)
    raw=original;raw['assessment']['quantity_identity']['relation']='different'
    # Formal adapters cannot invent a same/different scientific relation.
    with pytest.raises(Exception):SourceItemCheck.model_validate(paper_item_wire(raw,0))


@pytest.mark.parametrize('correction',['value','unit'])
def test_one_scientific_repair_is_scoped_to_original_root_across_new_job_ids(tmp_path,correction):
    async def run():
        repo,tid,svc,job,spec,source,candidate=fixture(tmp_path);pages,anchors,item=check()
        if correction=='unit':
            item=item.model_copy(update={'value_match':'exact','assessment':item.assessment.model_copy(
                update={'unit_match':'different','native_unit':'1000 m'})})
        material=(pages,[{'block_id':anchors[0]['block_ids'][0],'page':3,'text':pages[3]}],[])
        await apply_item(svc,job,spec,{'property_id':'p'},source,candidate,item,{'attempt_id':'synthetic'},paper_material=material)
        with repo.read() as c:
            assert len(repo.objects(c,tid,'quality_reextraction_action'))==1
            assert repo.objects(c,tid,'quality_decision')[0]['state']=='reextraction_requested'
            assert not repo.objects(c,tid,'measurement')
            assert c.execute("select count(*) from reviews where task_id=?",(tid,)).fetchone()[0]==0
        await apply_item(svc,job,spec,{'property_id':'p'},source,candidate,item,{'attempt_id':'second-check'},paper_material=material)
        with repo.read() as c:
            assert len(repo.objects(c,tid,'quality_reextraction_action'))==1
            assert c.execute("select count(*) from jobs where task_id=? and kind='quality_reextract'",(tid,)).fetchone()[0]==1
            assert any(d['reason']=='directed_reextraction_already_used' for d in repo.objects(c,tid,'quality_decision'))
    asyncio.run(run())


def test_known_different_quantity_does_not_invent_correct_value_or_ask_human(tmp_path):
    async def run():
        repo,tid,svc,job,spec,source,candidate=fixture(tmp_path);pages,_,item=check(different=True)
        await apply_item(svc,job,spec,{},source,candidate,item,{'attempt_id':'synthetic'},paper_material=(pages,[],[]))
        with repo.read() as c:
            assert repo.objects(c,tid,'quality_decision')[0]['state']=='not_applicable'
            assert not repo.objects(c,tid,'quality_reextraction_action')
            assert not repo.objects(c,tid,'measurement')
            assert not c.execute('select 1 from reviews where task_id=?',(tid,)).fetchone()
    asyncio.run(run())


def test_comparison_finding_with_used_reextract_budget_withholds_only_wrong_interpretation(tmp_path):
    async def run():
        repo,tid,svc,job,spec,source,candidate=fixture(tmp_path);pages,_,item=check(different=True)
        record={'measurement_id':'m','revision':1};record['content_sha256']=content_hash(record)
        other={'measurement_id':'other','revision':1};other['content_sha256']=content_hash(other)
        base={'id':'m','version':1,'content_sha256':record['content_sha256']}
        candidate.update(current_measurement_ref=base,comparison_problem={'problem':'SYNTHETIC actual source reports another quantity'})
        with repo.transaction() as c:
            repo.put_object(c,tid,'measurement','m',1,record);repo.put_object(c,tid,'measurement','other',1,other)
            repo.put_object(c,tid,'quality_reextraction_action','root',1,{'root_id':'root','maximum_scientific_actions':1})
        await apply_item(svc,job,spec,{},source,candidate,item,{'attempt_id':'synthetic'},paper_material=(pages,[],[]))
        with repo.read() as c:
            from astroquery_ai.science.results.publication import current_delivery_measurements
            assert len(repo.objects(c,tid,'quality_reextraction_action'))==1
            dispositions=repo.objects(c,tid,'admission_disposition')
            assert dispositions[0]['measurement_ref']==base and dispositions[0]['status']=='not_supported'
            assert current_delivery_measurements([record,other],dispositions)==[other]
            assert repo.object(c,tid,'measurement','m')==record
            assert not c.execute('select 1 from reviews where task_id=?',(tid,)).fetchone()
    asyncio.run(run())


def test_catalog_and_attachment_are_planned_with_paper_and_no_double_plans(tmp_path,monkeypatch):
    from astroquery_ai.science import source_review
    original=source_review.initial_review_groups;grouping_calls=[]
    def counted(*args,**kwargs):
        grouping_calls.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(source_review,'initial_review_groups',counted)
    repo,tid,svc,job,spec,source,candidate=fixture(tmp_path)
    with repo.transaction() as c:
        repo.finish_job(c,job)
        repo.put_object(c,tid,'document_index','s',1,{'pages':[{'page':3,'text':'SYNTHETIC original evidence for source field.'}]})
        spec['properties']=[{'property_id':candidate['proposal']['property_id'],'definition':{'description':'Synthetic test quantity'}}]
        for kind in ['catalog','official_attachment']:
            item=deepcopy(candidate);item['candidate_id']='candidate-'+kind;item['assembly_context']['source']={'source_id':kind,'kind':kind}
            item['assembly_context']['owner']='M03';ref={'id':item['candidate_id'],'version':1,'content_sha256':content_hash(item)}
            repo.put_object(c,tid,'candidate',item['candidate_id'],1,item)
            repo.put_object(c,tid,'quality_candidate_link',item['candidate_id'],1,{'candidate_ref':ref,'root_id':kind})
        plan_checks(svc,c,tid,spec);plan_checks(svc,c,tid,spec)
        assert len(grouping_calls)==1  # Do not rebuild the same evidence groups on every job completion.
        assert len(repo.objects(c,tid,'quality_plan'))==3
        assert c.execute("select count(*) from jobs where kind='quality_verify' and status='ready'").fetchone()[0]==3
        assert not c.execute("select 1 from jobs where kind='source_reconcile'").fetchone()
    assert JOB_STAGE['quality_verify']==JOB_STAGE['quality_reextract']=='quality'
    assert 'same_results' not in PaperQualityReply.model_json_schema()['properties']


def test_defining_estimator_verdict_is_grounded_and_consistent_not_a_reason_parser():
    from astroquery_ai.science.measurements.admission_contracts import QuantityIdentity
    original={'reported_quantity':'SYNTHETIC aggregate Q','subject_scale':'whole target',
        'native_representation':'linear','relation':'same','evidence':[{'page':2,'block_ids':['b2'],'quote':None}]}
    old=QuantityIdentity.model_validate(original)
    assert old.model_dump(mode='json')==original
    method={'selected_requirement':'SYNTHETIC estimator A','reported_estimator':'SYNTHETIC estimator B',
        'relation':'different','evidence':[{'page':3,'block_ids':['b3']}]}
    with pytest.raises(ValidationError):QuantityIdentity.model_validate({**original,'estimator_identity':method})
    negative=QuantityIdentity.model_validate({**original,'relation':'related_or_different','estimator_identity':method})
    assert negative.estimator_identity.reported_estimator=='SYNTHETIC estimator B'
    with pytest.raises(ValidationError):
        QuantityIdentity.model_validate({**original,'relation':'related_or_different',
            'estimator_identity':{**method,'evidence':[]}})


def test_model_selected_original_blocks_get_their_known_physical_pages():
    raw={'assessment':{'quantity_evidence':[{'page':2,'quote':'SYNTHETIC source text','block_ids':['b2','b7']}],
        'quantity_match':'exact'}}
    before=deepcopy(raw)
    fixed=paper_item_wire(raw,0,visible_blocks=[{'block_id':'b2','page':2},{'block_id':'b7','page':7}])
    assert fixed['assessment']['quantity_evidence']==[
        {'page':2,'quote':'SYNTHETIC source text','block_ids':['b2']},
        {'page':7,'quote':'SYNTHETIC source text','block_ids':['b7']}]
    assert fixed['assessment']['quantity_match']=='exact' and raw==before
    unknown=paper_item_wire(raw,0,visible_blocks=[{'block_id':'b2','page':2}])
    assert unknown['assessment']['quantity_evidence']==raw['assessment']['quantity_evidence']


def test_declared_native_unit_multiplier_is_composed_once_without_changing_a_value():
    from astroquery_ai.science.units import decimal_unit_factor
    raw={'native_unit_scale':'1000','assessment':{'native_unit':'m','unit_match':'exact','quantity_match':'exact'},'value_match':'exact'}
    before=deepcopy(raw);fixed=paper_item_wire(raw,0,proposed_unit='m')
    assert fixed['assessment']['unit_match']=='different'
    assert decimal_unit_factor(fixed['assessment']['native_unit'],'m')==1000
    assert fixed['value_match']=='exact' and fixed['assessment']['quantity_match']=='exact' and raw==before
    assert 'native_unit_scale' not in fixed
    exact=paper_item_wire(raw,0,proposed_unit='km')
    assert exact['assessment']['unit_match']=='exact'
    with pytest.raises(DomainError):paper_item_wire({**raw,'assessment':{**raw['assessment'],'native_unit':'1000 m'}},0,proposed_unit='m')
    for scale in ['0','-1','NaN']:
        with pytest.raises(DomainError):paper_item_wire({**raw,'native_unit_scale':scale},0,proposed_unit='m')


def test_source_check_field_alias_keeps_unknown_and_rejects_conflicts():
    source={'state':'unresolved','raw_info':[],'caution_quotes':[],'note':'SYNTHETIC missing scope'}
    fixed=paper_item_wire({'assessment':{},'original_source_quality':source},0)
    assert fixed['source_quality']==source and 'original_source_quality' not in fixed
    with pytest.raises(DomainError):paper_item_wire({'assessment':{},'original_source_quality':source,
        'source_quality':{**source,'state':'checked'}},0)


def test_quality_timeout_preserves_checked_sibling_and_closes_unchecked_as_technical(tmp_path, monkeypatch):
    import httpx
    from astroquery_ai.runtime.calls import ModelProfile
    from astroquery_ai.science import unified_quality as quality

    repo=Repository(tmp_path/'db');tid=repo.create_task('SYNTHETIC partial quality timeout')['task_id']
    candidates=[{'candidate_id':cid,'revision':1} for cid in ('a','b')]
    with repo.transaction() as conn:
        repo.mutate_task(conn,tid,lifecycle='running',science_state='open')
        repo.put_object(conn,tid,'source','s',1,{'kind':'catalog','metadata':{'columns':[{'name':'X'}]}})
        refs=[repo.put_object(conn,tid,'candidate',v['candidate_id'],1,v) for v in candidates]
        repo.enqueue(conn,tid,'M07','quality_verify',{'items':refs,'root_id':'quality-root','property_id':'p','work_id':'s'})
    job=repo.claim_job('test',task_id=tid)
    monkeypatch.setattr(quality,'_catalog_input',lambda *args:({'items':[{'item_id':'I1'},{'item_id':'I2'}]},{}))
    calls=[]; applied=[]
    async def model(*args,**kwargs):
        calls.append(kwargs)
        if len(calls)==2:raise httpx.ConnectTimeout('SYNTHETIC timeout')
        return {'items':[{'item_id':['malformed']},dict(item_id='I1',subject='target',quantity_relation='same',reported_quantity='X',
            subject_scale='object',result_role='reported_result',native_representation='linear',value_match='exact',
            unit_match='exact',errors_match='not_reported',evidence_columns=['X'],reason='synthetic row')]},{'attempt_id':'one'}
    async def observe(service,job,spec,binding,source,candidate,item,receipt,**kwargs):
        applied.append((candidate['candidate_id'],bool(item),receipt,kwargs['missing_reason']))
    monkeypatch.setattr(quality,'apply_item',observe)
    svc=SimpleNamespace(repo=repo,spec=lambda *args:{'properties':[{'property_id':'p'}]},
                        steps=SimpleNamespace(model=model),model_profile=lambda *args,**kwargs:ModelProfile(model='qwen3.7-plus',**kwargs))
    asyncio.run(quality.verify(svc,job))
    assert len(calls)==2 and applied[0][:3]==('a',True,{'attempt_id':'one'})
    assert applied[1]==('b',False,None,'quality_model_transport_incomplete')
    with repo.read() as conn:
        assert repo.object(conn,tid,'quality_batch_receipt',job['job_id'])['checked']==1


def test_catalogue_native_unit_witness_checks_row_column_scale_and_dimension():
    from astroquery_ai.runtime.codec import canonical
    from astroquery_ai.science.unified_quality import catalog_native_unit_receipt
    column={'name':'width','unit_text':'(2x10+3m)'}
    source={'source_id':'table-source','metadata':{'table_id':'table','columns':[column]}}
    locator={'row':3,'table':'table','column':'width'}
    original={'cells':{'width':'4.60'},'columns':[column]}
    evidence={'text_origin':'original_cells','raw_text':canonical(original).decode(),
              'source_id':'table-source','evidence_id':'cell','locator':locator,'available':True}
    candidate={'evidence':evidence}
    profile={'unit':{'kind':'physical','canonical_symbol':'km','dimension':'length'}}
    proposal=SimpleNamespace(row=3,column='width',unit='(2x10+3m)',raw_value='4.60',
                             representation='linear',value=SimpleNamespace(kind='real'))
    check=SimpleNamespace(unit_match='different',subject='target',quantity_relation='same',value_match='exact',
                          native_representation='linear',evidence_columns=['width'],review_issue=None,caution_ids=[])
    def proof():
        return catalog_native_unit_receipt(source,candidate,proposal,check,profile)
    assert proof()['unit_text']==column['unit_text'] and proof()['raw_value']=='4.60'
    assert check.unit_match=='different'  # The original model assessment stays auditable.
    proposal.unit='m'
    assert proof() is None
    proposal.unit=column['unit_text'];locator['row']=4
    assert proof() is None
    locator['row']=3;profile['unit']['dimension']='mass'
    assert proof() is None
    profile['unit']['dimension']='length';check.review_issue={'kind':'source conflict'}
    assert proof() is None
