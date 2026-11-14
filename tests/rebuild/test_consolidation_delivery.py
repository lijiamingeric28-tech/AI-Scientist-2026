"""Consolidation task-level scope, author format and archive boundaries."""
import json
from copy import deepcopy
import pytest
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.results.task_score import calculate,execution_fraction
from astroquery_ai.science.author_knowledge import inspect_author_package,assemble_insight_input,disabled_report
from astroquery_ai.science.archive_comparison import checked_reply


def test_comparison_view_retains_coordinates_all_errors_context_and_exact_shared_text():
    from astroquery_ai.science.archive_comparison import comparison_model_view
    errors={'state':'parsed','components':[{'raw_text':'±.02','values':{'delta':'.02'},'role':'statistical',
        'level':None,'unit_ref':{'id':'unit-dex','content_sha256':'hash'},'dependency_refs':[]},
        {'raw_text':'±.10','values':{'delta':'.10'},'role':'systematic','level':None}]}
    native={'raw_value':'.05','value':{'kind':'real','value':'.05'},'unit':'dex','representation':'log10','uncertainty':errors}
    processed={'value_typed':{'kind':'real','value':'.05'},'uncertainty_typed':errors,'main_state':'ready',
        'coordinate_units':{'source':'1','target':'1'},'scientific_operation':{'permission_receipts':'not evidence'},
        'validation_receipt':{'checks':['not comparison input']},'status':'ready'}
    item={'record':'R1','native':native,'processed':processed,'context':[{'key':'method','value':'actual method',
        'state':'known','check_ref':{'id':'technical'}}],'reported_references':[{'raw_code':'[7]',
        'role':'adoption','link_quote':'value adopted from [7]','resolved_work_ref':{'bibcode':'real-given-id'}}]}
    body={'items':[item], 'evidence':{'E1':{'record':'R1','source_id':'S1','locator':{'page':2},'text':'Exact original text.'},
        'E2':{'record':'R2','source_id':'S1','locator':{'page':2},'text':'Exact original text.'},
        'E3':{'record':'R3','source_id':'S2','locator':{'page':2},'text':'Exact original text.'}},'instruction':'JSON comparison.'}
    original=deepcopy(body);view=comparison_model_view(body)
    assert body==original
    assert view['items'][0]['native']['uncertainty']['components'][0]['values']=={'delta':'.02'}
    assert view['items'][0]['processed']['uncertainty_typed']['components'][1]['values']=={'delta':'.10'}
    assert view['items'][0]['processed']['coordinate_units']=={'source':'1','target':'1'}
    assert view['items'][0]['context']==[{'key':'method','value':'actual method','state':'known'}]
    assert view['items'][0]['reported_references'][0]['link_quote']=='value adopted from [7]'
    assert 'scientific_operation' not in view['items'][0]['processed']
    assert len(view['source_texts'])==2 and view['evidence']['E1']['text_ref']==view['evidence']['E2']['text_ref']
    assert view['evidence']['E3']['text_ref']!=view['evidence']['E1']['text_ref']
    assert all(view['source_texts'][e['text_ref']]=='Exact original text.' for e in view['evidence'].values())


def test_full_metadata_larger_than_csv_default_is_preserved_in_all_formats():
    from astroquery_ai.science.results.export_validation import verify_formats
    body={'delivery_id':'synthetic','snapshot_ref':{'id':'s','version':1,'content_sha256':'h'},
        'definitions':[],'measurements':[],'derived':[],'contexts':[],
        'workflow_contract':'backend-consolidation/1',
        'task_score':{'synthetic_large_scope_note':'scope '*30000}}
    result=verify_formats(body)
    assert result['state']=='passed' and len(result['formats'])==5
    assert result['formats']['csv_wide']['bytes']>131072


def test_five_format_check_reuses_exact_csv_in_package_without_second_transcription(monkeypatch):
    import io, zipfile
    from astroquery_ai.science.results import export_validation, exporting
    body={'delivery_id':'synthetic','snapshot_ref':{'id':'s','version':1,'content_sha256':'h'},
        'definitions':[],'measurements':[],'derived':[],'contexts':[]}
    calls=[];original=export_validation._serialize
    def record(body,fmt,**kwargs):
        calls.append((fmt,kwargs))
        return original(body,fmt,**kwargs)
    monkeypatch.setattr(export_validation,'_serialize',record)
    result=export_validation.verify_formats(body)
    assert result['state']=='passed'
    csv_bytes=next(kwargs['_csv_long'] for fmt,kwargs in calls if fmt=='package')
    assert csv_bytes==exporting._serialize(body,'csv_long')[0]
    raw,_=exporting._serialize(body,'package',_csv_long=csv_bytes)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read('measurements.csv')==csv_bytes
        assert json.loads(archive.read('delivery.json'))==body


def test_reading_scope_is_stable_under_batch_splits_and_retries():
    scope={'materials':[{'material_id':'paper:w','kind':'paper','ranges':[{'property_id':'p','page':1},{'property_id':'p','page':2}]}]}
    state={'work_id':'w','property_ids':['p'],'core_pages':[1,2],'coverage':'checked','closed':True}
    fraction,rows=execution_fraction(scope,[state,state],[])
    assert fraction==1 and rows[0]['expected_ranges']==2
    split=[{**state,'core_pages':[n]} for n in [1,2]]
    assert execution_fraction(scope,split,[])[0]==fraction
    assert execution_fraction(scope,[{**state,'coverage':'partial'}],[])[0]==0


def test_no_usable_results_are_zero_not_empty_denominator_full_marks(tmp_path):
    repo=Repository(tmp_path/'db');tid=repo.create_task('SYNTHETIC no materials')['task_id']
    spec={'spec_hash':'synthetic','properties':[{'property_id':'p'}]}
    snapshot={'measurements':[],'derived':[],'query':spec,'processing_receipts':[]}
    with repo.transaction() as c:score=calculate(repo,c,tid,spec,snapshot,delivery_verified=True)
    assert score['score']==0 and score['earned_points']==0 and score['possible_points']==95
    assert score['status']=='no_usable_results' and score['measurement_scores']==[]
    assert score['components'][1]['state']=='no_materials'
    assert score['excluded_scope']==[{'scope':'insights','weight':5,'state':'deferred_by_scope'}]


def test_all_in_scope_completion_is_100_without_claiming_insights(tmp_path):
    repo=Repository(tmp_path/'db');tid=repo.create_task('SYNTHETIC complete')['task_id']
    spec={'spec_hash':'synthetic','properties':[{'property_id':'p'}]}
    r={'measurement_id':'m','revision':1,'content_sha256':'x','property_ref':{'id':'p'}}
    snapshot={'query':spec,'measurements':[r],'derived':[{'measurement_id':'m','derived_id':'d','main_state':'ready'}],
        'processing_receipts':[{'input_ref':{'content_sha256':'x'},'output_ref':{'id':'d'},'checks':[{'target':'main_value','status':'passed'}]}]}
    with repo.transaction() as c:
        repo.put_object(c,tid,'completion_scope',tid,1,{'requested_properties':['p'],'materials':[
            {'material_id':'paper:w','kind':'paper','ranges':[{'property_id':'p','page':1}]}],
            'excluded_scope':[{'scope':'insights','weight':5,'state':'deferred_by_scope'}]})
        for n in range(20):repo.put_object(c,tid,'reading_allocation',str(n),1,{'work_id':str(n),'property_ids':['p']})
        repo.put_object(c,tid,'reading_batch_state','b',1,{'work_id':'w','property_ids':['p'],'core_pages':[1],'coverage':'checked','closed':True})
        repo.put_object(c,tid,'quality_candidate_root','r',1,{'root_id':'r'})
        repo.put_object(c,tid,'quality_decision','q',1,{'root_id':'r','state':'supported'})
        repo.put_object(c,tid,'archive_comparison','a',1,{'property_id':'p','measurement_refs':[
            {'id':'m','version':1,'content_sha256':'x'}],'state':'checked'})
        score=calculate(repo,c,tid,spec,snapshot,delivery_verified=True)
    assert score['earned_points']==95 and score['score']==100
    assert score['components'][-1]['earned'] is None


def test_old_pass_cannot_hide_a_new_current_quality_failure(tmp_path):
    repo=Repository(tmp_path/'db');tid=repo.create_task('SYNTHETIC current quality conclusion')['task_id']
    spec={'spec_hash':'s','properties':[{'property_id':'p'}]}
    with repo.transaction() as c:
        repo.put_object(c,tid,'quality_candidate_root','root',1,{'root_id':'root'})
        for cid,parent,state in [('old',None,'supported'),('current',{'id':'old'},'technical_failure')]:
            repo.put_object(c,tid,'quality_candidate_link',cid,1,{'candidate_ref':{'id':cid},'parent_ref':parent,'root_id':'root'})
            repo.put_object(c,tid,'quality_decision',cid,1,{'root_id':'root','candidate_ref':{'id':cid},'state':state})
        result=calculate(repo,c,tid,spec,{'query':spec,'measurements':[],'derived':[]},delivery_verified=False)
    assert result['components'][2]['candidate_roots']==1 and result['components'][2]['concluded_roots']==0


def author_fixture(tmp_path):
    ref={'id':'synthetic','version':1,'content_sha256':'synthetic'}
    inventory=[{'item_id':'item','otype':'*','property_id':'p','definition_ref':{'id':'p','version':'1','content_sha256':'d'},
        'output_profile_ref':{'id':'profile','version':'1','content_sha256':'o'}}]
    rows={'entries':[{'entry_id':'card','title':'合成内容','otypes':['*'],'property_topics':['test'],
        'conditions':['条件未知时仅作背景'],'blocks':[{'role':'meaning','text':'SYNTHETIC only','basis':'author_knowledge','source_ids':[]}]}],
        'sources':[{'source_id':'s','title':'合成引用','url':'https://example.org/reference','verification':'reference_only','locator':'','support_note':''}],
        'coverage':[{'item_id':'item','otype':'*','property_id':'p','entry_ids':['card'],'status':'covered','reason':'synthetic'}]}
    def write():
        for k,v in rows.items():(tmp_path/(k+'.jsonl')).write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in v),encoding='utf-8')
    write();return ref,inventory,rows,write


def test_author_format_preserves_labels_and_exact_versions_without_activation(tmp_path):
    ref,inventory,rows,write=author_fixture(tmp_path)
    package=inspect_author_package(tmp_path,inventory,registry_ref=ref,expected_registry_ref=ref)
    assert package['runtime_authorized'] is False and package['scientific_review_claimed'] is False
    assert package['entries'][0]['blocks'][0]['basis']=='author_knowledge'
    delivery={'definitions':[{'property_id':'p','definition':{'property_id':'p','version':'1','content_sha256':'d'},
        'output_profile':{'profile_id':'profile','version':1,'content_sha256':'o'}}],
        'snapshot_ref':ref,'measurements':[],'derived':[],'contexts':[],'evidence_index':[],'delivery_id':'delivery'}
    assembled=assemble_insight_input(delivery,package)
    assert not assembled['generation_enabled'] and len(assembled['knowledge_candidates'])==1
    delivery['definitions'][0]['definition']['content_sha256']='other'
    # R13: another legitimate inventory variant is not a whole-package error;
    # it is excluded from this exact delivery, never silently rebound.
    mismatch=assemble_insight_input(delivery,package)
    assert mismatch['knowledge_candidates']==[] and mismatch['inapplicable_bindings'][0]['item_id']=='item'
    disabled=disabled_report(delivery)
    assert disabled['units']==disabled['paragraphs']==[] and disabled['model_calls']==0
    assert disabled['status']=='disabled_pending_content' and disabled['snapshot_ref']==ref


@pytest.mark.parametrize('failure',['reference_only','wrong_item','wrong_type','version'])
def test_author_rejects_bad_evidence_bindings_and_registry_versions(tmp_path,failure):
    ref,inventory,rows,write=author_fixture(tmp_path)
    if failure=='reference_only':rows['entries'][0]['blocks'][0].update(basis='source_checked',source_ids=['s'])
    elif failure=='wrong_item':rows['coverage'][0]['item_id']='unknown'
    elif failure=='wrong_type':rows['entries'][0]['otypes']=['Psr']
    write()
    with pytest.raises(DomainError):inspect_author_package(tmp_path,inventory,registry_ref=ref,
        expected_registry_ref={**ref,'version':2} if failure=='version' else ref)


def test_archive_verifies_coverage_actual_members_and_evidence_without_numeric_rules():
    labels={'R1':{},'R2':{}};evidence={'E1':{'record':'R1'},'E2':{'record':'R2'}}
    raw={'duplicates':[{'members':['R1','R2'],'evidence':['E1','E2'],'reason':'SYNTHETIC same original result, multiple locations',
        'basis':'repeated_author_result','member_evidence':{'R1':['E1'],'R2':['E2']}}],
        'suspicions':[],'interpretation_issues':[],'checked_members':['R1','R2'],'limitations':[]}
    assert len(checked_reply(raw,labels,evidence).duplicates)==1
    raw['checked_members']=['R1']
    with pytest.raises(DomainError):checked_reply(raw,labels,evidence)
    raw['checked_members']=['R1','R2'];raw['duplicates'][0]['members']=['R1','other']
    with pytest.raises(DomainError):checked_reply(raw,labels,evidence)
