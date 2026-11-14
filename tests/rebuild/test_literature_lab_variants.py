"""Protocol binding and query compilation only; not scientific accuracy."""
import pytest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.metadata_variants import compile_concepts,checked_plan


def test_compositional_quantity_and_literal_names_preserve_both_sides():
    q=compile_concepts(['Object  A','Object A','Alias "quoted"'],'(line OR "line alpha") AND (delay OR response)')
    assert q.count('"Object A"')==1
    assert ' AND abs:((line OR "line alpha") AND (delay OR response))' in q
    assert q.endswith('AND doctype:(article OR eprint)')
    assert 'full:' not in q
    assert ' AND full:' in compile_concepts(['Object A'],'quantity',quantity_field='full')


@pytest.mark.parametrize('expression',['body:quantity','quantity OR full:other','references("paper")','NOT other',
    'quantity OR NOT other','quantity NOT full:other','*'])
def test_model_cannot_override_positive_quantity_side(expression):
    with pytest.raises(DomainError):compile_concepts(['Object A'],expression)


def test_actual_name_references_and_shared_name_plan_are_bound():
    names={'N1':'Database object A'}
    response={'search_names':[{'source_names':['N1'],'text':'Object A','basis':'same verified identifier typography'}],
              'properties':[{'property':'P1','base_quantity':'synthetic length of aggregate','direct_expression':'length','method_expression':None}]}
    assert checked_plan(response,names)['names']==['Object A']
    response['rewrite_useful']=False
    assert checked_plan(response,names)['query']  # Initial output is not a rewrite decision.
    assert checked_plan(response,names,rewrite=True)['rewrite_useful'] is False
    with pytest.raises(DomainError):checked_plan(response,{'N2':'Other'})
    with pytest.raises(DomainError):checked_plan(response,names,shared=[{'source_names':['N1'],'text':'Unchanged','basis':'known'}])


def test_retrieval_view_keeps_science_but_omits_mechanical_receipt_copying():
    from copy import deepcopy
    from astroquery_ai.science.metadata_variants import quantity_view
    binding={'definition':{'name_en':'Synthetic quantity','scope':'bounded_whole',
        'description':'Actual native quantity and estimator boundary',
        'definition_qualifiers':{'method':{'value':'Source-reported estimator','raw_description':'Actual method',
                                       'evidence_refs':[{'id':'source-hash','content_sha256':'a'*64}]}},
        'content_sha256':'b'*64}}
    before=deepcopy(binding);view=quantity_view(binding)
    assert view['final_scientific_boundary']['definition_qualifiers']['method']['value']=='Source-reported estimator'
    assert view['final_scientific_boundary']['description']=='Actual native quantity and estimator boundary'
    assert 'evidence_refs' not in view['final_scientific_boundary']['definition_qualifiers']['method']
    assert binding==before


def test_production_term_entry_uses_opt_in_variant_and_preserves_checkpoint(tmp_path):
    import asyncio
    from astroquery_ai.runtime.codec import loads
    from astroquery_ai.science.metadata_preparation import term_plan
    from tests.rebuild.test_two_tier_materials import carrier
    async def run():
        repo,tid,svc=carrier(tmp_path,count=0)
        spec=svc.spec(None,tid)
        spec['target']['target_id']='synthetic-target'
        spec['run_policy']['literature']['experiment']={'P':'P1'}
        calls=[]
        class Steps:
            async def model(self,execution,**kw):
                body=loads(kw['messages'][0]['content']);calls.append(body)
                assert body['verified_names']['N1']=='SYNTHETIC target'
                return {'search_names':[{'source_names':['N1'],'text':'SYNTHETIC target','basis':'exact supplied identifier'}],
                    'properties':[{'property':'P1','base_quantity':'synthetic length','direct_expression':'length',
                                   'method_expression':'method AND length','method_reason':'synthetic'}]}, {'attempt_id':'synthetic'}
        svc.steps=Steps();job=repo.claim_job('variant',task_id=tid)
        first=await term_plan(svc,job,spec,spec['properties'][0])
        again=await term_plan(svc,job,spec,spec['properties'][0])
        assert first==again and len(calls)==1
        assert first['method_query'] and first['prompt_version'].endswith('P1')
    asyncio.run(run())


def test_name_plans_share_only_declared_session_and_same_identity():
    from copy import deepcopy
    from astroquery_ai.science.metadata_variants import shared_name_id
    spec={'target':{'target_id':'synthetic','main_id':'Object A'},
          'module_experiment':{'experiment_id':'trial-a'},
          'run_policy':{'literature':{'experiment':{'P':'P1','name_plan_session':'session1'}}}}
    assert shared_name_id(spec,'task-a')==shared_name_id(spec,'task-b')
    changed=deepcopy(spec);changed['run_policy']['literature']['experiment']['name_plan_session']='session2'
    assert shared_name_id(spec,'task-a')!=shared_name_id(changed,'task-b')
    changed=deepcopy(spec);changed['target']['main_id']='Object B'
    assert shared_name_id(spec,'task-a')!=shared_name_id(changed,'task-a')
    del spec['run_policy']['literature']['experiment']['name_plan_session']
    changed=deepcopy(spec);changed['module_experiment']['experiment_id']='trial-b'
    assert shared_name_id(spec,'task-a')!=shared_name_id(changed,'task-a')
