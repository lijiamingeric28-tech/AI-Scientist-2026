"""Atomic run reservations and deterministic synthetic scientific boundary cases."""
from concurrent.futures import ThreadPoolExecutor
import random
from copy import deepcopy

import pytest

from astroquery_ai.runtime.budget import Budget
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.run_budget import activate, bind, usage


def setup_run(tmp_path, cap=600, calibration=600):
    repo = Repository(tmp_path / 'db')
    budget = Budget(repo)
    activate(repo, 'test', cap, calibration)
    tasks = [repo.create_task('SYNTHETIC scoped task', kind='validation',
        initializer=lambda c,t: bind(repo,c,t['task_id'],'test'))['task_id'] for _ in range(2)]
    return repo, budget, tasks


def reserve(budget, tid, root):
    return budget.reserve(task_id=tid, owner='M01', model='qwen3.8-flash', root_id=root,
        request={}, input_bound=100, output_bound=100, smoke=True)


def test_concurrent_tasks_share_one_atomic_ceiling_and_restart_cannot_reset_it(tmp_path):
    repo,budget,tasks=setup_run(tmp_path)
    def attempt(i):
        try:
            reserve(budget,tasks[i%2],str(i)); return True
        except DomainError as exc:
            assert exc.code=='CAMPAIGN_BUDGET_EXHAUSTED';return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted=list(pool.map(attempt,range(8)))
    assert sum(accepted)==1
    activate(repo,'test',600,600)
    with pytest.raises(DomainError) as error:reserve(Budget(repo),tasks[1],'restart')
    assert error.value.code=='CAMPAIGN_BUDGET_EXHAUSTED'
    with pytest.raises(DomainError):activate(repo,'test',1000000,600)


@pytest.mark.parametrize('state,actual,expected',[('unknown',None,350),('settled',25,25),('not_dispatched',0,0)])
def test_unknown_usage_keeps_reservation_and_settlement_releases_only_real_difference(tmp_path,state,actual,expected):
    repo,budget,tasks=setup_run(tmp_path)
    first=reserve(budget,tasks[0],'first')
    with repo.transaction() as c:
        c.execute('UPDATE attempts SET status=?,actual_micros=? WHERE attempt_id=?',(state,actual,first['attempt_id']))
    with repo.read() as c:assert usage(c,'test')['committed_micros']==expected
    if state=='unknown':
        with pytest.raises(DomainError):reserve(budget,tasks[1],'second')
    else:assert reserve(budget,tasks[1],'second')


def test_calibration_has_separate_lower_ceiling(tmp_path):
    _,budget,tasks=setup_run(tmp_path,cap=100000,calibration=349)
    with pytest.raises(DomainError) as error:reserve(budget,tasks[0],'calibration')
    assert error.value.details['calibration'] is True


def test_unscoped_history_is_not_counted_in_new_run(tmp_path):
    repo,budget,tasks=setup_run(tmp_path)
    historic=repo.create_task('SYNTHETIC old history',kind='validation')['task_id']
    reserve(budget,historic,'historical')
    with repo.read() as c:assert usage(c,'test')['committed_micros']==0
    assert reserve(budget,tasks[0],'new')


def test_normal_query_creation_binds_budget_before_any_queued_work(tmp_path):
    from uuid import uuid4
    from tests.rebuild.scenario import application
    from astroquery_ai.runtime.codec import loads
    app=application(tmp_path/'app')
    activate(app.repository,'night',100000000,5000000)
    app.execution_run_id='night'
    tid=str(uuid4())
    app.create('SYNTHETIC target length',tid,{'papers_per_property':10,'ads_sort':'score desc'})
    with app.repository.read() as c:
        member=c.execute('SELECT payload FROM settings WHERE key=?',('execution_run_task:'+tid,)).fetchone()
        assert loads(member[0])['run_id']=='night'
        assert c.execute("SELECT count(*) FROM jobs WHERE task_id=? AND status='ready'",(tid,)).fetchone()[0]==1
        assert usage(c,'night')['committed_micros']==0


@pytest.mark.parametrize('seed', range(100))
def test_finite_seeded_original_cell_and_grouping_matrix(seed):
    from astroquery_ai.science.catalog.literal_rows import literal_proposal
    from astroquery_ai.science.structured_quality import row_regime, transcription_problem
    rng=random.Random(seed)
    columns=[{'name':'Flux','datatype':'double','unit_text':'Jy','ucd':'phot.flux'},
        {'name':'Err','datatype':'double','unit_text':'Jy','ucd':'stat.error'},
        {'name':'JD','datatype':'double','unit_text':'d','ucd':'time.epoch'},
        {'name':'Q','datatype':'char','description':'0 = reported detection; U = upper limit; ? = unknown'},
        {'name':'Method','datatype':'char','description':'Source method'}]
    row={'Flux':format(rng.uniform(-5,5),'.6f'),'Err':format(rng.uniform(0,1),'.5f'),
         'JD':str(2450000+seed),'Q':rng.choice(['0','U','?']),'Method':rng.choice(['A','B'])}
    mapping={'property_id':'SYNTHETIC-flux','value_column':'Flux','quantity_match':'exact',
        'source_unit':'Jy','source_representation':'linear','error_columns':['Err'],
        'context_columns':['JD','Method'],'quality_columns':['Q']}
    p=literal_proposal(row,seed,columns,mapping,shared_flags=True)[0].model_dump(mode='json')
    assert p['raw_value']==row['Flux'] and p['errors'][0]['raw_text']==row['Err']
    assert p['subject_role']==p['result_role']=='unresolved' and p['source_quality'] is None
    assert transcription_problem(p,row,columns) is None
    regime=row_regime(row,columns,p,set(),['Q'])
    later={**row,'JD':str(2451000+seed)}
    assert row_regime(later,columns,p,set(),['Q'])==regime
    for key,value in [('Q','other'),('Method','different')]:
        assert row_regime({**row,key:value},columns,p,set(),['Q'])!=regime
    bad=deepcopy(p);bad['raw_value']='fabricated'
    assert transcription_problem(bad,row,columns)=='main_cell_token_mismatch'
    assert literal_proposal({**row,'Flux':'< 1.5'},seed,columns,mapping,shared_flags=True)[0] is None
