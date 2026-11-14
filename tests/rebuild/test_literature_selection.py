import pytest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.literature import compile_queries
from astroquery_ai.science.literature_selection import checked_query, checked_relevance, relevant_queues, relevance_outcome, relevance_bindings


def spec():
    return {'target':{'main_id':'V* synthetic', 'aliases':['catalog 1'],
        'submitted_mentions':['synthetic star']}, 'properties':[{'property_id':'p','definition':{
            'description':'SYNTHETIC whole quantity','value_schema':{'kind':'real'}}}]}


def test_checked_names_keep_verified_submitted_name_without_invented_alias():
    from tests.rebuild.test_ads_model_expressions import row,spec as query_spec,families
    response={'queries':[row(),row('body')]}
    assert len(checked_query(response,query_spec(),families()))==2
    response['queries'][0]['names']=['made-up short name']
    with pytest.raises(DomainError):checked_query(response,query_spec(),families())


def test_api_query_never_uses_unsupported_object_or_active_name_wildcard():
    plans = compile_queries(['V* synthetic','catalog 1'],[{'family_id':'f',
        'selected_property_ids':['p'],'search_concepts':['temperature']}])
    assert all('object:' not in p['query'] for p in plans)
    assert all('=abs:' in p['query'] and 'V\\* synthetic' in p['query'] for p in plans)
    assert all(p['compiler_version'] == 'ads-literal-identity-2' for p in plans)
    assert {p['layer'] for p in plans}=={'metadata','body'}
    assert all('temperature' in p['query'] for p in plans)


def test_relevance_preserves_plausible_multiobject_and_rejects_wrong_subject():
    works=[{'work_id':'a','records':[{'bibcode':'a','titles':['Spectra of young stars'],'abstract':None}],
        'allowed_property_ids':['p'],'family_ids':['f']},
        {'work_id':'b','records':[{'bibcode':'b','titles':['Galaxy redshifts'],'abstract':None}],
        'allowed_property_ids':['p'],'family_ids':['f']}]
    response={'works':[{'id':'W1','decision':'needs_fulltext','properties':['P1'],
        'evidence':['E1'],'reason':'plausible population; target list in full text'},
        {'id':'W2','decision':'unrelated','properties':[],
         'evidence':['E2'],'reason':'wrong physical subject'}]}
    decisions=checked_relevance(response,works,spec())
    assert relevant_queues({'f':['b','a']},works,decisions)=={'f':['a']}
    assert decisions['a']['evidence_quote']=='Spectra of young stars'
    response['works'][0]['evidence']=['E2']
    checked=relevance_outcome(response,works,spec())
    assert checked['unresolved_ids']==['a'] and list(checked['decisions'])==['b']
    response['works'][0].update(properties=[],evidence=[])
    assert checked_relevance(response,works,spec())['a']['property_ids']==['p']


def test_bad_tag_and_duplicate_do_not_erase_other_items_or_guess_identity():
    works=[{'work_id':f'hash-{i}','records':[{'bibcode':str(i),'titles':[f'Source {i}']}]} for i in range(3)]
    row=lambda tag:{'id':tag,'decision':'needs_fulltext','properties':['P1'],'evidence':[],'reason':'check fulltext'}
    out=relevance_outcome({'works':[row('W3'),row('W1'),row('W999')]},works,spec())
    assert set(out['decisions'])=={'hash-0','hash-2'} and out['unresolved_ids']==['hash-1']
    out=relevance_outcome({'works':[row('W1'),row('W1'),row('W3')]},works,spec())
    assert set(out['decisions'])=={'hash-2'} and set(out['unresolved_ids'])=={'hash-0','hash-1'}
    scope,_=relevance_bindings(spec(),works)
    with pytest.raises(DomainError):
        relevance_outcome({'works':[row('W1')]},list(reversed(works)),spec(),scope=scope)


def test_repair_subset_keeps_original_labels():
    works=[{'work_id':str(i),'records':[{'bibcode':str(i),'titles':[str(i)]}]} for i in range(3)]
    scope,_=relevance_bindings(spec(),works)
    out=relevance_outcome({'works':[{'id':'W3','decision':'needs_fulltext','properties':['P1'],
        'evidence':['E3'],'reason':'plausible'}]},works,spec(),scope=scope,only_ids={'2'})
    assert set(out['decisions'])=={'2'} and out['unresolved_ids']==[]


def test_partial_batches_survive_repair_failure_and_restart_without_repaying(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.runtime.codec import loads
    from astroquery_ai.science.workflow.literature_service import LiteratureService
    repo=Repository(tmp_path/'runtime.sqlite3')
    tid=repo.create_task('SYNTHETIC literature partial-checkpoint test')['task_id']
    with repo.transaction() as conn:
        repo.mutate_task(conn,tid,lifecycle='running',science_state='open')
        repo.enqueue(conn,tid,'M04','literature_discover',{})
    job=repo.claim_job('worker',lease_seconds=600)
    works=[{'work_id':str(i),'records':[{'bibcode':str(i),'titles':[f'SYNTHETIC source {i}']}]} for i in range(12)]
    calls=[]
    class Steps:
        async def model(self,execution,**kwargs):
            calls.append(kwargs)
            prompt=next(loads(m['content']) for m in kwargs['messages'] if m['content'].startswith('{') and 'works' in loads(m['content']))
            rows=prompt['works']
            results=[{'id':r['id'],'decision':'needs_fulltext','properties':['P1'],
                'evidence':[],'reason':'SYNTHETIC plausible fulltext'} for r in rows
                if r['records'][0]['bibcode'] not in {'10','11'}]
            if len(rows)==12:results[3]['id']='damaged-full-hash-not-a-tag'
            return {'works':results},{'attempt_id':'synthetic'}
    service=LiteratureService(SimpleNamespace(app=None,repo=repo,steps=Steps(),extractor=None))
    async def run():
        first=await service.assess_works(job,spec(),works)
        assert len(calls)==2
        assert all(first[str(i)]['decision']=='needs_fulltext' for i in range(10))
        assert all(first[str(i)]['decision']=='not_checked' for i in [10,11])
        repair=next(loads(m['content']) for m in calls[1]['messages'] if m['content'].startswith('{'))
        assert [x['id'] for x in repair['works']]==['W4','W11','W12']
        second=await service.assess_works(job,spec(),works)
        assert second==first and len(calls)==2
        with repo.read() as conn:
            assert len(repo.objects(conn,tid,'literature_item_evaluation'))==10
            assert conn.execute('select count(*) from reviews').fetchone()[0]==0
    asyncio.run(run())
