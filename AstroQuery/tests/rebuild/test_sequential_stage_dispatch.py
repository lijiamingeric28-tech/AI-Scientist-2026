from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.stages import advance_stage, current_stage, set_stage


def test_stage_barrier_and_independent_catalogs(tmp_path):
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC stage barrier')['task_id']
    with repo.transaction() as conn:
        set_stage(repo, conn, tid, 'catalog')
        tables = [repo.enqueue(conn, tid, 'M03', 'catalog_extract', {'table_id': str(i)}) for i in range(10)]
        literature = repo.enqueue(conn, tid, 'M04', 'literature_discover', {})
        repo.enqueue(conn, tid, 'M07', 'assess_batch', {'measurement_ids': [], 'candidate_ids': []})
    claimed = [repo.claim_job('worker') for _ in range(8)]
    assert {j['job_id'] for j in claimed} <= set(tables)
    assert repo.claim_job('worker') is None
    with repo.transaction() as conn:
        for job in claimed:
            repo.finish_job(conn, job)
        advance_stage(repo, conn, tid)
    for _ in range(2):
        job = repo.claim_job('worker')
        assert job['kind'] == 'catalog_extract'
        with repo.transaction() as conn:
            repo.finish_job(conn, job)
    # Last handler's completion alone cannot open a new phase.
    assert repo.claim_job('worker') is None
    with repo.transaction() as conn:
        advance_stage(repo, conn, tid)
    assert repo.claim_job('worker')['job_id'] == literature


def test_parallel_papers_and_later_attachment_use_service_not_owner_phase(tmp_path):
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC extraction concurrency')['task_id']
    with repo.transaction() as conn:
        set_stage(repo, conn, tid, 'extraction')
        for i in range(12):
            repo.enqueue(conn, tid, 'M06', 'paper_batch', {'work_id': str(i), 'pages': [1]})
        repo.enqueue(conn, tid, 'M06', 'paper_batch', {'work_id': '0', 'pages': [2]})
        attachment = repo.enqueue(conn, tid, 'M03', 'attachment_extract', {'table_id': 'official'})
        repo.enqueue(conn, tid, 'M08', 'normalize', {'measurement_id': 'SYNTHETIC'})
    claimed = [repo.claim_job('worker') for _ in range(13)]
    assert all(claimed) and len({j['payload'].get('work_id') for j in claimed if j['owner'] == 'M06'}) == 12
    assert attachment in {j['job_id'] for j in claimed}
    assert repo.claim_job('worker') is None


def test_pending_review_stays_in_quality_and_repairs_wait_for_running_work(tmp_path):
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC scoped repair')['task_id']
    with repo.transaction() as conn:
        set_stage(repo, conn, tid, 'quality')
        repo.enqueue(conn, tid, 'M07', 'assess_batch', {'measurement_ids': [], 'candidate_ids': []})
    job = repo.claim_job('worker')
    with repo.transaction() as conn:
        repo.enqueue(conn, tid, 'M06', 'source_reconcile', {'work_id': 'SYNTHETIC'})
        advance_stage(repo, conn, tid)
        assert current_stage(conn, tid)['stage_id'] == 'quality'
        repo.finish_job(conn, job)
        advance_stage(repo, conn, tid)
        assert current_stage(conn, tid)['local_repair'] is True
    assert repo.claim_job('worker')['kind'] == 'source_reconcile'


def test_overlapping_quality_records_are_serial_but_other_records_progress(tmp_path):
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC record concurrency')['task_id']
    with repo.transaction() as conn:
        set_stage(repo, conn, tid, 'quality')
        for mids in (['one', 'two'], ['two', 'three'], ['four']):
            repo.enqueue(conn, tid, 'M07', 'assess_batch', {'measurement_ids': mids})
    first, second = repo.claim_job('worker'), repo.claim_job('worker')
    assert first['payload']['measurement_ids'] == ['one', 'two']
    assert second['payload']['measurement_ids'] == ['four']
    assert repo.claim_job('worker') is None
