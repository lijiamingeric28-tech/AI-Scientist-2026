"""New synthetic software boundaries; no real-source accuracy claims."""
import asyncio
import base64
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from astroquery_ai.runtime.codec import canonical,digest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.storage import ArtifactStore
from astroquery_ai.runtime.run_policy import LEGACY_RUN_POLICY as NORMAL_RUN_POLICY
from astroquery_ai.science.literature import FairReadLedger
from astroquery_ai.science.workflow.context import ScienceContext
from astroquery_ai.science.workflow.paper_service import PaperService
from astroquery_ai.science.paper_admission import page_blocks
from astroquery_ai.science.qualification import qualify_source
from tests.rebuild.registry_fixture import make_release


def fixture(tmp_path, mode):
    repo=Repository(tmp_path/'runtime.sqlite3')
    tid=repo.create_task('SYNTHETIC bounded source reading')['task_id']
    data=make_release(tmp_path/'synthetic-registry')
    definition=data['definitions'][0]; pid=definition['property_id']
    spec={'task_id':tid,'spec_id':'synthetic-spec','target':{'target_id':'synthetic-target',
        'main_id':'SYNTHETIC_AQ','aliases':[]},'properties':[{'property_id':pid,
        'definition':definition,'output_profile':data['output-profiles'][0]}],
        'dependencies':[],'registry_release':{'id':'synthetic-registry'},'run_policy':NORMAL_RUN_POLICY}
    spec['spec_hash']=digest(spec)
    store=ArtifactStore(tmp_path/'artifacts',repo)
    artifact=store.write(b'%PDF-SYNTHETIC only, renderer is mocked','application/pdf')
    source,qualification=qualify_source({'source_id':'synthetic-source','kind':'paper','artifact':artifact,
        'title':['SYNTHETIC source'], 'version_grade':'unknown',
        'work':{'allowed_property_ids':[pid],'records':[{}]}},
        identity={'state':'SYNTHETIC'},checked_scope=['SYNTHETIC only'])
    text='SYNTHETIC_AQ has a measured synthetic whole length of 0 m.'
    index={'page_count':1,'pages':[{'page':1,'text':text,'height':800,'width':600}]}
    ledger=FairReadLedger(['f'],{'f':[source['source_id']]},{source['source_id']:['f']});ledger.select()
    with repo.transaction() as conn:
        ref=repo.put_object(conn,tid,'confirmed_query',spec['spec_id'],1,spec)
        repo.mutate_task(conn,tid,lifecycle='running',science_state='open',query_ref=canonical(ref).decode())
        store.register(conn,tid,'synthetic',artifact)
        repo.put_object(conn,tid,'source',source['source_id'],1,source)
        repo.put_object(conn,tid,'qualification',qualification['qualification_id'],1,qualification)
        repo.put_object(conn,tid,'document_index',source['source_id'],1,index)
        repo.put_object(conn,tid,'read_ledger',tid,1,asdict(ledger))
        repo.put_object(conn,tid,'reader_profile_pin',tid,1,{'settings':{
            'primary_model':'qwen3.8-flash','fallback_model':'qwen3.7-plus','core_batch_pages':4}})
        repo.enqueue(conn,tid,'M06','paper_batch',{'work_id':source['source_id'],'core_pages':[1],
            'artifact_ref':artifact['artifact_id'],'property_ids':[pid],'reading_batch_id':'synthetic-batch'})
    png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5uUAAAAASUVORK5CYII=')
    calls=[]
    async def parse(*args,**kwargs):return png
    async def model(**kwargs):
        calls.append(kwargs)
        if mode=='fail':raise DomainError('INVALID_MODEL_JSON','SYNTHETIC invalid JSON')
        if kwargs['profile'].operation=='paper_batch':
            results=[]
            if mode=='value':
                results=[{'property_id':'P1','value':{'kind':'real','value':'0'},'raw_value':'0',
                    'unit':'m','representation':'linear','source_quote':text,'page':1,
                    'subject_role':'target','result_role':'reported_result','location_kind':'body',
                    'limit':'none','errors':[],'conditions':[],'ambiguity':None}]
            return {'results':results,'coverage':'checked','limitations':[]}, {'attempt_id':'synthetic-read'}
        if kwargs['profile'].operation=='paper_admission':
            content=kwargs['messages'][0]['content'];payload=__import__('json').loads(content if isinstance(content,str) else content[0]['text'])
            block=next(b for b in payload['source_blocks'] if 'SYNTHETIC_AQ' in b['text'])
            anchor={'page':1,'block_ids':[block['block_id']]}
            return {'items':[{'item_id':item['item_id'],'native_representation':'linear','value_match':'exact',
                'assessment':{'index':i,'subject':'target','printed_subject':'SYNTHETIC_AQ',
                    'subject_evidence':[anchor],'result_role':'reported_result','role_evidence':[anchor],
                    'quantity_match':'exact','quantity_evidence':[anchor],'native_unit':'m',
                    'quantity_identity':{'reported_quantity':'synthetic whole length','subject_scale':'whole synthetic target',
                        'native_representation':'linear','relation':'same','evidence':[anchor]},
                    'unit_match':'exact','unit_evidence':[anchor],'reason':'SYNTHETIC original evidence'},
                'source_quality':{'state':'checked','raw_info':[block['block_id']],'caution_quotes':[],
                                  'note':'SYNTHETIC original inspected'}} for i,item in enumerate(payload['items'])],
                'same_results':[],'limitations':[]}, {'attempt_id':'synthetic-review'}
        raise AssertionError('Unexpected additional model operation')
    app=SimpleNamespace(root=tmp_path,repository=repo,artifacts=store,parse_owned=parse,
        models=SimpleNamespace(json=model),_profile_state=lambda owner:'validated')
    return app,PaperService(ScienceContext(app)),tid,calls


@pytest.mark.parametrize('mode,expected_calls',[('empty',1),('fail',2)])
def test_empty_or_two_errors_close_without_children_or_human(tmp_path,mode,expected_calls):
    async def run():
        app,service,tid,calls=fixture(tmp_path,mode)
        job=app.repository.claim_job('worker',lease_seconds=600)
        await service.extract_paper(job)
        with app.repository.read() as conn:
            assert len(calls)==expected_calls
            assert conn.execute("SELECT count(*) FROM jobs WHERE task_id=? AND kind='paper_batch'",(tid,)).fetchone()[0]==1
            assert conn.execute('SELECT count(*) FROM reviews WHERE task_id=?',(tid,)).fetchone()[0]==0
            assert not app.repository.objects(conn,tid,'measurement')
            assert app.repository.objects(conn,tid,'reading_batch_state')[0]['closed']
        assert all(c['profile'].model=='qwen3.8-flash' for c in calls)
    asyncio.run(run())


def test_candidate_waits_for_one_independent_work_property_review(tmp_path):
    async def run():
        app,service,tid,calls=fixture(tmp_path,'value')
        repo=app.repository;job=repo.claim_job('worker',lease_seconds=600)
        await service.extract_paper(job)
        with repo.transaction() as conn:
            assert not repo.objects(conn,tid,'measurement')
            candidate=repo.objects(conn,tid,'candidate')[0]
            ref={'kind':'candidate','id':candidate['candidate_id'],'version':1,'content_sha256':__import__('astroquery_ai.runtime.codec',fromlist=['content_hash']).content_hash(candidate)}
            repo.enqueue(conn,tid,'M06','source_reconcile',{'work_id':'synthetic-source',
                'property_id':candidate['proposal']['property_id'],'items':[ref],'consolidated_review':True})
        while (review:=repo.claim_job('worker',lease_seconds=600)) and review['kind']!='source_reconcile':
            with repo.transaction() as conn:repo.finish_job(conn,review)
        await service.reconcile_source(review)
        with repo.read() as conn:
            records=repo.objects(conn,tid,'measurement')
            assert len(records)==1 and records[0]['raw_value']=='0' and records[0]['unit']=='m'
            assert records[0]['uncertainty']['components']==[]
            assert repo.objects(conn,tid,'source_check')[0]['state']=='checked'
        assert [c['profile'].operation for c in calls]==['paper_batch','paper_admission']
        assert calls[1]['profile'].model=='qwen3.7-plus'
    asyncio.run(run())


def test_initial_capacity_plan_does_not_split_after_failure():
    from astroquery_ai.science.papers.acquisition import initial_core_batches
    pages=[{'page':i,'text':'native '*100} for i in range(1,10)]
    assert list(initial_core_batches({'pages':pages}))==[[1,2,3,4],[5,6,7,8],[9]]
    pages[0]['text']=''
    assert list(initial_core_batches({'pages':pages}))[0]==[1,2]


def test_truncation_retains_only_complete_objects():
    from astroquery_ai.runtime.calls import complete_extraction_items
    assert complete_extraction_items('{"results":[{"a":1},{"a":"unfinished') == {
        'results':[{'a':1}],'coverage':'partial','limitations':['provider_output_truncated_complete_items_only'],
        'context_requests':[],'figures':[],'figure_requests':[]}
    assert complete_extraction_items('{"results":[{"value":') is None


def test_same_work_parallel_batches_still_obey_stage_and_four_limit():
    from astroquery_ai.runtime.stages import eligible
    def batch(i):return {'owner':'M06','kind':'paper_batch','payload':{
        'work_id':'synthetic-work','reading_batch_id':str(i)},'job_id':str(i)}
    running=[batch(i) for i in range(3)]
    assert eligible(batch(3),running,{'stage_id':'extraction'})
    assert not eligible(batch(4),[*running,batch(3)],{'stage_id':'extraction'})
    assert not eligible(batch(3),running,{'stage_id':'quality'})


def test_citation_book_lookup_is_bibliography_not_scientific_search():
    from astroquery_ai.science.papers.references import bibliography_entries,matching_entries,bibliography_query
    index={'pages':[{'text':'Measured value 1.2.\nReferences\n[1] Smith, A. 2020, A&A, 600, A1\n[2] Jones, B. 2021, 10.1234/real-entry'}]}
    entries=bibliography_entries(index)
    assert matching_entries('[1]',entries)==[entries[0]]
    assert bibliography_query(entries[1])==('doi:"10.1234/real-entry"','doi:10.1234/real-entry')
    assert bibliography_query(entries[0])[0]=='author:"Smith" year:2020'
    assert not bibliography_entries({'pages':[{'text':'No bibliography in owned text'}]})


def test_citation_enrichment_is_once_one_hop_and_cannot_add_measurement(tmp_path):
    async def run():
        app,service,tid,calls=fixture(tmp_path,'empty')
        repo=app.repository
        first=repo.claim_job('worker',lease_seconds=600)
        await service.extract_paper(first)
        quote='The length was adopted from [1].'
        index={'pages':[{'page':1,'text':quote+'\nReferences\n[1] Smith, A. 2020, doi:10.1234/example'}]}
        with repo.transaction() as c:
            repo.put_object(c,tid,'document_index','synthetic-source',2,index)
            for n in range(2):
                repo.put_object(c,tid,'reported_source_ref',str(n),1,{'reference_id':str(n),
                    'source_ref':{'id':'synthetic-source'},'raw_code':'[1]','link_quote':quote,
                    'measurement_id':'synthetic-not-a-new-measurement','revision':1})
            repo.enqueue(c,tid,'M06','citation_enrich',{'work_id':'synthetic-source'})
        http_calls=[]
        async def request(*args,**kwargs):
            http_calls.append(kwargs)
            assert kwargs['params']['q']=='doi:"10.1234/example"'
            assert 'reference' not in kwargs['params']['fl']
            return canonical({'response':{'docs':[{'bibcode':'2020SYNTHETIC....1S',
                'doi':['10.1234/example'],'title':['SYNTHETIC cited work'],'abstract':'SYNTHETIC background'}]}}),{}
        app.configuration=SimpleNamespace(runtime={'ads_api_token':'SYNTHETIC not a secret'})
        app.http=SimpleNamespace(request=request)
        while (job:=repo.claim_job('worker',lease_seconds=600)) and job['kind']!='citation_enrich':
            with repo.transaction() as c:repo.finish_job(c,job)
        await service.enrich_references(job)
        with repo.read() as c:
            assert len(http_calls)==1
            assert len(repo.objects(c,tid,'cited_work'))==1
            assert all(r['resolution_state']=='resolved' and not r['grants_reading'] for r in repo.objects(c,tid,'reported_source_ref'))
            assert not repo.objects(c,tid,'measurement')
            assert not c.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind='acquire_work'",(tid,)).fetchone()
    asyncio.run(run())


def test_parse_cache_coalesces_independent_callers_and_preserves_ownership(tmp_path):
    async def run():
        from astroquery_ai.application.service import Application
        app=Application(tmp_path)
        tid=app.repository.create_task('SYNTHETIC parser cache')['task_id']
        artifact=app.artifacts.write(b'SYNTHETIC parser input','text/plain')
        with app.repository.transaction() as c:app.artifacts.register(c,tid,'source',artifact)
        calls=[]
        async def parse(*args,**kwargs):
            calls.append(args)
            await asyncio.sleep(.02)
            return {'native':'SYNTHETIC original'}
        app.parsers=SimpleNamespace(run=parse)
        got=await asyncio.gather(*(app.parse_owned(tid,artifact['artifact_id'],'test_parse') for _ in range(4)))
        assert len(calls)==1 and all(v==got[0] for v in got)
        got[0]['native']='edited caller copy'
        assert (await app.parse_owned(tid,artifact['artifact_id'],'test_parse'))['native']=='SYNTHETIC original'
        other=app.repository.create_task('SYNTHETIC unowned')['task_id']
        with pytest.raises(DomainError):await app.parse_owned(other,artifact['artifact_id'],'test_parse')
    asyncio.run(run())


def test_same_cell_unknown_roles_keep_both_error_components():
    from astroquery_ai.science.measurements.contracts import ErrorProposal
    from astroquery_ai.science.measurements.uncertainty_components import assemble_uncertainties
    errors=[ErrorProposal(location='SYNTHETIC one cell',raw_text=raw,kind='symmetric_delta',
        values={'delta':value},role='unspecified',meaning='reported_error',interpretation_state='parsed',reason=None
        ).model_dump(mode='json') for raw,value in [('±0.02','0.02'),('(±0.10)','0.10')]]
    ref={'id':'synthetic','version':1,'content_sha256':'a'*64}
    result=assemble_uncertainties(doc={'errors':errors,'unit':'dex','representation':'log10','value':{'kind':'real','value':'0.05'}},
        source={},owner='M06',mid='synthetic-measurement',evref=ref,ur=ref,ir=ref,component_parent_ids=None)
    components=result[0]
    assert len({c['component_id'] for c in components})==2
    assert [c['values']['delta'] for c in components]==['0.02','0.10']
    assert all(c['role']=='unspecified' and c['level'] is None for c in components)


def test_dimensionless_coordinate_declaration_keeps_missing_printed_unit():
    from astroquery_ai.science.unit_declarations import dimensionless_coordinate_declaration
    from astroquery_ai.runtime.models import SourceUnitDeclaration
    anchor={'page':1,'block_ids':['p1:l1-1'],'quote':None}
    verification={'state':'passed','dimensionless_native_coordinate':{'kind':'source_evidenced_log_ratio'},
        'check':{'quantity_match':'exact','unit_match':'not_applicable','native_unit':None,'quantity_evidence':[anchor]},
        'source_information_blocks':[{'page':1,'block_id':'p1:l1-1','text':'SYNTHETIC original log ratio definition'}]}
    record=dimensionless_coordinate_declaration({'unit':None,'representation':'log10'},
        {'output_profile':{'unit':{'kind':'dimensionless'}}},verification,
        {'id':'synthetic-artifact','version':1,'content_sha256':'a'*64})
    parsed=SourceUnitDeclaration.model_validate(record)
    assert parsed.raw_unit_text is None and parsed.source_literal is None and parsed.canonical_symbol=='1'
    assert dimensionless_coordinate_declaration({'unit':None,'representation':'linear'},
        {'output_profile':{'unit':{'kind':'physical'}}},verification,{}) is None


def test_failed_local_review_repair_keeps_first_valid_item(tmp_path):
    async def run():
        from copy import deepcopy
        from astroquery_ai.runtime.codec import content_hash
        app,service,tid,calls=fixture(tmp_path,'value');repo=app.repository
        job=repo.claim_job('worker',lease_seconds=600);await service.extract_paper(job)
        with repo.transaction() as c:
            first=repo.objects(c,tid,'candidate')[0];extra=deepcopy(first)
            extra['candidate_id']='synthetic-missing-item'
            extra['proposal'].update(value={'kind':'real','value':'1'},raw_value='1')
            repo.put_object(c,tid,'candidate',extra['candidate_id'],1,extra)
            refs=[{'kind':'candidate','id':v['candidate_id'],'version':1,'content_sha256':content_hash(v)} for v in [first,extra]]
            repo.enqueue(c,tid,'M06','source_reconcile',{'work_id':'synthetic-source',
                'property_id':first['proposal']['property_id'],'items':refs,'consolidated_review':True})
        original=app.models.json;review_calls=[]
        async def model(**kw):
            review_calls.append(kw)
            if len(review_calls)>1:raise DomainError('INVALID_MODEL_JSON','SYNTHETIC local repair failure')
            body,receipt=await original(**kw)
            body['items']=body['items'][:1]
            return body,receipt
        app.models.json=model
        while (review:=repo.claim_job('worker',lease_seconds=600)) and review['kind']!='source_reconcile':
            with repo.transaction() as c:repo.finish_job(c,review)
        await service.reconcile_source(review)
        with repo.read() as c:
            assert len(review_calls)==2
            records=repo.objects(c,tid,'measurement')
            assert len(records)==1 and records[0]['value']['value']=='0'
            assert 'local_repair_failed:INVALID_MODEL_JSON' in repo.objects(c,tid,'source_recheck')[0]['limitations']
    asyncio.run(run())


def test_empty_read_can_carry_an_actual_scoped_note_without_another_call(tmp_path):
    async def run():
        import json
        app,service,tid,calls=fixture(tmp_path,'empty');original=app.models.json
        async def model(**kw):
            body,receipt=await original(**kw)
            content=kw['messages'][0]['content']
            payload=json.loads(content if isinstance(content,str) else content[0]['text'])
            # Use the actual visible native source ID, never a copied summary.
            block=payload['source_blocks'][0] if 'source_blocks' in payload else None
            if block is None:
                from astroquery_ai.science.paper_admission import page_blocks
                block=page_blocks({1:'SYNTHETIC_AQ has a measured synthetic whole length of 0 m.'})[0]
            body['source_notes']=[{'block_ids':[block['block_id']],'kind':'definition'}]
            return body,receipt
        app.models.json=model
        await service.extract_paper(app.repository.claim_job('worker',task_id=tid))
        with app.repository.read() as c:
            notes=app.repository.objects(c,tid,'reading_context_note')
            assert len(notes)==1 and notes[0]['blocks'][0]['text'].startswith('SYNTHETIC_AQ')
            assert not app.repository.objects(c,tid,'measurement')
        assert len(calls)==1
    asyncio.run(run())


def test_evidenced_different_quantity_rejection_does_not_become_an_identity_protocol_gap(tmp_path):
    async def run():
        app,service,tid,calls=fixture(tmp_path,'value');repo=app.repository
        await service.extract_paper(repo.claim_job('worker',task_id=tid,lease_seconds=600))
        with repo.transaction() as c:
            candidate=repo.objects(c,tid,'candidate')[0]
            from astroquery_ai.runtime.codec import content_hash
            repo.enqueue(c,tid,'M06','source_reconcile',{'work_id':'synthetic-source',
                'property_id':candidate['proposal']['property_id'],'consolidated_review':True,
                'items':[{'kind':'candidate','id':candidate['candidate_id'],'version':1,'content_sha256':content_hash(candidate)}]})
        original=app.models.json
        async def model(**kw):
            response,receipt=await original(**kw)
            for item in response.get('items',[]):
                item['assessment'].update(quantity_match='different')
                item['assessment'].pop('quantity_identity',None)
            return response,receipt
        app.models.json=model
        while (job:=repo.claim_job('worker',task_id=tid,lease_seconds=600)) and job['kind']!='source_reconcile':
            with repo.transaction() as c:repo.finish_job(c,job)
        await service.reconcile_source(job)
        with repo.read() as c:
            outcomes=repo.objects(c,tid,'source_recheck')[0]['outcomes']
            assert outcomes[0]['verification']['state']=='rejected'
            assert outcomes[0]['verification']['reason']=='different_reported_measurand'
            assert not repo.objects(c,tid,'measurement')
        assert len(calls)==2  # Read + one review, no repair for a valid exclusion.
    asyncio.run(run())
