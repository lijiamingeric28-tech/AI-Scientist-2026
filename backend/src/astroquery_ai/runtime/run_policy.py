"""Frozen normal-run limits; initial catalogs never share an attachment clock."""
from contextvars import ContextVar
from copy import deepcopy
import time

from .codec import loads, digest
from .errors import DomainError

LEGACY_RUN_POLICY = {
    "version": "retrieval-quality-two-tier/1",
    "catalog": {"maximum_tables": 20, "wave_tables": 8, "table_repairs": 1,
                "maximum_discovery_queries": 6, "maximum_catalog_expansions": 12},
    "documents": {"maximum_pdf_pages": 50},
    "literature": {"unit": "confirmed_property", "candidate_limit": 40,
                   "selected_limit": 20, "sort": "score desc", "replacement": "bounded-two-tier",
                   "strategy":"two-tier-materials/1", "full_candidate_limit":20,
                   "abs_page_rows":40,"abs_maximum_pages":2,"full_page_rows":20,"full_maximum_pages":3,
                   "abs_timeout_seconds":30,"abs_read_timeout_seconds":20,
                   "full_timeout_seconds":60,"full_read_timeout_seconds":45,
                   "layer_transport_retries":1,
                   "citation_expansion": False},
    "reading": {"core_pages": 4, "properties_per_batch": 1, "maximum_attempts": 2,
                "quantity_identity":"explicit/1",
                "recursive_split": False, "review": "work_property_once"},
}
# Old confirmed requests keep the exact policy already stored in their spec.
CONSOLIDATION_RUN_POLICY = deepcopy(LEGACY_RUN_POLICY)
CONSOLIDATION_RUN_POLICY.update(version='backend-consolidation/1',
    workflow_contract='backend-consolidation/1',
    quality={'mode':'unified-evidence/1','local_reextractions_per_issue':1},
    comparison={'mode':'archive-and-review/1'},
    insights={'mode':'disabled_pending_content'},
    scoring={'mode':'task-completion/1','possible_points':95,'readable_target_per_property':20})
CONSOLIDATION_RUN_POLICY['literature'] = {
    'unit':'confirmed_property','strategy':'metadata-materials/1','sort':'score desc',
    'candidate_batch_size':40,'maximum_candidates':120,'selected_limit':20,
    'main_maximum_pages':4,'rewrite_maximum_pages':2,'page_rows':40,
    'page_transport_retries':1,'timeout_seconds':30,'read_timeout_seconds':20,
    'replacement':'metadata-qualified-backups','citation_expansion':False,
    'full_search':False,'maximum_query_rewrites':1}
CONSOLIDATION_RUN_POLICY['reading']['review']='unified-quality/1'
# Published following the recorded component/short-chain gates. This affects
# only newly confirmed requests; historical frozen policies are never rewritten.
NORMAL_RUN_POLICY = deepcopy(CONSOLIDATION_RUN_POLICY)
NORMAL_RUN_POLICY.update(version='insight-integration/2',
    insights={'mode':'dot_author/1','version':'insight-integration/2'},
    scoring={'mode':'task-completion/1','possible_points':100,'readable_target_per_property':20})
INSIGHT_RUN_POLICY = deepcopy(NORMAL_RUN_POLICY)
LITERATURE_RELEASE = 'retrieval-release/1'
NORMAL_RUN_POLICY['version'] = LITERATURE_RELEASE
NORMAL_RUN_POLICY['literature'].update(
    release=LITERATURE_RELEASE,
    strategy_profile={'P':'P0','S':'S2','F':'F1','D':'D1'},
    maximum_search_pages=6)

# Explicit candidate selection: do not silently upgrade the active release or
# any historical request. The chosen policy becomes part of the query hash.
FEEDBACK_RELEASE = 'retrieval-feedback/1'
FEEDBACK_RUN_POLICY = deepcopy(NORMAL_RUN_POLICY)
FEEDBACK_RUN_POLICY['version'] = FEEDBACK_RELEASE
FEEDBACK_RUN_POLICY['literature'].update(
    release=FEEDBACK_RELEASE, maximum_candidates=320, maximum_search_pages=8,
    maximum_pages_per_expression=4, page_rows=40, selected_limit=20,
    strategy_profile={'P':'shared-feedback','S':'feedback-pages','F':'grounded-possible','D':'D1'},
    property_body_search=True, count_verified_long_downloads_separately=True,
    replacement='qualified-backups-feedback-pages')

# Keep the candidate template above stable for already frozen material runs.
# New ordinary confirmations publish its full-query execution contract.
PUBLISHED_FEEDBACK_POLICY = deepcopy(FEEDBACK_RUN_POLICY)
PUBLISHED_FEEDBACK_POLICY['literature']['execution_mode'] = 'normal-query/1'
PUBLISHED_FEEDBACK_POLICY['documents']['manuscript_contract'] = 'identity-and-body/1'

# Install this ordinary presentation release only after its recorded gates.
# Historical policies remain literal parts of their own confirmed requests.
RESEARCH_DELIVERY_RELEASE = 'research-delivery/1'
RESEARCH_DELIVERY_POLICY = deepcopy(PUBLISHED_FEEDBACK_POLICY)
RESEARCH_DELIVERY_POLICY.update(version=RESEARCH_DELIVERY_RELEASE,
    insights={'mode':'dot_author/1','version':'research-property-short-2',
              'presentation':'research-property/1','final_model':'qwen3.8-max'},
    delivery={'export_schema_version':2})


def request_policy(configuration, preferences=None):
    version = configuration.runtime.get('retrieval_policy_version', FEEDBACK_RELEASE)
    if version not in {LITERATURE_RELEASE, FEEDBACK_RELEASE}:
        raise DomainError('LITERATURE_RELEASE_INVALID', 'Unknown request retrieval policy')
    presentation=configuration.runtime.get('research_delivery_version')
    if presentation not in {None,RESEARCH_DELIVERY_RELEASE}:
        raise DomainError('RESEARCH_DELIVERY_RELEASE_INVALID','Unknown research delivery release')
    if presentation==RESEARCH_DELIVERY_RELEASE:
        if version!=FEEDBACK_RELEASE:
            raise DomainError('RESEARCH_DELIVERY_RELEASE_INVALID','当前交付版本应绑定已发布的检索基线')
        policy = deepcopy(RESEARCH_DELIVERY_POLICY)
    else:
        policy = deepcopy(PUBLISHED_FEEDBACK_POLICY if version == FEEDBACK_RELEASE else NORMAL_RUN_POLICY)
    from .retrieval_preferences import resolve_preferences
    selected = resolve_preferences(configuration, preferences)
    policy['literature'].update(selected_limit=selected['papers_per_property'], sort=selected['ads_sort'])
    policy['scoring']['readable_target_per_property'] = selected['papers_per_property']
    if version == FEEDBACK_RELEASE:
        policy['catalog'].update(discovery_protocol='dynamic-metadata/2',
            metadata_result_limits=[100,300], maximum_feedback_queries=2,
            time_policy='initial-catalog-20min/1', discovery_seconds=150,
            resource_selection_seconds=300, selection_seconds=480,
            stop_dispatch_seconds=1140, end_seconds=1200)
        policy['quality']['official_table_review'] = 'shared_semantics/1'
        policy['quality']['catalog_table_review'] = 'shared_semantics/1'
        policy['insights'].update(presentation='material-summary/1', final_model='qwen3.8-flash')
        policy['delivery'] = {'export_schema_version': 2}
    # Only new current-release confirmations adopt the composite presentation.
    # Explicit legacy releases and historical frozen policies stay literal.
    if version == FEEDBACK_RELEASE:
        policy['insights'].update(presentation='research-workbench/2', final_model='qwen3.8-max')
    # Local experiment launch only; no public create/draft action gains overrides.
    import os
    if os.environ.get('ASTROQUERY_STOP_AFTER_EXTRACTION') == '1':
        from .extraction_experiment import VERSION
        policy['execution'] = {'experiment': VERSION, 'stop_after_extraction': True}
    return policy


def literature_strategy(spec):
    """Resolve only this request's frozen version; never upgrade old requests."""
    policy = spec.get('run_policy', {}).get('literature', {})
    if policy.get('release') == FEEDBACK_RELEASE:
        profile = FEEDBACK_RUN_POLICY['literature']['strategy_profile']
        if policy.get('strategy_profile') != profile or policy.get('experiment'):
            raise DomainError('LITERATURE_RELEASE_INVALID', 'Invalid feedback candidate profile')
        if policy.get('execution_mode') == 'normal-query/1' and policy.get('stop_after_materials'):
            raise DomainError('LITERATURE_RELEASE_INVALID', 'Published feedback requests cannot stop at research materials')
        return dict(profile)
    if policy.get('release') == LITERATURE_RELEASE:
        profile = policy.get('strategy_profile')
        if profile != {'P':'P0','S':'S2','F':'F1','D':'D1'}:
            raise DomainError('LITERATURE_RELEASE_INVALID', 'Frozen release profile does not match its version')
        if policy.get('experiment') or policy.get('stop_after_materials'):
            raise DomainError('LITERATURE_RELEASE_INVALID', 'Published requests cannot enable research-only execution')
        return dict(profile)
    value = policy.get('experiment')
    return dict(value) if isinstance(value, dict) else {}


def consolidated(spec):
    return spec.get('run_policy',{}).get('workflow_contract')=='backend-consolidation/1'
CATALOG_JOBS = {"catalog_discover", "catalog_extract"}
current_job = ContextVar("scientific_job", default=None)


def frozen_policy(repo, conn, tid):
    task = repo.task(conn, tid)
    if not task["query_ref"]:
        return None
    ref = loads(task["query_ref"])
    return repo.object(conn, tid, "confirmed_query", ref["id"], ref["version"]).get("run_policy")


def catalog_window(repo, conn, tid):
    rows = repo.objects(conn, tid, "catalog_window")
    return rows[0] if rows else None


def save_window(repo, conn, tid, value):
    prior = catalog_window(repo, conn, tid)
    value = {**value, "revision": prior["revision"] + 1 if prior else 1}
    repo.put_object(conn, tid, "catalog_window", tid, value["revision"], value)
    return value


def ensure_window(repo, conn, job, *, now=None):
    if job["kind"] not in CATALOG_JOBS:
        return None
    tid = job["task_id"]
    window = catalog_window(repo, conn, tid)
    if window:
        return window
    policy = frozen_policy(repo, conn, tid)
    if not policy or "end_seconds" not in policy.get("catalog", {}):
        return None  # Historical tasks keep their frozen execution semantics.
    window = save_window(repo, conn, tid, {
        "schema_version": "InitialCatalogWindow/1", "started_at": time.time() if now is None else now,
        "policy": deepcopy(policy["catalog"]), "paused_seconds": 0, "paused_at": None,
        "closed": False, "finished_at": None,
    })
    repo.event(conn, tid, "catalog_window_started", window)
    return window


def elapsed(window, *, now=None):
    now = (window.get('finished_at') if window.get('closed') and window.get('finished_at') is not None
           else time.time()) if now is None else now
    return max(0, now - window["started_at"] - window["paused_seconds"]
               - (now - window["paused_at"] if window.get("paused_at") is not None else 0))


def remaining(repo, conn, job, *, dispatch=False, now=None):
    if not job or job["kind"] not in CATALOG_JOBS:
        return None
    window = catalog_window(repo, conn, job["task_id"])
    if not window:
        return None
    key = "stop_dispatch_seconds" if dispatch else "end_seconds"
    return 0 if window["closed"] else max(0, window["policy"][key] - elapsed(window, now=now))


def guard(repo, conn, job, *, dispatch=False, now=None):
    left = remaining(repo, conn, job, dispatch=dispatch, now=now)
    if left is not None and left <= 0:
        raise DomainError("CATALOG_DISPATCH_CLOSED" if dispatch else "CATALOG_WINDOW_EXPIRED",
                          "本次星表为控制耗时已停止派发" if dispatch else "本次星表时间窗口已结束")
    return remaining(repo, conn, job, now=now)


def dispatch_remaining(repo, job=None):
    job = job or current_job.get()
    if not job or job["kind"] not in CATALOG_JOBS:
        return None
    with repo.read() as conn:
        return guard(repo, conn, job, dispatch=True)


def user_pause(repo, conn, tid, action, *, now=None):
    window = catalog_window(repo, conn, tid)
    if not window or window["closed"]:
        return
    now = time.time() if now is None else now
    if action == "pause" and window.get("paused_at") is None:
        save_window(repo, conn, tid, {**window, "paused_at": now})
    elif action in {"continue", "retry"} and window.get("paused_at") is not None:
        save_window(repo, conn, tid, {**window, "paused_at": None,
                    "paused_seconds": window["paused_seconds"] + max(0, now - window["paused_at"])})


def stop_job(repo, conn, job, reason):
    tid = job["task_id"]
    repo.put_object(conn, tid, "coverage", "catalog-time-" + job["job_id"], 1,
        {"owner": "M03", "state": "partial", "reason": reason,
         "outcome": "not_checked_time_control", "table_id": job["payload"].get("table_id"),
         "meaning": "本次为控制耗时未查或未完成；不是已查无值或访问失败"})
    conn.execute("UPDATE jobs SET status='not_run',reason=?,lease_token=NULL,lease_until=NULL WHERE job_id=?",
                 (reason, job["job_id"]))
    if job["kind"] == "catalog_discover":
        for name in ("catalog_hints", "catalog_discovery"):
            prior = conn.execute('SELECT state,watermark FROM producers WHERE task_id=? AND producer_id=?', (tid, name)).fetchone()
            if not prior or prior['state'] != 'closed':
                repo.producer(conn, tid, name, close_reason=reason, watermark=prior['watermark'] if prior else 0)
        repo.close_failed_metadata_dependencies(conn, tid, reason)
    repo.event(conn, tid, "job_state_changed", {"job_id": job["job_id"], "status": "not_run", "reason": reason})


def sweep_ready(repo, conn, *, task_id=None, now=None):
    """Close throttled/future jobs too; backoff cannot extend the frozen limit."""
    changed = set()
    rows = conn.execute("SELECT j.* FROM jobs j JOIN tasks t USING(task_id) WHERE j.kind IN ('catalog_discover','catalog_extract') AND j.status IN ('ready','waiting_dependency') AND t.lifecycle IN ('running','queued') AND (? IS NULL OR j.task_id=?)", (task_id, task_id)).fetchall()
    for row in rows:
        job = dict(row)
        job["payload"] = loads(job["payload"])
        left = remaining(repo, conn, job, dispatch=True, now=now)
        if left is not None and left <= 0:
            stop_job(repo, conn, job, "CATALOG_DISPATCH_CLOSED")
            changed.add(job["task_id"])
    # A later literature job can still be running when expired catalog jobs
    # drain. Closing their clock must not wait for that unrelated stage.
    # Start from the small active-task set. Joining objects first made every
    # idle worker scan the entire historical object index on each poll, starving
    # ordinary HTTP file streaming even with no scientific work in flight.
    candidates = conn.execute("SELECT t.task_id FROM tasks t "
        "WHERE t.lifecycle IN ('running','queued') AND (? IS NULL OR t.task_id=?) "
        "AND EXISTS(SELECT 1 FROM objects o WHERE o.task_id=t.task_id "
        "AND o.kind='catalog_window')", (task_id, task_id)).fetchall()
    clock = time.time() if now is None else now
    for row in candidates:
        tid = row[0]
        window = catalog_window(repo, conn, tid)
        if window['closed'] or elapsed(window, now=clock) < window['policy']['stop_dispatch_seconds']:
            continue
        jobs = conn.execute("SELECT job_id,status FROM jobs WHERE task_id=? "
                            "AND kind IN ('catalog_discover','catalog_extract')", (tid,)).fetchall()
        if not jobs or any(j['status'] in {'ready','running','waiting_dependency','awaiting_review'} for j in jobs):
            continue
        # The event timestamp also repairs a resumed drain whose clock was
        # not closed before a downstream job started. It never extends/restarts
        # the original window or hides a request that actually ran late.
        ids = {j['job_id'] for j in jobs}
        ended = []
        from datetime import datetime
        for event_row in conn.execute('SELECT payload FROM events WHERE task_id=? ORDER BY seq DESC', (tid,)):
            event = loads(event_row[0]); payload = event.get('payload', {})
            if payload.get('job_id') in ids and payload.get('status') in {'succeeded','failed','not_run','cancelled'}:
                timestamp = datetime.fromisoformat(event['committed_at']).timestamp()
                if window['started_at'] <= timestamp <= clock:
                    ended.append(timestamp)
        finished = max(ended) if ended else clock
        save_window(repo, conn, tid, {**window, 'closed': True, 'finished_at': finished,
            'elapsed_seconds': elapsed(window, now=finished), 'completion_basis': 'initial_catalog_terminal_events'})
        pools = repo.objects(conn, tid, 'catalog_pool')
        if pools and not pools[0]['closed']:
            pool = {**pools[0], 'closed': True, 'revision': pools[0]['revision'] + 1}
            repo.put_object(conn, tid, 'catalog_pool', tid, pool['revision'], pool)
        changed.add(tid)
    return changed


def endpoint_key(service, url):
    from urllib.parse import urlsplit
    p = urlsplit(url)
    route = '/viz-bin/ReadMe' if '/viz-bin/ReadMe' in p.path else p.path
    return 'endpoint-' + digest([service, p.netloc.casefold(), route])


def endpoint_cooling(repo, tid, service, url):
    job = current_job.get()
    if not job or job['task_id'] != tid or job['kind'] not in CATALOG_JOBS:
        return False
    key = endpoint_key(service, url)
    with repo.read() as conn:
        rows = [x for x in repo.objects(conn, tid, 'endpoint_cooldown') if x['endpoint_id'] == key]
        return bool(rows and rows[0]['until'] > time.time())


def cool_endpoint(repo, tid, service, url, reason):
    job = current_job.get()
    if not job or job['task_id'] != tid or job['kind'] not in CATALOG_JOBS:
        return
    key = endpoint_key(service, url)
    with repo.transaction() as conn:
        window = catalog_window(repo, conn, tid)
        if not window:
            return
        old = next((x for x in repo.objects(conn, tid, 'endpoint_cooldown') if x['endpoint_id'] == key), None)
        version = old['revision'] + 1 if old else 1
        repo.put_object(conn, tid, 'endpoint_cooldown', key, version,
            {'endpoint_id': key, 'revision': version, 'service': service,
             'until': time.time() + max(0, window['policy']['end_seconds'] - elapsed(window)),
             'reason': reason, 'scope': 'task_endpoint_operation_not_empty_result'})


def claim_table_repair(repo, job):
    if not job or job['kind'] != 'catalog_extract':
        return True
    tid, table = job['task_id'], job['payload']['table_id']
    key = 'table-repair-' + digest(table)
    with repo.transaction() as conn:
        if not catalog_window(repo, conn, tid):
            return True
        if any(x['table_id'] == table for x in repo.objects(conn, tid, 'catalog_repair')):
            return False
        repo.put_object(conn, tid, 'catalog_repair', key, 1,
            {'table_id': table, 'job_id': job['job_id'], 'maximum': 1})
        return True
