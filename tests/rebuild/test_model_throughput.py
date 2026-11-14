import pytest

from astroquery_ai.runtime.throughput import DispatchDeferred, ModelTraffic, rate_token_estimate


def test_model_pacing_is_shared_by_operation_and_different_models_are_independent():
    now = [100.0]
    traffic = ModelTraffic(tpm=6000, rpm=60, clock=lambda: now[0])
    ticket = traffic.reserve('same-model', 100)
    with pytest.raises(DispatchDeferred):
        traffic.reserve('same-model', 100)
    traffic.reserve('other-model', 100)
    traffic.settle('same-model', ticket, {'prompt_tokens': 20, 'completion_tokens': 10})
    assert ticket['tokens'] == 30
    now[0] = 101.1
    traffic.reserve('same-model', 100)
    traffic.settle('same-model', ticket, None, limited=True, retry_after=12)
    now[0] = 105
    with pytest.raises(DispatchDeferred) as err:
        traffic.reserve('same-model', 100)
    assert err.value.seconds >= 8


def test_token_rate_estimate_is_not_the_utf8_safety_bound():
    messages = [{'role': 'user', 'content': 'a' * 1000}]
    assert rate_token_estimate(messages, 1600, 200) == 1201


def test_unsent_reservation_is_released_without_changing_other_tickets():
    now=[100.0];traffic=ModelTraffic(tpm=6000,rpm=60,clock=lambda:now[0])
    first=traffic.reserve('m',100);now[0]=102
    second=traffic.reserve('m',100)
    traffic.cancel('m',first)
    assert list(traffic.entries['m'])==[second] and traffic.next_send['m']==103
    traffic.cancel('m',second)
    assert not traffic.entries['m']
    # Releasing an unsent request does not leave a false RPM/TPM entry.
    assert traffic.reserve('m',6000)['tokens']==6000


def test_production_work_slot_saturation_waits_without_spending_attempt_and_resumes(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from copy import deepcopy
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.runtime.budget import Budget
    from astroquery_ai.runtime.codec import canonical
    from astroquery_ai.runtime.run_policy import CONSOLIDATION_RUN_POLICY
    from astroquery_ai.runtime.stages import set_stage
    from astroquery_ai.runtime.scheduler import Scheduler
    repo=Repository(tmp_path/'runtime.sqlite3');budget=Budget(repo)
    tid=repo.create_task('SYNTHETIC production budget, no network')['task_id']
    with repo.transaction() as c:
        ref=repo.put_object(c,tid,'confirmed_query','synthetic-query',1,{'run_policy':deepcopy(CONSOLIDATION_RUN_POLICY),
            'dependencies':[],'registry_release':{'id':'synthetic-empty-release'}})
        repo.mutate_task(c,tid,lifecycle='running',science_state='open',query_ref=canonical(ref).decode())
        c.execute('UPDATE campaigns SET smoke_passed=1')
        set_stage(repo,c,tid,'quality')
        for i in range(5):repo.enqueue(c,tid,'M07','quality_verify',{'work_id':'same-work','items':[{'id':str(i)}]})
    def reserve(job):
        return budget.reserve(task_id=tid,owner='M06',model='qwen3.7-plus',root_id='root-'+job['job_id'],
            request={'synthetic':True},input_bound=100,output_bound=100,job=job,
            purpose='production',profile_state='validated',root_limit=2)
    jobs=[];attempts=[]
    for i in range(4):
        job=repo.claim_job('test-worker',task_id=tid);assert job
        jobs.append(job);attempts.append(reserve(job))
        budget.dispatch(attempts[-1]['attempt_id'])  # Synthetic ledger boundary; no network transport.
    blocked=repo.claim_job('test-worker',task_id=tid);assert blocked
    with pytest.raises(DispatchDeferred) as waiting:reserve(blocked)
    assert waiting.value.resource=='work-model-slots:same-work'
    worker=object.__new__(Scheduler);worker.repository=repo;worker.application=SimpleNamespace()
    worker.fail(blocked,waiting.value)
    with repo.read() as c:
        assert c.execute('select count(*) from attempts where task_id=?',(tid,)).fetchone()[0]==4
        assert tuple(c.execute('select status,attempt_count from jobs where job_id=?',(blocked['job_id'],)).fetchone())==('ready',0)
    budget.settle(attempts[0]['attempt_id'],input_tokens=0,output_tokens=0,
                  receipt={'synthetic':True,'actual_network_dispatch':False})
    import time
    later=time.time()+2;monkeypatch.setattr(time,'time',lambda:later)
    recovered=repo.claim_job('test-worker',task_id=tid)
    assert recovered and recovered['job_id']==blocked['job_id']
    final=reserve(recovered)
    assert final['attempt_id']
    with repo.read() as c:
        assert c.execute('select count(*) from attempts where task_id=? and root_id=?',
            (tid,'root-'+blocked['job_id'])).fetchone()[0]==1


def test_resource_wait_releases_lease_without_failure_or_paid_attempt(tmp_path):
    from types import SimpleNamespace
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.runtime.scheduler import Scheduler
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC resource wait')['task_id']
    with repo.transaction() as conn:
        jid = repo.enqueue(conn, tid, 'M03', 'catalog_extract', {'table_id': 'first'})
        other = repo.enqueue(conn, tid, 'M03', 'catalog_extract', {'table_id': 'second'})
    worker = object.__new__(Scheduler)
    worker.repository, worker.application = repo, SimpleNamespace()
    job = repo.claim_job('worker')
    worker.fail(job, DispatchDeferred('model-rate:synthetic', 30))
    with repo.read() as conn:
        state = conn.execute('SELECT status,attempt_count,lease_token FROM jobs WHERE job_id=?', (jid,)).fetchone()
        assert tuple(state) == ('ready', 0, None)
        assert conn.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
    assert repo.claim_job('worker')['job_id'] == other


def test_production_comparison_uses_confirmed_property_scope_without_fake_work(tmp_path):
    from copy import deepcopy
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.runtime.budget import Budget
    from astroquery_ai.runtime.codec import canonical
    from astroquery_ai.runtime.run_policy import CONSOLIDATION_RUN_POLICY
    from astroquery_ai.runtime.stages import set_stage
    from astroquery_ai.runtime.errors import DomainError
    repo=Repository(tmp_path/'runtime.sqlite3');budget=Budget(repo)
    tid=repo.create_task('SYNTHETIC property comparison scope, no network')['task_id']
    with repo.transaction() as c:
        ref=repo.put_object(c,tid,'confirmed_query','q',1,{'run_policy':deepcopy(CONSOLIDATION_RUN_POLICY),
            'dependencies':[],'registry_release':{'id':'synthetic-release'},'properties':[{'property_id':'p1'}]})
        repo.mutate_task(c,tid,lifecycle='running',science_state='open',query_ref=canonical(ref).decode())
        c.execute('UPDATE campaigns SET smoke_passed=1');set_stage(repo,c,tid,'postcheck')
        repo.enqueue(c,tid,'M09','compare_results',{'property_id':'p1','measurement_refs':[],'input_hash':'synthetic'})
        repo.enqueue(c,tid,'M09','compare_results',{'property_id':'unconfirmed','measurement_refs':[],'input_hash':'synthetic-negative'})
    def reserve(job):
        return budget.reserve(task_id=tid,owner='M06',model='qwen3.7-plus',root_id='scope-'+job['job_id'],
            request={'synthetic':True},input_bound=100,output_bound=100,job=job,
            purpose='production',profile_state='validated',root_limit=2)
    good=repo.claim_job('worker',task_id=tid);receipt=reserve(good)
    with repo.read() as c:
        assert c.execute('select work_scope from attempts where attempt_id=?',(receipt['attempt_id'],)).fetchone()[0]=='property-comparison:p1'
    bad=repo.claim_job('worker',task_id=tid)
    with pytest.raises(DomainError) as error:reserve(bad)
    assert error.value.code=='WORK_BUDGET_SCOPE_MISSING'
    with repo.read() as c:assert c.execute('select count(*) from attempts where task_id=?',(tid,)).fetchone()[0]==1


def test_separate_gateways_share_model_window_from_actual_call_ledger(tmp_path):
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.runtime.budget import Budget
    from astroquery_ai.runtime.throughput import shared_window_delay
    repo = Repository(tmp_path / 'runtime.sqlite3')
    budget = Budget(repo)
    task = repo.create_task('SYNTHETIC shared window', kind='validation')
    with repo.transaction() as conn:
        conn.execute('UPDATE campaigns SET smoke_passed=1')
    attempt = budget.reserve(task_id=task['task_id'], owner='M06', model='qwen3.8-flash',
        root_id='synthetic-shared', request={}, input_bound=2000, output_bound=1000,
        purpose='calibration', profile_state='trial', root_limit=1)
    budget.dispatch(attempt['attempt_id'])
    # Two independently constructed controllers still see one account/model
    # reservation. This synthetic dispatch never enters a network transport.
    with repo.read() as conn:
        assert shared_window_delay(conn, 'qwen3.8-flash', 10, rpm=1) > 0
        assert shared_window_delay(conn, 'qwen3.7-plus', 10, rpm=1) == 0
    budget.settle(attempt['attempt_id'], input_tokens=0, output_tokens=0,
                  receipt={'synthetic': True, 'actual_network_dispatch': False})
