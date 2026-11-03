"""No-cost checks of user settings, frozen requests and actual material-controller quotas."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from astroquery_ai.application.service import Application
from astroquery_ai.runtime.configuration import Configuration
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.retrieval_preferences import papers_value, readable_target, resolve_preferences
from astroquery_ai.runtime.run_policy import request_policy, RESEARCH_DELIVERY_POLICY
from astroquery_ai.science.feedback_retrieval import download_feedback, apply_local_grant
from astroquery_ai.science.literature_preparation import prepare, schedule
from tests.rebuild.test_two_tier_materials import carrier, settle_synthetic_downloads


@pytest.mark.parametrize('value',[0,-1,41,1.5,True,None,'','2.0',' 15','1e1','１５'])
def test_invalid_target_is_rejected(value):
    with pytest.raises(DomainError): papers_value(value)


def test_preferences_freeze_together_and_do_not_mutate_templates():
    before=deepcopy(RESEARCH_DELIVERY_POLICY)
    cfg=SimpleNamespace(runtime={'research_delivery_version':'research-delivery/1','ads_sort':'date desc','literature_papers_per_property':'15'})
    selected=resolve_preferences(cfg)
    cfg.runtime.update(ads_sort='read_count desc',literature_papers_per_property='30')
    policy=request_policy(cfg, selected)
    assert policy['literature']['selected_limit']==15 and policy['literature']['sort']=='date desc'
    assert policy['scoring']['readable_target_per_property']==15
    assert RESEARCH_DELIVERY_POLICY==before
    assert readable_target({})==20


def test_create_records_preferences_without_changing_global_default(tmp_path,monkeypatch):
    monkeypatch.setattr(Configuration,'effective',staticmethod(lambda saved:dict(saved)))
    app=Application(tmp_path,allow_synthetic=True)
    app.configuration.runtime={'ads_sort':'date desc','literature_papers_per_property':'20'}
    tid=str(uuid4())
    app.create('SYNTHETIC query',tid,{'papers_per_property':10,'ads_sort':'score desc'})
    app.configuration.runtime.update(ads_sort='citation_count desc',literature_papers_per_property='30')
    # A retried operation must reuse the original draft, even if defaults changed.
    app.create('SYNTHETIC query',tid)
    with app.repository.read() as c:
        draft=app.repository.object(c,tid,'draft',tid)
        policy=request_policy(app.configuration,draft['retrieval_preferences'])
        assert draft['retrieval_preferences']=={'papers_per_property':10,'ads_sort':'score desc'}
        assert policy['literature']['selected_limit']==10
        assert policy['literature']['sort']=='score desc'
    assert app.configuration.runtime['literature_papers_per_property']=='30'


def test_config_preferences_do_not_modify_saved_credentials(tmp_path,monkeypatch):
    monkeypatch.setattr(Configuration,'effective',staticmethod(lambda saved:dict(saved)))
    cfg=Configuration(tmp_path)
    cfg.save({'dashscope_api_key':'SYNTHETIC','ads_api_token':'SYNTHETIC','dashscope_base_url':'https://example.org/compatible-mode/v1','unpaywall_email':'a@example.org'},1)
    cfg.activate(); identity=cfg.connection_identity()
    cfg.save({'literature_papers_per_property':'30','ads_sort':'date desc'},2);cfg.activate()
    assert cfg.connection_identity()==identity
    assert cfg.public()['setup_complete'] and not cfg.public()['restart_required']
    assert cfg.runtime['dashscope_api_key']=='SYNTHETIC'
    assert resolve_preferences(Configuration(tmp_path))=={'papers_per_property':30,'ads_sort':'date desc'}
    with pytest.raises(DomainError): cfg.save({'literature_papers_per_property':'10'},2)


@pytest.mark.parametrize('target',[10,15,20,30])
def test_controller_replaces_failures_and_freezes_shared_allocations(tmp_path,target):
    async def run():
        repo,tid,service=carrier(tmp_path,properties=('p','q'),count=target+3)
        spec=service.spec(None,tid);spec['run_policy']['literature']['selected_limit']=target
        await prepare(service,repo.claim_job('prepare',task_id=tid,lease_seconds=600))
        with repo.read() as c:
            assert c.execute("select count(*) from jobs where task_id=? and kind='acquire_work'",(tid,)).fetchone()[0]==target
        settle_synthetic_downloads(repo,tid,fail={'w0','w1'})
        with repo.transaction() as c:
            repo.put_object(c,tid,'acquisition_result','w1',2,{'work_id':'w1','state':'skipped','reason':'PDF_PHYSICAL_PAGE_LIMIT'})
            schedule(repo,c,tid)
        await prepare(service,repo.claim_job('prepare',task_id=tid,lease_seconds=600))
        settle_synthetic_downloads(repo,tid)
        with repo.transaction() as c:schedule(repo,c,tid)
        await prepare(service,repo.claim_job('prepare',task_id=tid,lease_seconds=600))
        with repo.read() as c:
            snapshot=repo.objects(c,tid,'candidate_snapshot')[0]
            assert snapshot['unique_works']==target
            assert snapshot['work_property_allocations']==2*target
            assert all(len(q)==target for q in snapshot['property_queues'].values())
            assert not {'w0','w1'}.intersection(snapshot['work_ids'])
            assert len(repo.objects(c,tid,'reading_allocation'))==target
            assert all(x['readable_target']==target for x in repo.objects(c,tid,'coverage'))
    asyncio.run(run())


def test_exhausted_pool_reports_shortage_without_inventing_materials(tmp_path):
    async def run():
        repo,tid,service=carrier(tmp_path,count=4)
        spec=service.spec(None,tid);spec['run_policy']['literature']['selected_limit']=10
        with repo.transaction() as c:
            state=repo.objects(c,tid,'material_preparation')[0];state['pools']['p']['full_used']=True
            repo.put_object(c,tid,'material_preparation',tid,2,{**state,'revision':2})
        await prepare(service,repo.claim_job('prepare',task_id=tid,lease_seconds=600))
        settle_synthetic_downloads(repo,tid)
        with repo.transaction() as c:schedule(repo,c,tid)
        await prepare(service,repo.claim_job('prepare',task_id=tid,lease_seconds=600))
        with repo.read() as c:
            cover=repo.objects(c,tid,'coverage')[0]
            assert cover['state']=='partial' and cover['readable_works']==4 and cover['readable_target']==10
    asyncio.run(run())


def test_feedback_and_reuse_obey_target_not_old_twenty():
    pool={'acquired':[str(i) for i in range(10)],'attempted':[],'evaluated':[],'eligible':[],'decisions':{},'long_downloaded':['long']}
    feedback=download_feedback(pool,{},15)
    assert (feedback['D'],feedback['L'],feedback['F'],feedback['remaining_D'])==(10,1,11,5)
    assert not apply_local_grant(pool,'p','new',{'status':'supported'},10)
    assert apply_local_grant(pool,'p','new',{'status':'supported','id':'checked-evidence'},15)
