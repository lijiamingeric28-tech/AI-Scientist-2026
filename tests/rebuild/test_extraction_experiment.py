import asyncio
from copy import deepcopy
from types import SimpleNamespace

from astroquery_ai.runtime.run_policy import LEGACY_RUN_POLICY, request_policy
from astroquery_ai.runtime.extraction_experiment import VERSION, enabled
from tests.rebuild.scenario import application, confirmed_case


def test_stop_is_opt_in_and_frozen(monkeypatch):
    configuration = SimpleNamespace(runtime={})
    monkeypatch.delenv('ASTROQUERY_STOP_AFTER_EXTRACTION', raising=False)
    ordinary = request_policy(configuration)
    assert not enabled({'run_policy': ordinary})
    monkeypatch.setenv('ASTROQUERY_STOP_AFTER_EXTRACTION', '1')
    frozen = request_policy(configuration)
    monkeypatch.delenv('ASTROQUERY_STOP_AFTER_EXTRACTION')
    assert enabled({'run_policy': frozen})
    assert not enabled({'run_policy': ordinary})


def test_real_dispatch_stops_before_quality_and_retains_extraction(tmp_path):
    async def run():
        app = application(tmp_path / 'data')
        policy = deepcopy(LEGACY_RUN_POLICY)
        policy['execution'] = {'experiment': VERSION, 'stop_after_extraction': True}
        state, scheduler = await confirmed_case(app, run_policy=policy)
        assert state['lifecycle'] == 'paused'
        tid = state['task_id']
        with app.repository.read() as c:
            receipt = app.repository.object(c, tid, 'extraction_experiment_receipt', tid)
            assert receipt['quality_executed'] is False
            assert receipt['counts']['source'] > 0
            assert receipt['counts']['candidate'] + receipt['counts']['measurement'] > 0
            assert not c.execute("SELECT 1 FROM jobs WHERE task_id=? AND owner IN ('M07','M08','M09') AND status IN ('running','succeeded')", (tid,)).fetchone()
            assert not app.repository.task(c, tid)['delivery_ref']
        return scheduler
    asyncio.run(run())
