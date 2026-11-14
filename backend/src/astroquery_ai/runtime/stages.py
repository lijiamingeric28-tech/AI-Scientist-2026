"""Business stage barriers for the existing short-job dispatcher.

An owner is a service, not a stage: M03 also interprets acquired attachments.
Historical tasks without a pin keep their original dispatch semantics.
"""
from __future__ import annotations

from .codec import loads

STAGES = ("catalog", "literature", "acquisition", "extraction", "quality",
          "normalization", "postcheck", "delivery", "insight")
JOB_STAGE = {
    "catalog_discover": "catalog", "catalog_extract": "catalog",
    "literature_discover": "literature",
    "acquire_window": "acquisition", "acquire_work": "acquisition", "attachment_discover": "acquisition",
    'material_prepare':'acquisition',
    "paper_batch": "extraction", "attachment_extract": "extraction",
    "source_reconcile": "extraction",
    'citation_enrich': 'extraction',
    "paper_figures": "extraction", "paper_figure_page": "extraction",
    "assess_batch": "quality", "apply_source_recheck": "quality",
    "apply_review": "quality", "review_source_gap": "quality",
    "interpret_uncertainty": "quality",
    'quality_verify':'quality','quality_reextract':'quality','quality_citation_enrich':'quality',
    'compare_results':'postcheck',
    "normalize": "normalization", "finalize": "postcheck", "insights": "insight",
}
PRESENTATION_STAGE = {'catalog': 'retrieval', 'literature': 'retrieval', 'acquisition': 'retrieval',
    'extraction': 'extraction', 'quality': 'quality_check', 'normalization': 'clean',
    'postcheck': 'deliver', 'delivery': 'deliver', 'insight': 'insight'}
ACTIVE = {"ready", "running", "waiting_dependency", "awaiting_review"}
EXECUTION_POLICY = {
    "version": "bounded-reading-concurrency-2", "workers": 48,
    "models_total": 32, "models": {"qwen3.8-flash": 24, "qwen3.7-plus": 12, "qwen3.8-max": 2},
    "owners": {"M03": 8, "M04": 8, "M05": 12, "M06": 32, "M07": 8, "M08": 12,"M09":4},
    "network_total": 12, "parse": 4, "insight_units": 8,
    "services": {"simbad":2, "vizier":4, "ads":4, "publisher":2, "arxiv":1},
    "abstracts": 8, "scope": "single-active-query", "same_work_semantic_batches": 4,
}


def current_stage(conn, task_id):
    row = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='stage_checkpoint' "
                       "ORDER BY version DESC LIMIT 1", (task_id,)).fetchone()
    return loads(row[0]) if row else None


def set_stage(repo, conn, task_id, stage, *, repair=False):
    previous = current_stage(conn, task_id)
    if previous and previous["stage_id"] == stage:
        return previous
    revision = previous["revision"] + 1 if previous else 1
    checkpoint = {"schema_version": "ExecutionStage/1", "stage_id": stage,
                  "revision": revision, "previous_stage": previous["stage_id"] if previous else None,
                  "local_repair": repair, "policy_version": EXECUTION_POLICY["version"]}
    repo.put_object(conn, task_id, "stage_checkpoint", task_id, revision, checkpoint)
    repo.event(conn, task_id, "execution_stage_changed", checkpoint)
    return checkpoint


def advance_stage(repo, conn, task_id):
    checkpoint = current_stage(conn, task_id)
    if not checkpoint:
        return
    jobs = conn.execute("SELECT kind,status FROM jobs WHERE task_id=?", (task_id,)).fetchall()
    # A handler marks itself done before advance() finishes. Only this committed
    # checkpoint opens the next stage; a worker cannot infer it from an empty queue.
    if any(j["status"] == "running" for j in jobs):
        return
    pending = {JOB_STAGE[j["kind"]] for j in jobs
               if j["status"] in ACTIVE and j["kind"] in JOB_STAGE}
    if conn.execute("SELECT 1 FROM reviews WHERE task_id=? AND status IN ('pending','accepted') LIMIT 1",
                    (task_id,)).fetchone():
        pending.add("quality")
    if pending:
        stage = min(pending, key=STAGES.index)
        preparations=repo.objects(conn,task_id,'material_preparation')
        if preparations and not preparations[0]['closed'] and STAGES.index(stage)>STAGES.index('acquisition'):
            stage='acquisition'
        set_stage(repo, conn, task_id, stage,
                  repair=STAGES.index(stage) < STAGES.index(checkpoint["stage_id"]))


def resource_key(job):
    payload = job["payload"]
    if job['kind']=='material_prepare':return ('material_preparation',job['task_id'])
    if job["owner"] == "M06":
        if payload.get('consolidated_review'):
            return ('source_property_review', payload['work_id'], payload['property_id'], job['job_id'])
        if payload.get('reading_batch_id'):
            return ('reading_batch', payload['reading_batch_id'])
        return ("work", payload.get("work_id", job["job_id"]))
    if job['kind'] == 'acquire_work':
        return ('work_acquisition', payload['work_id'])
    if job["kind"] in {"normalize", "interpret_uncertainty"}:
        return ("measurement", payload["measurement_id"])
    if job["kind"] == "acquire_window":
        return ("read_ledger", job["task_id"])
    if job["kind"] == "finalize":
        return ("seal", job["task_id"])
    if job["owner"] == "M03":
        table = payload.get("table", {})
        return ("table", payload.get("table_id") or table.get("table_id") or job["job_id"])
    return None


def record_locks(repo, conn, job):
    payload, tid = job['payload'], job['task_id']
    locks = {('measurement', mid) for mid in payload.get('measurement_ids', [])}
    locks.update(('candidate', cid) for cid in payload.get('candidate_ids', []))
    if job['kind'] == 'apply_source_recheck':
        ref = payload['recheck_ref']
        row = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='source_recheck' AND object_id=? AND version=?",
                           (tid, ref['id'], ref['version'])).fetchone()
        if row:
            locks.update((o['item_ref']['kind'], o['item_ref']['id']) for o in loads(row[0])['outcomes'])
    if job['kind'] == 'apply_review':
        row = conn.execute('SELECT payload FROM reviews WHERE task_id=? AND review_id=?',
                           (tid, payload['review_id'])).fetchone()
        if row:
            scope = loads(row[0])['scope']
            locks.update(('measurement', mid) for mid in scope.get('measurement_ids', []))
            locks.update(('candidate', cid) for cid in scope.get('candidate_ids', []))
    key = resource_key(job)
    if key:
        locks.add(key)
    return locks


def eligible(job, running, checkpoint):
    stage = JOB_STAGE.get(job["kind"])
    if stage and stage != checkpoint["stage_id"]:
        return False
    owner_limit = EXECUTION_POLICY["owners"].get(job["owner"], 1)
    if sum(j["owner"] == job["owner"] for j in running) >= owner_limit:
        return False
    if job['kind'] == 'paper_batch' and job['payload'].get('reading_batch_id'):
        work = job['payload'].get('read_grant_work_id', job['payload']['work_id'])
        count = sum(j['kind'] == 'paper_batch' and
            j['payload'].get('read_grant_work_id', j['payload'].get('work_id')) == work for j in running)
        if count >= EXECUTION_POLICY['same_work_semantic_batches']:
            return False
    locks = job.get('record_locks', {resource_key(job)} - {None})
    return all(not locks.intersection(j.get('record_locks', {resource_key(j)} - {None})) for j in running)
