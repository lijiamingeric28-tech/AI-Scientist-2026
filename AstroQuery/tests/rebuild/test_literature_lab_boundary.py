"""Material experiments use the real preparation boundary; no science run."""
import asyncio
from types import SimpleNamespace
import pytest

from astroquery_ai.runtime.codec import canonical
from astroquery_ai.science.literature_preparation import prepare, schedule
from astroquery_ai.science.workflow.orchestration_service import OrchestrationService
from tests.rebuild.test_two_tier_materials import carrier, settle_synthetic_downloads


@pytest.mark.parametrize('stop', [False, True])
def test_frozen_material_boundary_preserves_sources_and_normal_default(tmp_path, stop):
    async def run():
        repo, tid, svc = carrier(tmp_path, properties=('p', 'q'), count=20)
        spec = svc.spec(None, tid)
        if stop:
            spec['run_policy']['literature']['stop_after_materials'] = True
        await prepare(svc, repo.claim_job('prepare', task_id=tid, lease_seconds=600))
        settle_synthetic_downloads(repo, tid)
        with repo.transaction() as c:
            schedule(repo, c, tid)
        await prepare(svc, repo.claim_job('prepare', task_id=tid, lease_seconds=600))
        with repo.read() as c:
            assert repo.objects(c, tid, 'material_preparation')[0]['closed']
            assert len(repo.objects(c, tid, 'source')) == 20
            assert len(repo.objects(c, tid, 'reading_allocation')) == 20
            assert repo.objects(c, tid, 'candidate_snapshot')[0]['downstream_scheduled'] is not stop
            jobs = [r[0] for r in c.execute('select kind from jobs where task_id=?', (tid,))]
            assert jobs.count('paper_batch') == (0 if stop else 40)
            assert jobs.count('attachment_discover') == (0 if stop else 20)
        if stop:
            with repo.transaction() as c:
                repo.mutate_task(c, tid, query_ref='{}')
            ctx = SimpleNamespace(repo=repo, app=None, steps=None, extractor=None)
            orchestrator = OrchestrationService(ctx)
            orchestrator.spec = lambda c, t: spec
            await orchestrator.advance(tid)
            assert repo.get_task(tid)['terminal_reason'] == 'material_experiment_frozen'
            assert repo.get_task(tid)['lifecycle'] == 'paused'
            with repo.read() as c:
                assert not repo.objects(c, tid, 'delivery')
                assert not c.execute("select 1 from jobs where task_id=? and kind in ('finalize','insights','assess_batch')", (tid,)).fetchone()
    asyncio.run(run())


@pytest.mark.parametrize('first_lab,second_lab,opt_in,expected',[
    (True,True,False,False),(True,True,True,True),
    (False,True,True,False),(True,False,True,False)])
def test_parallel_claim_is_only_for_explicit_frozen_material_experiments(tmp_path,first_lab,second_lab,opt_in,expected):
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.runtime.codec import digest
    from astroquery_ai.runtime.stages import set_stage
    repo=Repository(tmp_path/'db')
    tids=[]
    for is_lab in (first_lab,second_lab):
        tid=repo.create_task('SYNTHETIC material/ordinary isolation')['task_id'];tids.append(tid)
        spec={'run_policy':{'literature':{'stop_after_materials':is_lab}},
              'module_experiment':{'version':'literature-lab/1'},'dependencies':[],
              'registry_release':{'id':'synthetic'}}
        spec['spec_hash']=digest(spec)
        with repo.transaction() as c:
            ref=repo.put_object(c,tid,'confirmed_query',tid,1,spec)
            repo.mutate_task(c,tid,lifecycle='running',science_state='open',query_ref=canonical(ref).decode())
            set_stage(repo,c,tid,'literature')
            repo.enqueue(c,tid,'M04','literature_discover',{})
    assert repo.claim_job('one',task_id=tids[0])
    second=repo.claim_job('two',task_id=tids[1],material_scope='literature-lab/1' if opt_in else None)
    assert bool(second) is expected


def test_closing_one_material_worker_does_not_recover_running_siblings(tmp_path):
    from astroquery_ai.runtime.scheduler import Scheduler
    repo,tid,_=carrier(tmp_path,count=0)
    repo.claim_job('still-active',task_id=tid)
    async def run():
        worker=SimpleNamespace(stopping=False,wake=asyncio.Event(),worker=None,repository=repo)
        await Scheduler.stop(worker,recover=False)
        with repo.read() as c:
            assert c.execute("select count(*) from jobs where status='running'").fetchone()[0]==1
        assert repo.get_task(tid)['lifecycle']=='running'
    asyncio.run(run())


def test_manual_module_claim_waits_for_real_worker_capacity_without_new_job(tmp_path,monkeypatch):
    from tests.support.literature.common import claim_module_job
    from astroquery_ai.runtime.stages import EXECUTION_POLICY
    async def run():
        repo,tid,_=carrier(tmp_path,count=0)
        first=repo.claim_job('busy',task_id=tid)
        with repo.transaction() as c:
            second=repo.enqueue(c,tid,'M04','reconcile',{'operation':'synthetic-evaluation'})
        monkeypatch.setitem(EXECUTION_POLICY,'workers',1)
        waiter=asyncio.create_task(claim_module_job(SimpleNamespace(repository=repo),tid,'after-wait'))
        await asyncio.sleep(.02)
        assert not waiter.done()
        with repo.transaction() as c:repo.finish_job(c,first)
        result=await asyncio.wait_for(waiter,2)
        assert result['job_id']==second and result['attempt_count']==1
        with repo.read() as c:assert c.execute('select count(*) from jobs where task_id=?',(tid,)).fetchone()[0]==2
    asyncio.run(run())


def test_explicit_content_research_keeps_downloads_but_refills_until_twenty_useful(tmp_path):
    async def run():
        repo,tid,svc=carrier(tmp_path,count=21)
        spec=svc.spec(None,tid)
        spec['run_policy']['literature'].update(stop_after_materials=True,experiment={'content_gated':True})
        async def evaluator(job,frozen,results):
            return {wid:{'status':'F' if wid=='w0' else 'U','evaluation_id':'SYNTHETIC-'+wid}
                    for wid,row in results.items() if row['state']=='acquired'}
        svc.app=SimpleNamespace(material_content_evaluator=evaluator)
        await prepare(svc,repo.claim_job('initial',task_id=tid))
        settle_synthetic_downloads(repo,tid)
        with repo.transaction() as c:schedule(repo,c,tid)
        await prepare(svc,repo.claim_job('replacement',task_id=tid))
        settle_synthetic_downloads(repo,tid)
        with repo.transaction() as c:schedule(repo,c,tid)
        await prepare(svc,repo.claim_job('freeze',task_id=tid))
        with repo.read() as c:
            state=repo.objects(c,tid,'material_preparation')[0];pool=state['pools']['p']
            assert state['closed'] and len(pool['downloaded'])==21 and len(pool['acquired'])==20
            assert 'w0' not in pool['acquired'] and pool['content_evaluations']['w0']['status']=='F'
            assert len(repo.objects(c,tid,'prepared_source'))==21 and len(repo.objects(c,tid,'source'))==20
            assert all(r['state']=='acquired' for r in repo.objects(c,tid,'acquisition_result'))
            assert not c.execute("select 1 from jobs where task_id=? and kind='paper_batch'",(tid,)).fetchone()
    asyncio.run(run())
