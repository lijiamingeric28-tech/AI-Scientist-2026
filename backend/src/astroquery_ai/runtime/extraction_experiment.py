"""Opt-in extraction boundary, frozen into new requests; ordinary runs are unchanged."""
from __future__ import annotations

from .codec import loads, utcnow
from .errors import DomainError
from .stages import JOB_STAGE, STAGES, ACTIVE, advance_stage

VERSION = 'attachment-repro/1'


def enabled(spec):
    policy = spec.get('run_policy', {}).get('execution', {})
    return policy.get('experiment') == VERSION and policy.get('stop_after_extraction') is True


def permits_job(repo, conn, job):
    stage = JOB_STAGE.get(job['kind'])
    if stage is None or STAGES.index(stage) <= STAGES.index('extraction'):
        return True
    task = repo.task(conn, job['task_id'])
    if not task['query_ref']:
        return True
    ref = loads(task['query_ref'])
    return not enabled(repo.object(conn, job['task_id'], 'confirmed_query', ref['id'], ref['version']))


def advance_extraction(service, conn, tid, spec):
    """Called after replenishment/preparation, before any quality planning."""
    repo = service.repo
    jobs = [dict(r) for r in conn.execute('SELECT kind,status,job_id,reason FROM jobs WHERE task_id=?', (tid,))]
    downstream = [j for j in jobs if JOB_STAGE.get(j['kind']) in STAGES[STAGES.index('quality'):]]
    if any(j['status'] in {'running', 'succeeded'} for j in downstream):
        raise DomainError('EXTRACTION_BOUNDARY_BREACH', '提取实验出现下游执行作业')
    upstream = [j for j in jobs if j not in downstream]
    preparations = repo.objects(conn, tid, 'material_preparation')
    if any(j['status'] in ACTIVE for j in upstream) or (preparations and not preparations[0]['closed']):
        advance_stage(repo, conn, tid)
        return
    # Figure reuse is extraction work in the normal pipeline, not a quality pass.
    planned = {p['source_id'] for p in repo.objects(conn, tid, 'figure_reuse_plan')}
    created = False
    for source in repo.objects(conn, tid, 'source'):
        if source['kind'] == 'paper' and source['source_id'] not in planned:
            repo.put_object(conn, tid, 'figure_reuse_plan', source['source_id'], 1,
                            {'source_id': source['source_id'], 'reading_complete': True})
            repo.enqueue(conn, tid, 'M06', 'paper_figures', {'work_id': source['source_id'],
                'artifact_ref': source['artifact']['artifact_id'], 'reuse_body_hints': True})
            created = True
    if created:
        advance_stage(repo, conn, tid)
        return
    for j in downstream:
        if j['status'] in ACTIVE:
            conn.execute("UPDATE jobs SET status='not_run',reason='extraction_experiment_boundary' WHERE job_id=?", (j['job_id'],))
    receipt = {'schema_version': VERSION, 'finished_at': utcnow(),
        'state': 'extraction_finished', 'quality_executed': False, 'delivery_created': False,
        'counts': {kind: len(repo.objects(conn, tid, kind)) for kind in ('source','attachment','candidate','measurement')},
        'failed_jobs': [j for j in upstream if j['status'] in {'failed','not_run','cancelled'}]}
    repo.put_object(conn, tid, 'extraction_experiment_receipt', tid, 1, receipt)
    repo.mutate_task(conn, tid, lifecycle='paused', phase='extraction', resume_required=0,
                     terminal_reason='extraction_experiment_frozen')
    repo.event(conn, tid, 'extraction_experiment_frozen', receipt)
