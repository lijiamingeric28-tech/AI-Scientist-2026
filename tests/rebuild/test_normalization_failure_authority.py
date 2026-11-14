import pytest

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.codec import canonical, content_hash
from astroquery_ai.runtime.delivery import current_derived_representations
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.scheduler import Scheduler
from tests.rebuild.factories import measurement, ref


def case(tmp_path, *, stale=False):
    app = Application(tmp_path, allow_synthetic=True)
    tid = app.repository.create_task('SYNTHETIC normalization failure authority')['task_id']
    record = measurement()
    record['task_id'] = tid
    record['content_sha256'] = content_hash(record)
    target = ref('SYNTHETIC target output')
    binding = {'property_id': record['property_ref']['id'], 'output_profile': {
        'profile_id': target['id'], 'version': 1, 'content_sha256': target['content_sha256']}}
    with app.repository.transaction() as conn:
        query = app.repository.put_object(conn, tid, 'confirmed_query', 'SYNTHETIC query', 1,
            {'properties': [binding], 'dependencies': [], 'registry_release': {'id': 'SYNTHETIC registry'}})
        app.repository.put_object(conn, tid, 'measurement', record['measurement_id'], 1, record)
        app.repository.mutate_task(conn, tid, lifecycle='queued', science_state='open', query_ref=canonical(query).decode())
        app.repository.enqueue(conn, tid, 'M08', 'normalize', {'measurement_id': record['measurement_id'],
            'source_hash': ref('SYNTHETIC previous source')['content_sha256'] if stale else record['content_sha256']})
    return app, tid, record, binding


@pytest.mark.parametrize('code,status', [('MODEL_NETWORK_ERROR', 'not_checked'),
                                        ('MODEL_NUMERIC_CHECK_FAILED', 'failed')])
def test_final_failure_is_current_and_does_not_turn_transport_unknown_into_bad_science(tmp_path, code, status):
    app, tid, record, binding = case(tmp_path)
    scheduler = Scheduler(app)
    for _ in range(3):
        job = app.repository.claim_job('SYNTHETIC worker')
        if job is None:
            break
        scheduler.fail(job, DomainError(code, 'SYNTHETIC failure'))
    with app.repository.read() as conn:
        history = app.repository.objects(conn, tid, 'derived')
        pointers = app.repository.objects(conn, tid, 'derived_current')
        selected = current_derived_representations([record], [binding], history, pointers)
        assert len(selected) == 1 and selected[0]['status'] == status
        assert selected[0]['value_typed'] is None
        assert app.repository.object(conn, tid, 'measurement', record['measurement_id']) == record
        assert not app.repository.objects(conn, tid, 'review_answer')
        receipts = app.repository.objects(conn, tid, 'processing_receipt')
        assert len(receipts) == 1 and receipts[0]['postcheck'] == status
        assert not app.repository.objects(conn, tid, 'change_event')
    assert app.budget.summary()['committed_micros'] == 0


def test_failure_of_old_input_cannot_mark_current_human_revision_failed_or_retry_it(tmp_path):
    app, tid, record, _ = case(tmp_path, stale=True)
    job = app.repository.claim_job('SYNTHETIC worker')
    Scheduler(app).fail(job, DomainError('MODEL_NETWORK_ERROR', 'SYNTHETIC late transport error'))
    with app.repository.read() as conn:
        assert app.repository.object(conn, tid, 'measurement', record['measurement_id']) == record
        assert not app.repository.objects(conn, tid, 'derived')
        assert not app.repository.objects(conn, tid, 'derived_current')
        assert conn.execute('SELECT status FROM jobs WHERE job_id=?', (job['job_id'],)).fetchone()[0] == 'not_run'
    assert app.repository.claim_job('SYNTHETIC next worker') is None
