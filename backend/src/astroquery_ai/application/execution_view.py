"""Public execution facts, reconstructed at an event cursor without scientific work.

Jobs are mutable scheduler rows. Their statuses and running intervals must come
from events, never from the current row when inspecting a past cursor.
"""
from collections import Counter, defaultdict
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime
import re

from astroquery_ai.runtime.codec import loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.stages import JOB_STAGE
from .presentation import EXECUTION, STAGES, TERMINAL, history, history_scope, seconds

OPERATIONS = {
    'prepare': '理解查询', 'catalog_discover': '发现星表', 'catalog_extract': '读取星表',
    'literature_discover': '检索论文', 'material_prepare': '筛选与准备论文',
    'acquire_window': '分配正文获取', 'acquire_work': '获取论文正文',
    'attachment_discover': '发现官方附件', 'attachment_extract': '读取官方附件',
    'paper_batch': '阅读正文批次', 'paper_figures': '获取研究图像',
    'paper_figure_page': '读取图像原页', 'source_reconcile': '整理作品内候选',
    'citation_enrich': '解析原文引用', 'quality_citation_enrich': '补充引用资料',
    'quality_verify': '核验提取', 'quality_reextract': '局部重新提取',
    'assess_batch': '核验候选批次', 'apply_source_recheck': '应用原文复检',
    'apply_review': '应用人工判断', 'review_source_gap': '检查来源缺口',
    'interpret_uncertainty': '核实不确定度', 'normalize': '清洗测量表示',
    'compare_results': '对照测量', 'finalize': '准备交付', 'insights': '生成科研洞察',
}
STATES = {'running': '运行中', 'succeeded': '成功', 'failed': '失败',
          'ready': '等待运行', 'waiting_resource': '等待资源', 'cancelled': '已取消',
          'not_run': '未运行', 'waiting_dependency': '等待前置作业',
          'awaiting_review': '等待人工判断', 'unknown': '状态未记录',
          'ended_unknown': '结束状态未记录'}
EVENT_LABELS = {
    'execution_stage_changed': '进入阶段', 'task_state_changed': '任务状态变化',
    'query_confirmed': '查询已确认', 'draft_changed': '查询草稿更新',
    'question_ready': '请求确认已就绪', 'job_state_changed': '作业状态变化',
    'job_retry_scheduled': '安排重试', 'job_waiting_resource': '等待可用资源',
    'batch_committed': '批次结果已保存', 'producer_closed': '材料生产已结束',
    'review_ready': '提出人工判断', 'answer_received': '收到人工回答',
    'review_applied': '应用人工判断', 'review_withdrawn': '撤回人工问题',
    'science_sealed': '科研数据已封存', 'delivery_ready': '交付修订已发布',
    'insight_unit_updated': '逐性质洞察更新', 'insight_updated': '洞察报告更新',
    'export_updated': '科研导出已更新', 'export_ready': '科研导出已就绪',
    'reading_allocations_frozen': '阅读范围已确定', 'budget_changed': '模型调用状态更新',
    'dependency_closed': '前置依赖已处理',
}
REVIEW_KINDS = {'review_ready', 'answer_received', 'review_applied', 'review_withdrawn'}
SERVICES = {'ads': 'ADS', 'simbad': 'SIMBAD', 'vizier': 'VizieR', 'publisher': '出版方',
            'arxiv': 'arXiv', 'unpaywall': '开放获取服务', 'dashscope': '模型服务'}
ERRORS = {
    'PROPERTY_SELECTION_SCHEMA': ('model', '性质选择响应格式不符合要求'),
    'CATALOG_IDENTITY_LIMITATION_SCOPE': ('science', '星表对象核验范围不足'),
    'MODEL_INPUT_LIMIT': ('model', '模型输入超过本次允许范围'),
    'MODEL_OUTPUT_INVALID': ('model', '模型响应格式无法读取'),
    'MODEL_TIMEOUT': ('model', '模型调用超时'),
    'HTTP_TIMEOUT': ('service', '服务访问超时'),
    'HTTP_STATUS': ('service', '服务返回访问异常'),
    'PDF_PARSE_FAILED': ('processing', '正文解析未完成'),
}
LINK_FIELDS = {'work_id', 'source_id', 'measurement_id', 'property_id', 'batch_id',
               'reading_batch_id', 'table_id', 'review_id', 'candidate_id'}


def public_id(value):
    """IDs are links, never arbitrary diagnostic text, URLs or local paths."""
    if not isinstance(value, str) or not 0 < len(value) <= 200:
        return None
    if re.match(r'(?i)(?:[a-z]:[\\/]|https?://|file:|[/\\])', value):
        return None
    return value if re.fullmatch(r'[\w .:/+*()\-]+', value) else None


def error_info(value):
    code = value if isinstance(value, str) and value in ERRORS else None
    group, label = ERRORS.get(code, ('processing', '此项执行未完成'))
    if code and code.startswith(('HTTP_', 'NETWORK_', 'ADS_', 'VIZIER_', 'SIMBAD_')):
        group, label = 'service', '外部服务访问未完成'
    elif code and code.startswith(('MODEL_', 'LLM_', 'RESPONSE_')) and code not in ERRORS:
        group, label = 'model', '模型调用未完成'
    return {'code': code, 'category': group, 'message': label}


def public_title(value):
    text = str(value or '查询执行过程')[:500]
    text = re.sub(r'(?i)bearer\s+\S+', '[已隐藏]', text)
    text = re.sub(r'(?i)(?:api[_-]?key|token|password|secret)\s*[=:]\s*\S+', '[已隐藏]', text)
    return re.sub(r'(?:[A-Za-z]:[\\/]|https?://)\S+', '[地址已隐藏]', text)


def instant(value):
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return None


def union_seconds(intervals):
    pairs = sorted((instant(x['start']), instant(x['end'])) for x in intervals
                   if instant(x.get('start')) is not None and instant(x.get('end')) is not None
                   and instant(x['end']) >= instant(x['start']))
    total, right = 0, None
    for start, end in pairs:
        if end < start:
            continue
        total += end - start if right is None or start > right else max(0, end - right)
        right = max(right or end, end)
    return total if pairs else None


def page(items, offset, limit, focus_seq=None):
    offset, limit = max(0, offset), min(100, max(1, limit))
    if focus_seq is not None:
        index = next((i for i, item in enumerate(items) if item.get('seq') == focus_seq), None)
        if index is not None:
            offset = index // limit * limit
    return {'items': items[offset:offset + limit], 'total': len(items),
            'offset': offset, 'limit': limit}


def object_links(payload):
    return {key: public_id(payload[key]) for key in LINK_FIELDS
            if public_id(payload.get(key)) is not None}


def project(application, task_id, at_seq=None):
    return deepcopy(_cached_project(application, task_id, at_seq))


def _cached_project(application, task_id, at_seq=None):
    from .execution_cache import reconstruction
    return reconstruction(application, task_id, at_seq,
                          lambda conn, rows: _project(application, task_id, at_seq, conn, rows))


def _project(application, task_id, at_seq=None, snapshot=None, event_payloads=None):
    """All data in the returned model is safe for JSON, copying and PDF reports."""
    with (nullcontext(snapshot) if snapshot is not None else application.repository.read()) as conn:
        if event_payloads is None:
            task, source, cursor, cutoff, events = history(application, conn, task_id, at_seq)
        else:
            task, source, cursor, _ = history_scope(application, conn, task_id, at_seq)
            events = [loads(raw) for raw in event_payloads]
            cutoff = events[-1]['committed_at'] if events else task['created_at']
        metadata = {r['job_id']: dict(r) for r in conn.execute(
            'SELECT job_id,kind,payload,created_at FROM jobs WHERE task_id=? AND created_at<?',
            (source, cutoff))}
        # An event is stronger than a timestamp when a job starts in the same tick.
        seen_jobs = {e['payload']['job_id'] for e in events if e['payload'].get('job_id')}
        for jid in seen_jobs - metadata.keys():
            row = conn.execute('SELECT job_id,kind,payload,created_at FROM jobs WHERE task_id=? AND job_id=?',
                               (source, jid)).fetchone()
            if row:
                metadata[jid] = dict(row)
        edges = [dict(r) for r in conn.execute(
            'SELECT d.* FROM job_dependencies d JOIN jobs j ON j.job_id=d.job_id WHERE j.task_id=?', (source,))]
        model_rows = [dict(r) for r in conn.execute(
            'SELECT attempt_id,job_id,model,status,created_at,dispatched_at,settled_at,receipt FROM attempts WHERE task_id=? AND created_at<?',
            (source, cutoff))]
        http_rows = [dict(r) for r in conn.execute(
            'SELECT attempt_id,service,status,started_at,completed_at,status_code,error_code,request_hash FROM http_attempts WHERE task_id=? AND started_at<?',
            (source, cutoff))]
        resolutions = {r['object_id']: (r['created_at'], loads(r['payload'])) for r in conn.execute(
            "SELECT object_id,created_at,payload FROM objects WHERE task_id=? AND kind='dependency_resolution' AND created_at<? ORDER BY version",
            (source, cutoff))}

    jobs = {}
    for jid, row in metadata.items():
        links = object_links(loads(row['payload']))
        jobs[jid] = {'job_id': jid, 'kind': row['kind'], 'name': OPERATIONS.get(row['kind'], '业务作业'),
                     'stage_id': EXECUTION.get(JOB_STAGE.get(row['kind']), 'understand'),
                     'status': 'ready', 'created_at': row['created_at'], 'links': links,
                     'runs': [], 'waits': [], 'events': [], 'retries': [], 'model_attempts': [],
                     'dependencies': [], 'dependents': []}
    lifecycle, terminal_at, terminal_seq = 'clarifying', None, None
    delivery_ref = None
    visits, waits, pauses, public_events, review_issues = [], [], [], [], {}
    opened = human = pause = None
    waiting_reviews = set()
    current_stage = 'understand'
    for event in events:
        p, kind, at, seq = event['payload'], event['kind'], event['committed_at'], event['seq']
        jid = p.get('job_id')
        job = jobs.get(jid)
        explicit_stage = EXECUTION.get(p.get('stage_id'))
        stage = explicit_stage or (job['stage_id'] if job else current_stage)
        if kind == 'execution_stage_changed':
            if opened:
                opened.update(end=at, end_seq=seq)
            current_stage = stage
            opened = {'visit_id': f'{stage}:{seq}', 'stage_id': stage, 'seq': seq, 'start': at,
                      'end': None, 'end_seq': None, 'execution_stage': p.get('stage_id'),
                      'local_repair': bool(p.get('local_repair')), 'previous_visit_id': visits[-1]['visit_id'] if visits else None}
            visits.append(opened)
        if kind == 'task_state_changed':
            lifecycle = p.get('lifecycle', lifecycle)
            if human and lifecycle not in {'waiting_review', 'waiting_input'}:
                human.update(end=at, end_seq=seq)
                human = None
            if lifecycle in {'waiting_review', 'waiting_input'} and human is None:
                human = {'start': at, 'end': None, 'seq': seq, 'stage_id': current_stage}
                waits.append(human)
            if pause and lifecycle not in {'paused', 'pausing'}:
                pause.update(end=at, end_seq=seq)
                pause = None
            if lifecycle == 'paused' and pause is None:
                pause = {'start': at, 'end': None, 'seq': seq}
                pauses.append(pause)
            if lifecycle in TERMINAL:
                terminal_at, terminal_seq = at, seq
                if opened and not opened['end']:
                    opened.update(end=at, end_seq=seq)
        if kind == 'query_confirmed':
            lifecycle = 'running'
        if kind == 'review_ready':
            waiting_reviews.add(p.get('review_id'))
        if kind in {'review_applied', 'review_withdrawn'}:
            waiting_reviews.discard(p.get('review_id'))
        if kind in {'review_applied', 'review_withdrawn'} and human and not waiting_reviews:
            human.update(end=at, end_seq=seq)
            human = None
            lifecycle = 'running'
        if kind == 'delivery_ready':
            ref = p.get('delivery_ref') or {}
            if public_id(ref.get('id')) and type(ref.get('version')) is int:
                delivery_ref = {'id': ref['id'], 'version': ref['version']}
        links = {**(job['links'] if job else {}), **object_links(p)}
        category = 'review' if kind in REVIEW_KINDS or kind == 'question_ready' else (
            'stage' if kind in {'execution_stage_changed', 'task_state_changed', 'query_confirmed'} else
            'job' if kind.startswith('job_') else 'material' if kind in {'batch_committed', 'reading_allocations_frozen'} else
            'delivery' if kind in {'science_sealed', 'delivery_ready'} or kind.startswith('export_') else
            'model' if kind == 'budget_changed' else 'insight' if kind.startswith('insight_') else 'other')
        status = p.get('status') if p.get('status') in STATES else None
        row = {'seq': seq, 'at': at, 'kind': kind if re.fullmatch(r'[a-z_]{1,65}', kind) else 'other',
               'stage_id': stage, 'stage_basis': 'explicit' if explicit_stage else 'job' if job else 'visit_time',
               'category': category, 'label': EVENT_LABELS.get(kind, '执行记录'), 'job_id': jid if job else None,
               'object_label': job['name'] if job else None, 'status': status, 'links': links,
               'exception': kind == 'job_retry_scheduled' or kind == 'job_state_changed' and status == 'failed'}
        if row['exception']:
            row['diagnostic'] = error_info(p.get('reason'))
        if kind == 'review_applied':
            receipt = p.get('receipt') or {}
            row['review_result'] = {key: receipt.get(key) for key in ('status', 'comparison_outcome', 'postcheck')
                                    if isinstance(receipt.get(key), str) and receipt.get(key) in {'applied', 'succeeded', 'passed', 'completed', 'pending',
                                                           'different_conditions', 'confirmed_conflict', 'no_conflict', 'kept', 'not_required'}}
        if kind == 'batch_committed':
            row['counts'] = {key: p[key] for key in ('candidate_count', 'admitted_count') if type(p.get(key)) is int}
        public_events.append(row)
        if kind in REVIEW_KINDS and links.get('review_id'):
            rid = links['review_id']
            issue = review_issues.setdefault(rid, {'issue_id': 'review:' + rid, 'seq': seq, 'at': at,
                'stage_id': stage, 'job_id': None, 'category': 'science', 'recovery': 'unresolved',
                'message': '此处需要人工判断测量的含义或条件', 'actions': [], 'links': links})
            issue['actions'].append(row)
            if kind == 'review_ready':
                issue['recovery'] = 'unresolved'
            if kind in {'review_applied', 'review_withdrawn'}:
                issue['recovery'] = 'resolved'
        if not job:
            continue
        job['events'].append(row)
        if kind == 'job_state_changed':
            job['status'] = status or 'unknown'
            if status == 'running':
                for wait in job['waits']:
                    if not wait.get('end'):
                        wait.update(end=at, end_seq=seq)
                job['runs'].append({'seq': seq, 'start': at, 'end': None, 'status': 'running',
                                    'visit_id': opened['visit_id'] if opened else None})
            elif job['runs'] and not job['runs'][-1]['end']:
                job['runs'][-1].update(end=at, end_seq=seq, status=status or 'unknown')
        elif kind in {'job_waiting_resource', 'job_retry_scheduled'}:
            if job['runs'] and not job['runs'][-1]['end']:
                job['runs'][-1].update(end=at, end_seq=seq,
                    status='waiting_resource' if kind == 'job_waiting_resource' else 'failed')
            if kind == 'job_waiting_resource':
                job['status'] = 'waiting_resource'
                job['waits'].append({'seq': seq, 'start': at, 'end': None})
            else:
                job['status'] = 'ready'
                job['retries'].append(row)

    if cursor == task['last_event_seq'] and terminal_at is None:
        lifecycle = task['lifecycle']
    if visits:
        visits.insert(0, {'visit_id': 'understand:0', 'stage_id': 'understand', 'seq': 0,
            'start': task['created_at'], 'end': visits[0]['start'], 'end_seq': visits[0]['seq'],
            'execution_stage': 'understand', 'local_repair': False, 'previous_visit_id': None})
        visits[1]['previous_visit_id'] = visits[0]['visit_id']
    for visit in visits:
        visit['seconds'] = seconds(visit['start'], visit['end'])
        visit['observed_seconds'] = seconds(visit['start'], visit['end'] or cutoff)
        visit['state'] = 'ended' if visit['end'] else 'ended_unknown' if lifecycle in TERMINAL else 'running'
    for interval in waits + pauses:
        interval['seconds'] = seconds(interval['start'], interval['end'] or cutoff)
    issues = []
    peak_edges = []
    for job in jobs.values():
        for run in job['runs']:
            run['seconds'] = seconds(run['start'], run['end'])
            run['observed_seconds'] = seconds(run['start'], run['end'] or cutoff)
            if not run['end'] and (lifecycle in TERMINAL or opened and job['stage_id'] != current_stage):
                run['status'] = 'ended_unknown'
                job['status'] = 'ended_unknown'
            if run['status'] != 'ended_unknown' and instant(run['start']) is not None:
                end = run['end'] or cutoff
                peak_edges.extend([(instant(run['start']), 1, job['job_id']), (instant(end), -1, job['job_id'])])
        if job['status'] in {'ready', 'waiting_resource', 'running', 'awaiting_review', 'waiting_dependency'} and lifecycle in TERMINAL:
            job['status'] = 'ended_unknown'
        job['start'] = job['runs'][0]['start'] if job['runs'] else None
        job['end'] = job['runs'][-1]['end'] if job['runs'] else None
        job['seconds'] = union_seconds(job['runs'])
        job['run_count'] = len(job['runs'])
        job['retry_count'] = len(job['retries'])
        job['wait_count'] = len(job['waits'])
        job['status_label'] = STATES.get(job['status'], '状态未记录')
        failures = [e for e in job['events'] if e['exception']]
        if failures:
            first = failures[0]
            recovery = 'recovered' if job['status'] == 'succeeded' else (
                'partial' if lifecycle in TERMINAL and lifecycle == 'completed' else 'unresolved')
            issues.append({'issue_id': 'job:' + job['job_id'], 'seq': first['seq'], 'at': first['at'],
                'stage_id': job['stage_id'], 'job_id': job['job_id'], 'recovery': recovery,
                **first['diagnostic'], 'name': job['name'], 'links': job['links'],
                'occurrences': len(failures), 'actions': [e for e in job['events'] if e['kind'] != 'budget_changed'],
                'impact': '本作业后来已成功' if recovery == 'recovered' else
                          '本作业未取得成功结果，任务已继续并完成' if recovery == 'partial' else '尚无成功恢复记录'})
    active_jobs, peak = Counter(), 0
    for _, change, jid in sorted(peak_edges):
        active_jobs[jid] += change
        peak = max(peak, sum(value > 0 for value in active_jobs.values()))

    closed_dependencies = {event['payload'].get('resolution_ref', {}).get('id')
                           for event in events if event['kind'] == 'dependency_closed'}
    for edge in edges:
        child, parent = jobs.get(edge['job_id']), jobs.get(edge['dependency_id'])
        if not child or not parent:
            continue
        resolution = 'required'
        ref = loads(edge['resolution_ref']) if edge['resolution_ref'] else {}
        resolution_at, saved = resolutions.get(ref.get('id'), (None, {}))
        if resolution_at and resolution_at < cutoff and ref.get('id') in closed_dependencies:
            resolution = saved.get('resolution', 'required')
        view = {'job_id': parent['job_id'], 'name': parent['name'], 'status': parent['status'],
                'resolution': resolution if resolution in {'required', 'closed_without_result'} else 'unknown'}
        child['dependencies'].append(view)
        parent['dependents'].append({**view, 'job_id': child['job_id'], 'name': child['name'], 'status': child['status']})
    for row in model_rows:
        job = jobs.get(row['job_id'])
        if not job:
            continue
        settled = row['settled_at'] and row['settled_at'] < cutoff
        receipt = loads(row['receipt']) if settled and row['receipt'] else {}
        model = row['model'] if re.fullmatch(r'[a-zA-Z0-9.\-]{1,70}', row['model']) else None
        job['model_attempts'].append({'attempt_id': row['attempt_id'], 'model': model,
            'start': row['dispatched_at'] if row['dispatched_at'] and row['dispatched_at'] < cutoff else None,
            'end': row['settled_at'] if settled else None, 'status': row['status'] if settled else 'pending',
            'error': error_info(receipt.get('error_code')) if receipt.get('error_code') else None,
            'provider_status': receipt.get('provider_status') if type(receipt.get('provider_status')) is int else None,
            'rate_wait_seconds': receipt.get('rate_wait_seconds') if type(receipt.get('rate_wait_seconds')) in {int, float} else None})
    services = []
    service_groups = defaultdict(list)
    for row in http_rows:
        ended = row['completed_at'] and row['completed_at'] < cutoff
        service = {'attempt_id': row['attempt_id'], 'service': SERVICES.get(row['service'].lower(), '外部资料服务'),
            'start': row['started_at'], 'end': row['completed_at'] if ended else None,
            'seconds': seconds(row['started_at'], row['completed_at']) if ended else None,
            'status': row['status'] if ended and row['status'] in {'completed', 'failed', 'unknown'} else 'pending',
            'status_code': row['status_code'] if ended else None,
            'error': error_info(row['error_code']) if ended and row['error_code'] else None}
        services.append(service)
        service_groups[(row['service'], row['request_hash'])].append(service)
    service_issues = []
    for attempts in service_groups.values():
        attempts.sort(key=lambda a: a['start'])
        failures = [a for a in attempts if a['status'] == 'failed']
        if not failures:
            continue
        first = failures[0]
        recovered = attempts[-1]['status'] == 'completed' and attempts[-1]['start'] > first['start']
        service_issues.append({'issue_id': 'http:' + first['attempt_id'], 'seq': None,
            'at': first['start'], 'stage_id': None, 'category': 'service', 'job_id': None,
            'recovery': 'recovered' if recovered else 'partial' if lifecycle == 'completed' else 'unresolved',
            'message': first['service'] + '访问曾失败', 'name': first['service'],
            'links': {}, 'actions': [], 'service_attempts': attempts, 'occurrences': len(failures),
            'impact': '同一请求后来已取得响应' if recovered else '此请求没有已保存的成功响应，不能据此判断资料中没有数据'})

    stages = []
    for sid, name in STAGES[:-1]:
        own_visits = [v for v in visits if v['stage_id'] == sid]
        own_jobs = [j for j in jobs.values() if j['stage_id'] == sid]
        counts = dict(Counter(j['status'] for j in own_jobs))
        state = 'pending' if not own_visits and not own_jobs else (
            'running' if lifecycle not in TERMINAL and current_stage == sid else 'ended')
        stages.append({'id': sid, 'name': name, 'status': state, 'visits': own_visits,
            'seconds': union_seconds(own_visits), 'job_counts': counts, 'job_total': len(own_jobs),
            'human_wait_seconds': union_seconds([{**w, 'end': w['end'] or cutoff} for w in waits if w['stage_id'] == sid])})
    all_issues = sorted(issues + service_issues + list(review_issues.values()), key=lambda x: (x['at'], x['seq'] or 0))
    for index, visit in enumerate(visits):
        own_jobs = [job for job in jobs.values() if any(run['visit_id'] == visit['visit_id'] for run in job['runs'])]
        visible_events = [event for event in public_events if visit['seq'] <= event['seq']
                          and (visit['end_seq'] is None or event['seq'] < visit['end_seq'])]
        statuses = {}
        for event in visible_events:
            if event['job_id'] and event['status']:
                statuses[event['job_id']] = event['status']
        visit['job_total'] = len(own_jobs)
        visit['job_states'] = dict(Counter(statuses.get(job['job_id'], 'unknown') for job in own_jobs))
        visit['key_events'] = [event for event in visible_events if event['exception'] or event['category'] == 'review'][:8]
        visit['next_visit_id'] = visits[index + 1]['visit_id'] if index + 1 < len(visits) else None
    marks = [e for e in public_events if e['category'] == 'review' or e['exception'] or e['kind'] in {'science_sealed', 'delivery_ready'}]
    wall_end = terminal_at if lifecycle in TERMINAL else cutoff
    return {'schema_version': 'TaskExecutionView/2', 'task_id': task_id, 'source_task_id': source,
        'cursor': cursor, 'as_of': cutoff, 'title': public_title(task['title']), 'lifecycle': lifecycle,
        'created_at': task['created_at'], 'terminal_at': terminal_at, 'terminal_seq': terminal_seq,
        'wall_seconds': seconds(task['created_at'], wall_end), 'human_wait_seconds': union_seconds(
            [{**w, 'end': w['end'] or cutoff} for w in waits]), 'waits': waits, 'pauses': pauses,
        'delivery_ref': delivery_ref, 'stages': stages, 'visits': visits, 'markers': marks,
        'jobs': jobs, 'events': public_events, 'issues': all_issues, 'services': services,
        'summary': {'jobs': len(jobs), 'job_states': dict(Counter(j['status'] for j in jobs.values())),
            'visited_stages': len({v['stage_id'] for v in visits}), 'peak_running_jobs': peak if peak_edges else None,
            'run_segments': sum(j['run_count'] for j in jobs.values()), 'retries': sum(j['retry_count'] for j in jobs.values()),
            'resource_waits': sum(j['wait_count'] for j in jobs.values()),
            'exception_events': sum(e['exception'] for e in public_events), 'issues': len(issues),
            'issue_states': dict(Counter(i['recovery'] for i in issues + service_issues)),
            'service_issues': len(service_issues), 'http_failures': sum(s['status'] == 'failed' for s in services),
            'scientific_reviews': len(review_issues),
            'events': len(events), 'http_attempts': len(services), 'model_attempts': len(model_rows)},
        'history_complete': bool(visits and terminal_at) if lifecycle in TERMINAL else bool(visits)}


def read(application, task_id, at_seq=None, section='overview', stage_id=None, category=None,
         offset=0, limit=50, focus_seq=None, job_id=None, status=None, search=None,
         start=None, end=None, sort='time'):
    return deepcopy(_read(_cached_project(application, task_id, at_seq), section, stage_id, category,
                          offset, limit, focus_seq, job_id, status, search, start, end, sort))


def _read(data, section, stage_id, category, offset, limit, focus_seq, job_id, status, search, start, end, sort):
    identity = {key: data[key] for key in ('schema_version', 'task_id', 'cursor', 'as_of', 'delivery_ref')}
    if section == 'overview':
        return {k: v for k, v in data.items() if k not in {'events', 'issues', 'services', 'jobs'}}
    if section == 'job':
        if job_id not in data['jobs']:
            raise DomainError('JOB_NOT_VISIBLE', '此时点没有可读取的该项作业', 404)
        return {**identity, 'job': data['jobs'][job_id]}
    collection = {'events': data['events'], 'issues': data['issues'],
                  'jobs': [job_brief(j) for j in data['jobs'].values()], 'services': data['services']}
    if section not in collection:
        raise DomainError('EXECUTION_SECTION', '执行明细读取范围无效', 422)
    rows = collection[section]
    if stage_id:
        rows = [r for r in rows if r.get('stage_id') == stage_id]
    if category:
        rows = [r for r in rows if r.get('category') == category or
                category == 'exception' and r.get('exception') or r.get('recovery') == category]
    if status:
        rows = [r for r in rows if r.get('status') == status]
    if job_id:
        rows = [r for r in rows if r.get('job_id') == job_id]
    if start or end:
        for point in (start, end):
            if point and instant(point) is None:
                raise DomainError('EXECUTION_TIME_RANGE', '时间范围无效', 422)
        rows = [r for r in rows if instant(r.get('at') or r.get('start') or r.get('created_at')) is not None
                and (not start or instant(r.get('end') or r.get('at') or r.get('start') or r.get('created_at')) >= instant(start))
                and (not end or instant(r.get('at') or r.get('start') or r.get('created_at')) <= instant(end))]
    if search:
        needle = search[:200].casefold()
        rows = [r for r in rows if needle in ' '.join(str(r.get(k, '')) for k in
                ('name', 'kind', 'label', 'job_id', 'message', 'object_label', 'links')).casefold()]
    if section == 'jobs':
        if sort == 'duration':
            rows.sort(key=lambda r: (r['seconds'] is not None, r['seconds'] or 0), reverse=True)
        elif sort == 'retries':
            rows.sort(key=lambda r: r['retry_count'], reverse=True)
        else:
            rows.sort(key=lambda r: r.get('start') or r['created_at'])
    return {**identity, **page(rows, offset, limit, focus_seq)}


def job_brief(job):
    keys = ('job_id', 'kind', 'name', 'stage_id', 'status', 'status_label', 'created_at', 'start',
            'end', 'seconds', 'run_count', 'retry_count', 'wait_count', 'links')
    return {**{key: job[key] for key in keys}, 'runs': job['runs'],
            'dependency_count': len(job['dependencies'])}
