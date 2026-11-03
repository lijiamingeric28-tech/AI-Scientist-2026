"""The finite rewrite must consume a genuinely new model-selected branch."""
import asyncio
from astroquery_ai.science.metadata_variants import batch_plan
from tests.rebuild.test_two_tier_materials import carrier


def test_adaptive_reordered_terms_do_not_reopen_an_exhausted_ads_page(tmp_path,monkeypatch):
    from astroquery_ai.science.metadata_preparation import compile_metadata_query,metadata_query_key
    base={'names':['Alias B','Target A'],'core_terms':['quantity A','quantity B'],'synonyms':[],
          'phrases':['quantity A','quantity B'],'method_terms':[]}
    base['query']=compile_metadata_query(base)
    reordered=compile_metadata_query({'names':list(reversed(base['names'])), 'phrases':list(reversed(base['phrases']))})
    assert base['query']!=reordered
    assert metadata_query_key(base['query'])==metadata_query_key(reordered)
    assert metadata_query_key(base['query'])!=metadata_query_key(compile_metadata_query({'names':base['phrases'],'phrases':base['names']}))
    async def run():
        repo,tid,svc=carrier(tmp_path,count=0)
        spec=svc.spec(None,tid);spec['run_policy']['literature']['experiment']={'P':'P0','S':'S2'}
        async def plans(service,job,frozen,binding,*,rewrite=False,feedback=None):
            return dict(base,query=reordered,rewrite_useful=True) if rewrite else base
        monkeypatch.setattr('astroquery_ai.science.metadata_preparation.term_plan',plans)
        with repo.transaction() as c:repo.put_object(c,tid,'literature_search','old-page',1,
            {'property_id':'p','query':base['query'],'closed_reason':'provider_end'})
        result=await batch_plan(svc,repo.claim_job('check',task_id=tid),spec,spec['properties'][0],3)
        assert not result['rewrite_useful'] and result['query'] is None
    asyncio.run(run())


def test_rewrite_can_retain_direct_words_and_supply_one_new_method_query(tmp_path,monkeypatch):
    async def run():
        repo,tid,svc=carrier(tmp_path,count=0)
        spec=svc.spec(None,tid);spec['run_policy']['literature']['experiment']={'P':'P2','S':'S2'}
        main={'query':'original direct query','method_query':None,'names':['Synthetic target']}
        revised={**main,'rewrite_useful':True,'method_query':'new grounded method query'}
        calls=[]
        async def plans(service,job,frozen,binding,*,rewrite=False,feedback=None):
            calls.append(rewrite);return revised if rewrite else main
        monkeypatch.setattr('astroquery_ai.science.metadata_preparation.term_plan',plans)
        with repo.transaction() as c:repo.put_object(c,tid,'literature_search','original',1,
            {'property_id':'p','query':main['query'],'closed_reason':'provider_end'})
        result=await batch_plan(svc,repo.claim_job('rewrite',task_id=tid),spec,spec['properties'][0],3,
                                feedback={'evaluated':0,'metadata_eligible':0,'attempted':0,'readable':0})
        assert result['query']==revised['method_query'] and result['retrieval_branch']=='rewrite_method'
        assert calls==[False,True]
    asyncio.run(run())
