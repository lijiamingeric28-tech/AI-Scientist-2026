"""Synthetic boundary tests; scientific results are checked separately on originals."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from astroquery_ai.runtime.calls import ModelProfile,ModelGateway,json_input_capacity,json_messages,input_upper_bound
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.codec import loads
from astroquery_ai.query.semantic_selection import selection_prompt,selection_bindings,selection_parts,select_properties
from astroquery_ai.query.selection import resolve_property_requests
from astroquery_ai.science import archive_comparison as archive


def bindings():
    return [{'property_id':'synthetic-'+str(i),'definition':dict(name_cn='SYNTHETIC '+str(i),name_en='Synthetic '+str(i),
        description='Synthetic distinct physical quantity '+str(i)), 'output_profile':{'unit':'s'}} for i in range(1,5)]


def draft():
    return dict(original_query='SYNTHETIC a and b',target={'target_id':'synthetic-target'},revision=5,
        property_support={'support_hash':'synthetic-support','bindings':bindings()},selected_property_ids=['synthetic-4'],
        property_requests=[{'text':'old request','candidates':[{'property_id':'synthetic-4','explanation':'old P999'}]}],issues=[])


def answer(rows,mode='replace'):
    return dict(property_operation=mode,clarification_needed=False,requests=[dict(text=t,coverage='complete',gap='',
        candidate_property_ids=ids,equivalent_property_ids=ids,explanation='SYNTHETIC actual provided definition') for t,ids in rows],
        conditions=[],unknown_fragments=[])


def test_gateway_and_preflight_count_same_json_envelope_before_reserving():
    messages=[{'role':'user','content':'SYNTHETIC no mode marker'}]
    bound=input_upper_bound(json_messages(messages))
    profile=ModelProfile('qwen3.8-flash',max_input_tokens=bound-1,max_images=0)
    gateway=ModelGateway(SimpleNamespace(runtime={'dashscope_api_key':'synthetic','dashscope_base_url':'https://invalid.test'}),
        SimpleNamespace(repository=SimpleNamespace(get_task=lambda _: {'kind':'validation'})))
    with pytest.raises(DomainError) as ex:
        asyncio.run(gateway.json(task_id='synthetic',owner='M01',root_id='synthetic',messages=messages,profile=profile))
    assert ex.value.code=='MODEL_INPUT_LIMIT'
    assert ex.value.details['input_bound']==json_input_capacity(messages,profile)['input_bound']==bound


def test_previous_selected_definitions_are_readonly_not_output_labels():
    d=draft();p=selection_prompt('SYNTHETIC edit',d,bindings()[:2])
    assert p['allowed_candidate_ids']==['P1','P2']
    assert p['current_selections_read_only'][0]['selected_ref']=='S1'
    assert 'current_selected_property_ids' not in p and 'previous_property_requests' not in p
    assert 'P999' not in str(p) and 'synthetic-4' not in str(p)
    assert selection_bindings(d,bindings()[2:])['groups']['P']=={'P3':'synthetic-3','P4':'synthetic-4'}
    other=deepcopy(d);other['target']['target_id']='other'
    assert selection_bindings(other)['binding_hash']!=selection_bindings(d)['binding_hash']


def test_scope_duplicate_and_schema_errors_keep_valid_siblings():
    d=draft();raw=answer([('a',['P1']),('bad scope',['P4']),('duplicate',['P2','P2'])])
    result,errors,_=selection_parts(raw,'a',bindings()[:2],selection_bindings(d,bindings()[:2])['groups']['P'])
    assert result['requests'][0]['candidates'][0]['property_id']=='synthetic-1'
    assert len(result['requests'])==1
    assert {e['code'] for e in errors}=={'PROPERTY_CANDIDATE_SCOPE','PROPERTY_SELECTION_SCHEMA'}
    # No out-of-batch P4 is silently reinterpreted as a local ordinal.
    assert raw['requests'][1]['candidate_property_ids']==['P4']


def test_selection_repairs_only_bad_row_then_model_merges_all_legal_candidates(tmp_path):
    from astroquery_ai.application.service import Application
    app=Application(tmp_path);tid=app.repository.create_task('synthetic',kind='validation')['task_id']
    d=draft();d['selected_property_ids']=[];d['property_requests']=[]
    seen=[]
    async def model(**kw):
        prompt=loads(kw['messages'][0]['content']);seen.append(prompt)
        if len(seen)==1:raw=answer([('a',['P1']),('b',['P999'])])
        elif len(seen)==2:
            assert len(prompt['format_repair']['retained_requests_read_only'])==1
            raw=answer([('b',['P2'])])
        else:raw=answer([('a',['P1']),('b',['P2'])])
        return raw,{'attempt_id':'synthetic-'+str(len(seen))}
    result,proof=asyncio.run(select_properties(app,{'task_id':tid,'payload':{'action_id':'synthetic'}},d,'a and b',
        purpose='calibration',state='trial',calibration_call=model))
    assert len(seen)==3 and not proof['technical_batch_failures']
    assert {c['property_id'] for r in result['requests'] for c in r['candidates']}=={'synthetic-1','synthetic-2'}
    assert len(proof['batch_responses'][0]['requests'])==2


def test_real_unsupported_and_technical_unfinished_are_different_user_states():
    semantic=answer([]);semantic['requests']=[dict(text='no matching quantity',coverage='none',gap='SYNTHETIC unsupported',candidates=[])]
    d=draft();resolve_property_requests(d,{},'synthetic',semantic=semantic)
    assert any(i['kind']=='unsupported_property' and i['requires_omission'] for i in d['issues'])
    semantic['technical_batch_failures']=[{'state':'technical_incomplete_not_scientific_absence'}]
    d=draft();resolve_property_requests(d,{},'synthetic',semantic=semantic)
    assert any(i['kind']=='property_selection_incomplete' and not i['requires_omission'] for i in d['issues'])
    assert not any(i['kind']=='unsupported_property' for i in d['issues'])


def test_definition_choice_and_genuine_missing_request_remain_distinct():
    scope=bindings()[:2];mapping=selection_bindings(draft(),scope)['groups']['P']
    raw=answer([('源参数',['P1','P2'])])
    row=raw['requests'][0]
    row.update(coverage='choice',uncovered_text='',candidate_notes=[{'property_id':'P1','summary':'第一种定义'}])
    result,errors,_=selection_parts(raw,'源参数',scope,mapping,final=True)
    assert not errors
    d=draft();resolve_property_requests(d,{},'choice',semantic=result)
    assert [i['kind'] for i in d['issues']]==['ambiguous_property']
    assert d['property_requests'][0]['candidates'][0]['summary']=='第一种定义'
    row.update(coverage='partial',gap='需要补充时间范围')
    assert selection_parts(raw,'源参数，限去年',scope,mapping,final=True)[1][0]['code']=='PROPERTY_UNCOVERED_SCOPE'
    row['uncovered_text']='限去年'
    result,errors,_=selection_parts(raw,'源参数，限去年',scope,mapping,final=True)
    assert not errors
    resolve_property_requests(d,{},'partial',semantic=result)
    assert any(i.get('uncovered_text')=='限去年' and i['requires_omission'] for i in d['issues'])


def test_start_selected_is_atomic_and_idempotent(tmp_path,monkeypatch):
    from uuid import uuid4
    from tests.rebuild.scenario import application,run_until_wait
    from astroquery_ai.runtime.scheduler import Scheduler
    from astroquery_ai.runtime.run_policy import LEGACY_RUN_POLICY
    app=application(tmp_path);tid=str(uuid4())
    app.create('SYNTHETIC_AQ 测试长度',tid)
    asyncio.run(run_until_wait(app,Scheduler(app)))
    with app.repository.transaction() as conn:
        d=app._draft(conn,tid)
        d['issues'].append(dict(issue_id='gap',kind='unsupported_filter',status='open',description='限去年'))
        app._save_draft(conn,d)
    s=app.view(tid);qid=s['pending']['question_id']
    action=dict(type='start_selected',property_ids=s['draft']['selected_property_ids'],omission_ids=[],omission_context_hash=s['omission_context_hash'])
    req=dict(protocol_version=2,operation_id=str(uuid4()),question_id=qid,expected_revision=s['revision'],action=action)
    with pytest.raises(DomainError,match='明确同意'):app.draft_action(tid,req)
    assert app.view(tid)['revision']==s['revision'] and app.view(tid)['pending']['question_id']==qid
    action['omission_ids']=['gap'];req['question_id']='stale'
    with pytest.raises(DomainError):app.draft_action(tid,req)
    req['question_id']=qid
    monkeypatch.setattr('astroquery_ai.runtime.run_policy.request_policy',lambda _, preferences=None:deepcopy(LEGACY_RUN_POLICY))
    first=app.draft_action(tid,req)
    assert app.draft_action(tid,req)==first
    with app.repository.read() as conn:
        spec=app.repository.objects(conn,tid,'confirmed_query')
        assert len(spec)==1 and spec[0]['omitted_requests'][0]['issue_id']=='gap'
        assert spec[0]['confirmation']['selection_question_id']==qid
        assert conn.execute("select count(*) from jobs where task_id=? and kind='start_science'",(tid,)).fetchone()[0]==1


@pytest.mark.parametrize('mode,expected',[('add',['synthetic-4','synthetic-1']),('remove',[]),('replace',['synthetic-1'])])
def test_explicit_edits_keep_identity_and_do_not_reselect_by_names(mode,expected):
    d=draft();pid='synthetic-4' if mode=='remove' else 'synthetic-1'
    r=dict(text='synthetic edit',coverage='complete',gap='',start=None,end=None,
        candidates=[dict(property_id=pid,match='equivalent',explanation='actual given definition')])
    resolve_property_requests(d,{},'edit',semantic={**answer([],mode),'requests':[r]})
    assert d['selected_property_ids']==expected


def comparison_material():
    labels={f'R{i}':dict(measurement_id='m'+str(i),revision=1,content_sha256=str(i)) for i in range(1,13)}
    evidence={f'E{i}':dict(record=f'R{i}',source_id='s'+str(i),locator={'page':i},
        ref={'id':'e'+str(i),'version':1,'content_sha256':str(i)}) for i in range(1,13)}
    body=dict(schema=archive.ComparisonReply.model_json_schema(),property={},answered_questions=[],instruction='Return JSON from original evidence.',
        items=[dict(record=f'R{i}',same_source_key='s'+str(i),source_label='Synthetic source '+str(i),
            native={'raw_value':str(i),'unit':'s','uncertainty':{'components':[]}},processed=None,context=[],
            evidence=[f'E{i}'],reported_references=[],result_role='reported_result') for i in range(1,13)],
        evidence={k:{**{a:b for a,b in v.items() if a!='ref'},'text_ref':'B'+k[1:]} for k,v in evidence.items()},
        source_texts={f'B{i}':str(i)+'SYNTHETIC original location. '*180 for i in range(1,13)})
    return body,labels,evidence


def test_failed_cross_window_is_not_left_planned_or_claimed_checked():
    links=[{'members':['R1','R2'],'state':'original_window_planned'}]
    window=dict(members=['R1','R2'],checked_members=['R1','R2'],state='partial',attempt_id='saved-valid-siblings')
    result=archive.completed_cross_links(links,[window])
    assert result[0]['state']=='partial' and result[0]['reason']=='cross_group_original_window_incomplete'
    assert result[0]['attempt_ids']==['saved-valid-siblings']
    assert links[0]['state']=='original_window_planned'
    window['state']='checked'
    assert archive.completed_cross_links(links,[window])[0]['state']=='originals_checked'


def test_comparison_failed_repair_preserves_valid_original_group(monkeypatch):
    import httpx
    from tests.rebuild.test_final_four_boundaries import material
    labels,evidence,good=material();saved=[];calls=[]
    @contextmanager
    def tx():yield None
    repo=SimpleNamespace(read=tx,transaction=tx,validate_lease=lambda *a:None,put_object=lambda *a:saved.append(a[-1]),finish_job=lambda *a:None,objects=lambda *a:[])
    monkeypatch.setattr(archive,'comparison_input',lambda *a:(
        {'answered_questions': [], 'items': [{'record': label} for label in labels], 'evidence': evidence},
        labels, evidence))
    async def model(*a,**kw):
        calls.append(kw)
        if len(calls)==2:raise httpx.ReadTimeout('SYNTHETIC repair transport failure')
        bad={**good,'members':['R3','R4'],'evidence':['E3'],'member_evidence':{'R3':['E3'],'R4':['E3']}}
        return dict(checked_members=list(labels),duplicates=[good,bad]),{'attempt_id':'saved-first'}
    service=SimpleNamespace(repo=repo,spec=lambda *a:{},steps=SimpleNamespace(model=model),
        model_profile=lambda *a,**k:ModelProfile('qwen3.7-plus',**k))
    asyncio.run(archive.compare_results(service,{'task_id':'synthetic','payload':dict(property_id='p',input_hash='hash',measurement_refs=[])}))
    report=saved[-1]
    assert report['state']=='partial' and len(report['duplicates'])==1 and len(calls)==2
    assert any(e.get('code')=='ReadTimeout' for e in report['diagnostics'])


def test_focused_evidence_keeps_header_source_quote_and_distant_error_note():
    from astroquery_ai.science.source_review import focused_review_blocks
    from astroquery_ai.science.paper_admission import page_blocks
    from astroquery_ai.science.measurements.contracts import MeasurementProposal
    pages={1:'SYNTHETIC table header Q (m)\n'+'Unrelated original layout.\n'*800+'Target Q=12 +/- 1 m\nTable footnote original.\n',
           8:'SYNTHETIC distant note: the quoted error is an independent systematic component in m.\n'}
    note=next(b for b in page_blocks(pages) if b['page']==8)
    p=MeasurementProposal.model_validate(dict(property_id='synthetic',value={'kind':'real','value':'12'},raw_value='12',unit='m',
        representation='linear',source_quote='Target Q=12 +/- 1 m',page=1,row=None,column=None,
        subject_role='target',result_role='reported_result',location_kind='table',limit='none',conditions=[],ambiguity=None,
        errors=[dict(location='page 8',raw_text='+/- 1',kind='symmetric_delta',values={'delta':'1'},role='sys',meaning='reported_error',
            interpretation_state='parsed',reason=None,semantics_evidence=[dict(page=8,block_ids=[note['block_id']])])]))
    blocks,omitted,missing=focused_review_blocks(pages,[p],{'main_id':'Target'})
    joined='\n'.join(b['text'] for b in blocks)
    assert not missing and omitted
    assert 'SYNTHETIC table header Q (m)' in joined and 'Target Q=12 +/- 1 m' in joined
    assert note['block_id'] in {b['block_id'] for b in blocks}


def test_normal_parser_clarification_finishes_with_a_question_not_repo_attribute_error(tmp_path,monkeypatch):
    from astroquery_ai.application.service import Application
    app=Application(tmp_path)
    monkeypatch.setattr(app.registry,'load',lambda:{'manifest':{'release_id':'synthetic','content_sha256':'synthetic'}})
    monkeypatch.setattr(app,'_profile_state',lambda _: 'validated')
    async def model(**kw):
        return dict(targets=[],properties=[],conditions=[],unknown_fragments=[],property_operation='unchanged',clarification_needed=True),{'attempt_id':'synthetic'}
    monkeypatch.setattr(app.models,'json',model)
    view=app.create('SYNTHETIC ambiguous edit','648ec90c-69b5-4f32-9d62-f54c13c4104c')
    job=app.repository.claim_job('test',task_id=view['task_id'])
    asyncio.run(app.prepare(job))
    result=app.view(view['task_id'])
    assert result['lifecycle']=='waiting_input' and result['pending']
    with app.repository.read() as c:
        assert c.execute('select status from jobs where job_id=?',(job['job_id'],)).fetchone()[0]=='succeeded'


@pytest.mark.parametrize('failed_cross_group', [False, True])
def test_comparison_partition_finishes_only_after_supported_crosslinks(monkeypatch, failed_cross_group):
    body,labels,evidence=comparison_material();saved=[];calls=[]
    profile=ModelProfile('qwen3.7-plus',max_input_tokens=22000)
    plan=archive.plan_comparison_inputs(body,profile)
    assert plan['mode']=='evidence_windows_with_global_index' and len(plan['windows'])>1
    assert not plan['unplanned'] and all(w['capacity']['repair']['fits'] for w in plan['windows'])
    @contextmanager
    def tx():yield None
    repo=SimpleNamespace(read=tx,transaction=tx,validate_lease=lambda *a:None,put_object=lambda *a:saved.append(a[-1]),finish_job=lambda *a:None,objects=lambda *a:[])
    monkeypatch.setattr(archive,'comparison_input',lambda *a:(body,labels,evidence))
    async def model(*a,**kw):
        import httpx
        value=loads(kw['messages'][0]['content']);calls.append(value)
        if value['schema'].get('title')=='ComparisonNavigation':
            assert {item['record'] for item in value['all_record_index']['items']} == set(labels)
            return dict(index_members=list(labels),evidence_groups=[['R1','R12']],limitations=[]),{'attempt_id':str(len(calls))}
        assert 'all_record_index' not in value
        own=[i['record'] for i in value['items']]
        duplicates=[]
        if {'R1','R12'}<=set(own):
            if failed_cross_group:
                raise httpx.ReadTimeout('Synthetic cross-original timeout')
            duplicates=[dict(members=['R1','R12'],evidence=['E1','E12'],
                member_evidence={'R1':['E1'],'R12':['E12']},reason='SYNTHETIC explicit original adoption',basis='explicit_adoption')]
        return dict(checked_members=own,duplicates=duplicates),{'attempt_id':str(len(calls))}
    service=SimpleNamespace(repo=repo,spec=lambda *a:{},steps=SimpleNamespace(model=model),model_profile=lambda *a,**k:profile)
    asyncio.run(archive.compare_results(service,{'task_id':'synthetic','payload':dict(property_id='p',input_hash='hash',measurement_refs=[])}))
    report=saved[-1]
    assert report['state']==('partial' if failed_cross_group else 'checked')
    assert set(report['checked_members'])==set(labels)
    assert report['coverage']['uncovered_cross_window_scope'] is failed_cross_group
    assert report['coverage']['global_index']['state']=='indexed_not_scientifically_checked'
    assert len(report['duplicates']) == (0 if failed_cross_group else 1)
    if not failed_cross_group:
        assert set(report['duplicates'][0]['member_evidence'])=={'m1','m12'}
        assert report['duplicates'][0]['property_id']=='p'
    else:
        assert report['coverage']['cross_group_links'][0]['reason']=='cross_group_original_window_incomplete'
    assert sum('all_record_index' in c for c in calls) == 1


def test_oversize_navigation_index_preserves_original_windows(monkeypatch):
    body, labels, evidence = comparison_material()
    for item in body['items']:
        item['context'] = [{'note': 'SYNTHETIC carried condition ' * 180}]
    profile = ModelProfile('qwen3.7-plus', max_input_tokens=22000)
    plan = archive.plan_comparison_inputs(body, profile)
    assert len(plan['global_index']['items']) == len(labels)
    assert not plan['unplanned']
    assert {label for window in plan['windows'] for label in window['members']} == set(labels)
    assert all(window['capacity']['repair']['fits'] for window in plan['windows'])

    @contextmanager
    def transaction():
        yield None

    saved = []
    repo = SimpleNamespace(read=transaction, transaction=transaction,
                           validate_lease=lambda *args: None, finish_job=lambda *args: None,
                           objects=lambda *args: [],
                           put_object=lambda *args: saved.append(args[-1]))
    monkeypatch.setattr(archive, 'comparison_input', lambda *args: (body, labels, evidence))

    async def model(*args, **kwargs):
        request = loads(kwargs['messages'][0]['content'])
        assert request.get('all_record_index') is None
        members = [item['record'] for item in request['items']]
        return {'checked_members': members}, {'attempt_id': 'synthetic-window'}

    service = SimpleNamespace(repo=repo, spec=lambda *args: {},
                              steps=SimpleNamespace(model=model), model_profile=lambda *args, **kw: profile)
    asyncio.run(archive.compare_results(service, {
        'task_id': 'synthetic',
        'payload': {'property_id': 'p', 'input_hash': 'hash', 'measurement_refs': []},
    }))
    report = saved[-1]
    assert report['state'] == 'partial'
    assert set(report['checked_members']) == set(labels)
    assert report['coverage']['global_index']['reason'] == 'comparison_global_index_input_limit'
    assert report['coverage']['uncovered_cross_window_scope'] is True


def test_comparison_window_repair_keeps_prior_version_and_publishes_new_findings(monkeypatch):
    body, labels, evidence = comparison_material()
    done = list(labels)[2:]
    initial = {
        'duplicates': [], 'suspicions': [], 'interpretation_issues': [], 'state': 'partial',
        'checked_members': done, 'diagnostics': [],
        'coverage': {
            'windows': [
                {'members': ['R1', 'R2'], 'checked_members': [], 'state': 'partial'},
                {'members': done, 'checked_members': done, 'state': 'checked'},
            ],
            'mode': 'evidence_windows_with_global_index',
            'global_index': {'state': 'indexed_not_scientifically_checked'},
            'cross_group_links': [],
        },
    }
    saved = []

    @contextmanager
    def tx():
        yield None

    repo = SimpleNamespace(read=tx, transaction=tx, validate_lease=lambda *a: None,
                           object=lambda *a: deepcopy(initial), objects=lambda *a: [],
                           put_object=lambda *a: saved.append((a[-2], a[-1])), finish_job=lambda *a: None)
    monkeypatch.setattr(archive, 'comparison_input', lambda *a: (body, labels, evidence))

    async def model(*args, **kwargs):
        request = loads(kwargs['messages'][0]['content'])
        assert [item['record'] for item in request['items']] == ['R1', 'R2']
        return {
            'checked_members': ['R1', 'R2'],
            'duplicates': [{'members': ['R1', 'R2'], 'evidence': ['E1', 'E2'],
                            'member_evidence': {'R1': ['E1'], 'R2': ['E2']},
                            'reason': 'Explicit adoption in the two originals', 'basis': 'explicit_adoption'}],
        }, {'attempt_id': 'saved-repair'}

    service = SimpleNamespace(repo=repo, spec=lambda *a: {}, steps=SimpleNamespace(model=model),
                              model_profile=lambda *a, **kw: ModelProfile('qwen3.7-plus', **kw))
    asyncio.run(archive.compare_results(service, {'task_id': 'synthetic', 'payload': {
        'property_id': 'p', 'input_hash': 'hash', 'measurement_refs': [], 'repair_windows': True}}))
    (version, updated), = saved
    assert version == 2 and updated['state'] == 'checked'
    assert set(updated['checked_members']) == set(labels)
    assert updated['duplicates'][0]['member_refs'] == [archive.reference(labels['R1']), archive.reference(labels['R2'])]
    assert initial['state'] == 'partial' and initial['coverage']['windows'][0]['state'] == 'partial'
