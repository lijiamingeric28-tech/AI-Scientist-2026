"""Durable auxiliary reading runs; scientific tasks and deliveries stay sealed."""
import asyncio
from copy import deepcopy
from uuid import uuid4

from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads, utcnow
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science import material_analysis as analysis, property_insights as cards
from astroquery_ai.science.insight_inputs import explanation_wire
from astroquery_ai.science.workflow.context import ScienceContext

ACTIVE = {'queued', 'running'}


def scope_content(scope):
    # The current material is a reading anchor, not part of a whole-property
    # analysis input. Every material must reuse the same frozen comparison.
    return {key: value for key, value in scope.items()
            if not (scope.get('kind') == 'property_comparison' and key == 'material_id')}


def scope_key(scope):
    return digest({key: value for key, value in scope_content(scope).items() if key != 'task_id'})


def input_identity(scope, context, protocol=None):
    parts = [analysis.SCHEMA, analysis.MODEL_VERSION, scope_content(scope), context['content_sha256']]
    return digest(parts + ([protocol] if protocol else []))


def checked_state(row):
    state = loads(row['payload'])
    from astroquery_ai.science.task_knowledge import blocks
    blocks(state['context'])
    expected = input_identity(state['scope'], state['context'], state.get('input_protocol'))
    key = scope_key(state['scope'])
    if expected != row['input_hash'] or expected != state['input_hash'] or key != row['scope_key']:
        raise DomainError('MATERIAL_ANALYSIS_HASH', '补充运行输入引用校验失败', 409)
    return state


def permit_matches(repo, conn, task, owner, model, root_id, *, messages=None):
    if owner != 'M11' or model != 'qwen3.8-max' or not root_id.startswith('material-analysis-call-'):
        return False
    row = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='material_analysis_permit' "
                       "AND object_id=?", (task['task_id'], root_id)).fetchone()
    if not row:
        return False
    permit = loads(row[0])
    run = conn.execute('SELECT * FROM material_analysis_runs WHERE run_id=? AND task_id=?',
                       (permit['run_id'], task['task_id'])).fetchone()
    if (not run or run['status'] != 'running' or task['kind'] != 'live' or task['science_state'] != 'sealed'
            or task['lifecycle'] not in {'completed', 'budget_exhausted'}):
        return False
    try:
        saved = checked_state(run)
    except (DomainError, KeyError, ValueError, TypeError):
        return False
    scope = saved['scope']
    meta = conn.execute("SELECT content_sha256 FROM objects WHERE task_id=? AND kind='delivery' AND object_id=? AND version=?",
                        (scope['source_task_id'], scope['delivery_id'], scope['delivery_revision'])).fetchone()
    return (task['generation'] == permit['generation'] and permit['input_hash'] == saved['input_hash']
            and meta is not None and meta[0] == scope['delivery_sha256']
            and permit['model_version'] == analysis.MODEL_VERSION
            and (messages is None or permit['messages_hash'] == digest(messages)))


class MaterialAnalysisService:
    def __init__(self, app):
        self.app, self.repo = app, app.repository
        self._active, self._worker = {}, None
        self._closing = False
        with self.repo.transaction() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS material_analysis_runs (
                run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                scope_key TEXT NOT NULL, input_hash TEXT NOT NULL, status TEXT NOT NULL,
                payload BLOB NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
            c.execute('CREATE INDEX IF NOT EXISTS material_analysis_lookup ON material_analysis_runs(task_id,scope_key,created_at)')
            c.execute('''CREATE TABLE IF NOT EXISTS material_analysis_operations (
                task_id TEXT NOT NULL REFERENCES tasks(task_id), operation_id TEXT NOT NULL,
                request_hash TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES material_analysis_runs(run_id),
                PRIMARY KEY(task_id,operation_id))''')

    def profile(self):
        return ScienceContext(self.app).model_profile('M11', 'qwen3.8-max', version=analysis.MODEL_VERSION,
            max_input_tokens=cards.INPUT_LIMIT, max_output_tokens=analysis.OUTPUT_LIMIT,
            max_images=0, wall_seconds=240, inactivity_seconds=90)

    def _model_complete(self, c, tid, row):
        """Reading-only fallback revisions must not consume a model retry."""
        state = loads(row['payload'])
        refs = state.get('reports') or []
        if not refs:
            return False
        ref = refs[-1]
        report = self.repo.object(c, tid, 'material_analysis', ref['id'], ref['version'])
        if content_hash(report) != ref['content_sha256']:
            raise DomainError('MATERIAL_ANALYSIS_HASH', '补充报告引用校验失败', 409)
        coverage = report.get('coverage') or {}
        requested, completed = set(coverage.get('requested_ids', [])), set(coverage.get('completed_ids', []))
        return (report.get('status') == 'complete'
                and report.get('generation_method') not in {
                    'saved_material_summary_reuse', 'saved_source_comparison', 'saved_batch_and_summary'}
                and len(requested) == state['scope']['record_count']
                and bool(requested) and requested <= completed)

    def _saved_material_readings(self, c, tid, state, requested):
        """Reuse independently saved source readings as synthesis inputs only."""
        if state['scope']['kind'] != 'property_comparison':
            return []
        seen, covered, results = set(), set(), []
        for row in c.execute("SELECT * FROM objects WHERE task_id=? AND kind='material_analysis' ORDER BY version DESC", (tid,)):
            if row['object_id'] in seen:
                continue
            seen.add(row['object_id'])
            report = loads(row['payload'])
            scope = report.get('scope', {})
            if (scope.get('kind') != 'material' or report.get('status') != 'complete'
                    or any(scope.get(key) != state['scope'].get(key) for key in (
                        'source_task_id', 'delivery_id', 'delivery_revision', 'delivery_sha256', 'snapshot_ref', 'property_id'))
                    or report.get('knowledge_context_sha256') != state['context']['content_sha256']
                    or report.get('generation_method') in {'saved_material_summary_reuse', 'saved_source_comparison', 'saved_batch_and_summary'}):
                continue
            coverage = report.get('coverage', {})
            ids = set(coverage.get('requested_ids', []))
            if (not ids or len(ids) != scope.get('record_count') or not ids <= requested - covered
                    or not ids <= set(coverage.get('completed_ids', []))):
                continue
            if content_hash(report) != row['content_sha256']:
                raise DomainError('MATERIAL_ANALYSIS_HASH', '复用资料解读引用校验失败', 409)
            ref = {'id': row['object_id'], 'version': row['version'], 'content_sha256': row['content_sha256']}
            results.append({'status': 'generated', 'measurement_ids': sorted(ids), 'reused_report_ref': ref,
                'reused_receipts': deepcopy(report.get('receipts', [])),
                'card': {'measurement_ids': sorted(ids), 'sections': deepcopy(report['sections']),
                    'recommendations': deepcopy(report['recommendations']), 'findings': report.get('findings', []),
                    'field_states': {}, 'validation_issues': [], 'warnings': deepcopy(report.get('warnings', [])),
                    'unverified_advice': deepcopy(report.get('unverified_advice', []))}})
            covered.update(ids)
        return results if covered == requested else []

    def _coordinates(self, c, tid, did, revision, mid, pid, kind, *, at_seq=None, sealed_only=False):
        task = self.repo.task(c, tid)
        view = self.app.delivery.display_scope(c, tid, did, revision, expected_revision=revision,
                                               at_seq=at_seq, sealed_only=sealed_only)
        header, index, _ = self.app.delivery.read_workbench(c, tid, did, revision,
            expected_revision=revision, at_seq=at_seq, sealed_only=sealed_only)
        if kind not in {'material', 'property_comparison'} or pid not in index.names:
            raise DomainError('MATERIAL_ANALYSIS_SCOPE', '请选择本资料及明确性质', 422)
        group = None
        if mid is not None or kind == 'material':
            group, pid = index.resolve(mid, pid)
        source_task = self.repo.task(c, view['source'])
        qref = loads(source_task['query_ref'])
        spec = self.repo.object(c, view['source'], 'confirmed_query', qref['id'], qref['version'])
        if spec.get('spec_hash') != digest({k: v for k, v in spec.items() if k != 'spec_hash'}):
            raise DomainError('FROZEN_SPEC_CORRUPT', '冻结规格哈希不匹配', 409)
        scope = {'task_id': tid, 'source_task_id': view['source'], 'delivery_id': did,
            'delivery_revision': view['revision'], 'delivery_sha256': view['sha'],
            'snapshot_ref': deepcopy(header['snapshot_ref']), 'material_id': group['group_id'] if group else None,
            'property_id': pid, 'property_name': index.names[pid], 'kind': kind,
            'record_count': len(set(index.record_ids(group, pid)) if kind == 'material' else
                {mid for own in index.groups.values() for mid in own['by_property'].get(pid, {}).get('records', [])})}
        key = scope_key(scope)
        return task, view, header, spec, scope, key

    def _allowed(self, task, tid, *, historical=False, sample_update=False):
        with self.repo.read() as c:
            origin = c.execute("SELECT payload FROM objects WHERE task_id=? AND kind='task_origin' AND object_id=? AND version=1", (tid, tid)).fetchone()
            if origin and loads(origin[0]).get('source') == 'sample' and not sample_update:
                return {'allowed': False, 'reason': 'READ_ONLY_DEMO', 'message': '演示样例仅供阅读；已保存的补充解读可切换版本查看。'}
        if historical or task['kind'] != 'live' or task['science_state'] != 'sealed' or task['lifecycle'] not in {'completed', 'budget_exhausted'}:
            return {'allowed': False, 'reason': 'MATERIAL_ANALYSIS_READ_ONLY', 'message': '退出历史回放并等待交付完成后，可创建独立补充解读。'}
        try:
            self.app.profile_authority.authorize(tid, 'M11', self.profile(), 1)
            return {'allowed': True}
        except DomainError as exc:
            return {'allowed': False, 'reason': exc.code, 'message': exc.message}

    def read(self, tid, did, revision, mid, pid, kind='material', *, report_version=None,
             at_seq=None, sealed_only=False, projection=None):
        with self.repo.read() as c:
            task, visible, header, spec, scope, key = self._coordinates(c, tid, did, revision, mid, pid, kind,
                at_seq=at_seq, sealed_only=sealed_only)
            before = visible['summary_before']
            rows = c.execute('SELECT run_id,status,payload,created_at FROM material_analysis_runs WHERE task_id=? AND scope_key=? '
                'AND (? IS NULL OR created_at<=?) ORDER BY created_at DESC', (visible['source'], key, before, before)).fetchall()
            versions = []
            for row in rows:
                state = loads(row['payload'])
                for ref in state.get('reports', []):
                    if before is None or ref['generated_at'] <= before:
                        versions.append(ref)
            versions.sort(key=lambda ref: ref['version'], reverse=True)
            selected = next((ref for ref in versions if report_version is None or ref['version'] == report_version), None)
            if report_version is not None and selected is None:
                raise DomainError('MATERIAL_ANALYSIS_VERSION', '该补充版本不在当前可见范围', 409)
            report = None
            if selected and projection != 'status':
                report = self.repo.object(c, visible['source'], 'material_analysis', selected['id'], selected['version'])
                expected_scope = {**scope, 'task_id': visible['source']}
                if content_hash(report) != selected['content_sha256'] or scope_content(report.get('scope', {})) != scope_content(expected_scope):
                    raise DomainError('MATERIAL_ANALYSIS_HASH', '补充报告引用校验失败', 409)
            saved = header.get('insight_report') or {}
            saved = (saved.get('property_report') or {}) if saved.get('schema_version') == 'InsightBundle/1' else saved
            comparison = next((card for card in saved.get('cards', []) if card.get('property_id') == pid), None)
            existing = {'card': comparison, 'knowledge_blocks': saved.get('knowledge_blocks', []),
                        'origin': 'saved_property_report', 'scope': 'all_property_records'} if comparison and projection != 'status' else None
            _, latest = self.app.delivery.delivery_reference(c, tid)
        permission = self._allowed(task, tid, historical=at_seq is not None or sealed_only or visible['source'] != tid
                or (latest['id'], latest['version']) != (did, scope['delivery_revision']))
        if scope['record_count'] == 0:
            permission = {'allowed': False, 'reason': 'MATERIAL_ANALYSIS_NO_RECORDS', 'message': '此范围未保存可分析的测量；已有题录、总结和背景继续可读。'}
        return {'delivery_id': did, 'delivery_revision': scope['delivery_revision'], 'scope': scope,
            'generation': permission,
            'versions': versions, 'report': report,
            'run': self.status(tid, rows[0]['run_id']) if rows and before is None else None,
            'existing_comparison': existing}

    def submit(self, tid, did, request, *, sample_update=False):
        required = {'operation_id', 'expected_delivery_revision', 'property_id', 'scope'}
        if (not isinstance(request, dict) or not required <= set(request) or set(request) - required - {'material_id'}
                or not all(isinstance(request[k], str) and request[k] for k in ('operation_id', 'property_id', 'scope'))
                or type(request['expected_delivery_revision']) is not int
                or (request.get('scope') != 'property_comparison' or request.get('material_id') is not None)
                and not (isinstance(request.get('material_id'), str) and request['material_id'])):
            raise DomainError('MATERIAL_ANALYSIS_REQUEST', '补充分析请求不完整', 422)
        request_hash = digest(request)
        with self.repo.read() as c:
            task, visible, _, spec, scope, key = self._coordinates(c, tid, did, request['expected_delivery_revision'],
                request.get('material_id'), request['property_id'], request['scope'])
            _, latest = self.app.delivery.delivery_reference(c, tid)
            if (latest['id'], latest['version']) != (did, request['expected_delivery_revision']):
                raise DomainError('DELIVERY_CHANGED', '请回到当前交付后创建补充分析', 409)
            if task['kind'] != 'live' or task['lifecycle'] not in {'completed', 'budget_exhausted'} or task['science_state'] != 'sealed':
                raise DomainError('MATERIAL_ANALYSIS_READ_ONLY', '当前任务只能读取已保存的内容', 409)
            if not scope['record_count']:
                raise DomainError('MATERIAL_ANALYSIS_NO_RECORDS', '此范围未保存可分析的测量', 409)
            if sample_update:
                from astroquery_ai.runtime.published_demos import PublishedDemos
                origin = c.execute("SELECT payload FROM objects WHERE task_id=? AND kind='task_origin' AND object_id=? AND version=1", (tid, tid)).fetchone()
                entry = PublishedDemos(self.app).index.get(tid)
                if not origin or loads(origin[0]).get('source') != 'sample' or not entry or entry['snapshot_ref'] != scope['snapshot_ref']:
                    raise DomainError('SAMPLE_UPDATE_SCOPE', '维护更新仅限当前已安装样例的准确科学快照', 409)
            permission = self._allowed(task, tid, sample_update=sample_update)
            if not permission['allowed']:
                raise DomainError(permission['reason'], permission['message'], 409)
            from .insight_views import read_knowledge_context
            context = read_knowledge_context(self.app, c, tid, did, request['expected_delivery_revision'])[0]['context']
        identity = input_identity(scope, context, analysis.INPUT_PROTOCOL)
        with self.repo.transaction() as c:
            operation = c.execute('SELECT request_hash,run_id FROM material_analysis_operations WHERE task_id=? AND operation_id=?',
                                  (tid, request['operation_id'])).fetchone()
            if operation:
                if operation['request_hash'] != request_hash:
                    raise DomainError('OPERATION_CONFLICT', '同一操作标识对应不同请求', 409)
                return self._status(c, tid, operation['run_id'])
            old = c.execute('SELECT run_id,status,payload FROM material_analysis_runs WHERE task_id=? AND input_hash=? ORDER BY created_at DESC LIMIT 1',
                            (tid, identity)).fetchone()
            if old and (old['status'] in ACTIVE or old['status'] == 'complete' and self._model_complete(c, tid, old)):
                rid = old['run_id']
            else:
                rid = str(uuid4())
                previous = loads(old['payload']) if old else {}
                state = {'scope': scope, 'context': context, 'spec_ref': loads(task['query_ref']),
                    'input_hash': identity, 'input_protocol': analysis.INPUT_PROTOCOL, 'checkpoints': previous.get('checkpoints', {}),
                    'synthesis_checkpoint': previous.get('synthesis_checkpoint'),
                    'reports': [], 'stage': 'queued', 'completed_records': 0,
                    'retry_of': old['run_id'] if old else None, 'reason': None}
                if sample_update:
                    state['created_by'] = 'explicit-sample-maintainer/1'
                now = utcnow()
                c.execute('INSERT INTO material_analysis_runs VALUES(?,?,?,?,?,?,?,?)',
                    (rid, tid, key, identity, 'queued', canonical(state), now, now))
            c.execute('INSERT INTO material_analysis_operations VALUES(?,?,?,?)',
                (tid, request['operation_id'], request_hash, rid))
            return self._status(c, tid, rid)

    def _status(self, c, tid, rid):
        row = c.execute('SELECT * FROM material_analysis_runs WHERE run_id=? AND task_id=?', (rid, tid)).fetchone()
        if not row:
            raise DomainError('MATERIAL_ANALYSIS_NOT_FOUND', '未找到该补充运行', 404)
        state = loads(row['payload'])
        return {'run_id': rid, 'status': row['status'], 'scope': state['scope'],
            'stage': state.get('stage'), 'reason': state.get('reason'), 'message': state.get('message'),
            'completed_records': state.get('completed_records', 0), 'total_records': state.get('total_records'),
            'created_at': row['created_at'], 'updated_at': row['updated_at'], 'reports': state.get('reports', [])}

    def status(self, tid, rid, *, at_seq=None, sealed_only=False):
        with self.repo.read() as c:
            source = self.app.history.source(c, tid)
            result = self._status(c, source, rid)
            scope = result['scope']
            boundary = self.app.delivery.display_scope(c, tid, scope['delivery_id'], scope['delivery_revision'],
                at_seq=at_seq, sealed_only=sealed_only)['summary_before']
            if boundary is not None and result['updated_at'] > boundary:
                raise DomainError('MATERIAL_ANALYSIS_NOT_FOUND', '此时点没有该补充运行状态', 404)
            return result

    def resolve_followup(self, c, tid, delivery, reference):
        if (not isinstance(reference, dict) or set(reference) != {'id', 'version', 'content_sha256'}
                or type(reference['version']) is not int or reference['version'] < 1):
            raise DomainError('MATERIAL_ANALYSIS_REFERENCE', '补充报告引用不完整', 422)
        report = self.repo.object(c, tid, 'material_analysis', reference['id'], reference['version'])
        scope = report.get('scope') or {}
        if (report.get('schema_version') != analysis.SCHEMA or content_hash(report) != reference['content_sha256']
                or scope.get('task_id') != tid or scope.get('delivery_id') != delivery['delivery_id']
                or scope.get('delivery_revision') != delivery['revision']
                or report.get('snapshot_ref') != delivery['snapshot_ref']):
            raise DomainError('MATERIAL_ANALYSIS_REFERENCE', '补充报告不属于本次交付或引用已变化', 409)
        context = report.get('knowledge_context')
        from astroquery_ai.science.task_knowledge import blocks
        blocks(context)
        if not context or context.get('content_sha256') != report.get('knowledge_context_sha256'):
            raise DomainError('TASK_KNOWLEDGE_HASH', '补充解读的知识快照不可核验', 409)
        return report

    def _update(self, c, rid, state, status):
        c.execute('UPDATE material_analysis_runs SET payload=?,status=?,updated_at=? WHERE run_id=?',
                  (canonical(state), status, utcnow(), rid))

    def stop(self, tid, rid):
        with self.repo.transaction() as c:
            current = self._status(c, tid, rid)
            if current['status'] in ACTIVE:
                state = loads(c.execute('SELECT payload FROM material_analysis_runs WHERE run_id=?', (rid,)).fetchone()[0])
                state.update(stage='cancelled', reason='user_stopped')
                self._update(c, rid, state, 'cancelled')
        if rid in self._active:
            self._active[rid].cancel()
        return self.status(tid, rid)

    def recover(self):
        with self.repo.transaction() as c:
            for row in c.execute("SELECT run_id,payload FROM material_analysis_runs WHERE status='running'").fetchall():
                state = loads(row['payload'])
                state.update(stage='interrupted', reason='process_interrupted', message='运行中断，已保存的批次可复用；请明确重试。')
                self._update(c, row['run_id'], state, 'interrupted')

    def _check(self, c, rid):
        row = c.execute('SELECT * FROM material_analysis_runs WHERE run_id=?', (rid,)).fetchone()
        if not row or row['status'] != 'running':
            raise DomainError('MATERIAL_ANALYSIS_STOPPED', '补充解读已停止', 409)
        task = self.repo.task(c, row['task_id'])
        checked_state(row)
        if c.execute('SELECT 1 FROM task_tombstones WHERE task_id=?', (row['task_id'],)).fetchone():
            raise DomainError('TASK_DELETED', '任务已删除', 409)
        return task

    async def execute(self, rid):
        with self.repo.transaction() as c:
            row = c.execute('SELECT * FROM material_analysis_runs WHERE run_id=?', (rid,)).fetchone()
            if not row or row['status'] != 'queued':
                return
            tid, state = row['task_id'], loads(row['payload'])
            self._update(c, rid, state, 'running')
        scope = state['scope']
        try:
            from astroquery_ai.science import property_insight_generation as generator
            with self.repo.read() as c:
                self._check(c, rid)
                body = self.app.delivery.read_snapshot(c, scope['source_task_id'], scope['delivery_id'], scope['delivery_revision'])
                meta = c.execute("SELECT content_sha256 FROM objects WHERE task_id=? AND kind='delivery' AND object_id=? AND version=?",
                    (scope['source_task_id'], scope['delivery_id'], scope['delivery_revision'])).fetchone()
                if meta[0] != scope['delivery_sha256'] or content_hash(body) != meta[0] or body['snapshot_ref'] != scope['snapshot_ref']:
                    raise DomainError('MATERIAL_ANALYSIS_HASH', '交付输入已变化', 409)
                ref = state['spec_ref']
                spec = self.repo.object(c, tid, 'confirmed_query', ref['id'], ref['version'])
                if content_hash(spec) != ref['content_sha256'] or spec.get('spec_hash') != digest({k: v for k, v in spec.items() if k != 'spec_hash'}):
                    raise DomainError('FROZEN_SPEC_CORRUPT', '冻结规格引用已变化', 409)
            current, _ = analysis.scope_unit(body, spec, state['context'], scope['material_id'], scope['property_id'], scope['kind'])
            if not current['measurements']:
                raise DomainError('MATERIAL_ANALYSIS_NO_RECORDS', '此范围未保存可供分析的测量', 409)
            groups, synthesis = generator.plan(current, body, spec)
            state['total_records'] = len(current['measurements'])
            results = []
            state['active_checkpoint_keys'] = []
            for ordinal, group in enumerate(groups):
                key = digest([group['input'], analysis.SCHEMA, scope['kind']])
                saved = state['checkpoints'].get(key)
                if saved and saved.get('status') == 'generated':
                    results.append(saved)
                    state['active_checkpoint_keys'].append(key)
                    continue
                if synthesis:
                    with self.repo.read() as c:
                        reused = self._saved_material_readings(c, tid, state, {row['measurement_id'] for row in group['unit']['measurements']})
                    if reused:
                        for result in reused:
                            ref_key = 'saved-material-' + digest(result['reused_report_ref'])
                            state['checkpoints'][ref_key] = result
                            state['active_checkpoint_keys'].append(ref_key)
                        results.extend(reused)
                        continue
                state.update(stage=f'batch:{ordinal+1}/{len(groups)}')
                with self.repo.transaction() as c:
                    self._check(c, rid)
                    self._update(c, rid, state, 'running')
                result = await self._explain(rid, tid, body, spec, group['unit'], group['input'], group['bindings'], state, key)
                state['checkpoints'][key] = result
                state['active_checkpoint_keys'].append(key)
                state['completed_records'] = len({mid for item in state['checkpoints'].values() if item.get('status') == 'generated' for mid in item['measurement_ids']})
                with self.repo.transaction() as c:
                    self._check(c, rid)
                    self._update(c, rid, state, 'running')
                results.append(result)
            if synthesis and all(item['status'] == 'generated' for item in results):
                packed, bindings = generator.synthesis_input(current, body, spec,
                    [item['card'] for item in results], [{'measurement_ids': item['measurement_ids'], 'status': item['status']} for item in results])
                signature = digest(packed)
                checkpoint = state.get('synthesis_checkpoint') or {}
                merged = checkpoint.get('result')
                if checkpoint.get('input_sha256') != signature or not merged or merged.get('status') != 'generated':
                    merged = await self._explain(rid, tid, body, spec, current, packed, bindings, state, 'synthesis')
                    state['synthesis_checkpoint'] = {'input_sha256': signature, 'result': merged}
                    with self.repo.transaction() as c:
                        self._check(c, rid)
                        self._update(c, rid, state, 'running')
                results = [merged] if merged['status'] == 'generated' else [*results, merged]
            await self._publish(rid, tid, state, current, results)
        except asyncio.CancelledError:
            with self.repo.transaction() as c:
                row = c.execute('SELECT status FROM material_analysis_runs WHERE run_id=?', (rid,)).fetchone()
                if row and row[0] == 'running':
                    state.update(stage='interrupted', reason='process_interrupted')
                    self._update(c, rid, state, 'interrupted')
            raise
        except Exception as exc:
            with self.repo.transaction() as c:
                row = c.execute('SELECT status FROM material_analysis_runs WHERE run_id=?', (rid,)).fetchone()
                if row and row[0] == 'running':
                    state.update(stage='failed', reason=getattr(exc, 'code', 'MATERIAL_ANALYSIS_FAILED'),
                                 message=exc.message if isinstance(exc, DomainError) else '补充解读未完成，已保存批次保留。')
                    self._update(c, rid, state, 'failed')

    async def _explain(self, rid, tid, body, spec, current, packed, bindings, state, key):
        from astroquery_ai.runtime.calls import input_upper_bound
        packed = analysis.supplement_input(packed, state['scope']['kind'])
        messages = [{'role': 'user', 'content': canonical(packed).decode()}]
        bound = input_upper_bound(messages)
        projection = 'full-originals/1'
        if key == 'synthesis' and bound > cards.INPUT_LIMIT:
            packed = analysis.synthesis_reading_input(packed)
            messages = [{'role': 'user', 'content': canonical(packed).decode()}]
            bound = input_upper_bound(messages)
            projection = 'verified-batch-synthesis/1'
        if bound > cards.INPUT_LIMIT:
            return {'status': 'failed', 'reason': 'INSIGHT_INPUT_CAPACITY', 'measurement_ids': [r['measurement_id'] for r in current['measurements']]}
        self.app.profile_authority.authorize(tid, 'M11', self.profile(), bound)
        last, receipt, response = None, None, None
        for turn in range(2):
            root = 'material-analysis-call-' + digest([rid, key, turn])
            with self.repo.transaction() as c:
                task = self._check(c, rid)
                permit = {'run_id': rid, 'generation': task['generation'], 'input_hash': state['input_hash'],
                    'messages_hash': digest(messages), 'model_version': analysis.MODEL_VERSION}
                if not c.execute("SELECT 1 FROM objects WHERE task_id=? AND kind='material_analysis_permit' AND object_id=?", (tid, root)).fetchone():
                    self.repo.put_object(c, tid, 'material_analysis_permit', root, 1, permit)
            try:
                response, receipt = await self.app.models.json(task_id=tid, owner='M11', root_id=root,
                    messages=messages, profile=self.profile(), purpose='production', root_limit=1,
                    dispatch_guard=lambda c, attempt: self._check(c, rid))
                last = analysis.validate_supplement(response, current, bindings)
                if analysis.usable(last) or not last['validation_issues'] or turn:
                    break
                # One bounded local repair, using only the necessary rejected
                # slots and their existing original materials.
                repairable = {**last, 'validation_issues': [issue for issue in last['validation_issues'] if issue.get('section') in cards.SECTIONS]}
                if not repairable['validation_issues']:
                    break
                local, slots = cards.repair_input(response, repairable, current, body, spec, bindings)
                if not slots:
                    break
                local_messages = [{'role': 'user', 'content': canonical(local).decode()}]
                if input_upper_bound(local_messages) > cards.INPUT_LIMIT:
                    break
                with self.repo.transaction() as c:
                    task = self._check(c, rid)
                    self.repo.put_object(c, tid, 'material_analysis_permit', root+'-local', 1,
                        {'run_id': rid, 'generation': task['generation'], 'input_hash': state['input_hash'],
                         'messages_hash': digest(local_messages), 'model_version': analysis.MODEL_VERSION})
                fixed, repair_receipt = await self.app.models.json(task_id=tid, owner='M11', root_id=root+'-local',
                    messages=local_messages, profile=self.profile(), purpose='production', root_limit=1,
                    dispatch_guard=lambda c, attempt: self._check(c, rid))
                updated, _ = cards.apply_repairs(response, fixed, slots, current, bindings)
                last = analysis.validate_supplement(updated, current, bindings)
                receipt = {**receipt, 'repair_attempt_id': repair_receipt['attempt_id']}
                break
            except DomainError as exc:
                # A paid response may contain complete useful fields despite a
                # broken/truncated JSON tail. Reuse only persisted complete text.
                with self.repo.read() as c:
                    attempt = c.execute('SELECT attempt_id,receipt FROM attempts WHERE task_id=? AND root_id=? ORDER BY created_at DESC LIMIT 1', (tid, root)).fetchone()
                    diagnostic = c.execute("SELECT payload FROM objects WHERE task_id=? AND kind='model_response_diagnostic' AND object_id=?", (tid, attempt['attempt_id'])).fetchone() if attempt else None
                if diagnostic:
                    recovered = analysis.recover_json_fields(loads(diagnostic[0])['raw_response'])
                    try:
                        last = analysis.validate_supplement(recovered, current, bindings)
                        last['warnings'].append({'section': 'response', 'code': exc.code, 'severity': 'warning', 'recovery': 'complete_saved_json_fields'})
                        response = recovered
                        receipt = {**(loads(attempt['receipt']) if attempt['receipt'] else {}), 'attempt_id': attempt['attempt_id']}
                    except DomainError:
                        last = None
                if not analysis.usable(last):
                    return {'status': 'failed', 'reason': exc.code, 'measurement_ids': [r['measurement_id'] for r in current['measurements']], 'raw_response': response}
                break
        return {'status': 'generated' if analysis.usable(last) else 'partial',
                'measurement_ids': [r['measurement_id'] for r in current['measurements']], 'card': last, 'receipt': receipt, 'raw_response': response,
                'input_projection': projection}

    async def _publish(self, rid, tid, state, current, results):
        valid = [r for r in results if r.get('card')]
        complete = bool(valid) and all(r['status'] == 'generated' for r in results)
        report = {'schema_version': analysis.SCHEMA, 'run_id': rid, 'scope': state['scope'],
            'input_protocol': state.get('input_protocol', 'material-reading-input/1'),
            'validation_policy': analysis.VALIDATION_POLICY,
            'snapshot_ref': state['scope']['snapshot_ref'], 'knowledge_context': state['context'],
            'knowledge_context_sha256': state['context']['content_sha256'], 'input_hash': state['input_hash'],
            'generated_at': utcnow(), 'status': 'complete' if complete else 'partial' if any(r['card']['sections']['found'] for r in valid) else 'failed',
            'sections': {section: [p for result in valid for p in result['card']['sections'][section]] for section in cards.SECTIONS},
            'recommendations': {'benchmark': next((r['card']['recommendations'].get('benchmark') for r in valid if r['card']['recommendations'].get('benchmark')), None),
                **{field: [p for result in valid for p in result['card']['recommendations'].get(field, [])] for field in ('data_cleaning', 'application_guidance')}},
            'knowledge_blocks': deepcopy(current['claims']),
            'coverage': {'requested_ids': [r['measurement_id'] for r in current['measurements']],
                         'completed_ids': sorted({mid for result in results if result['status'] == 'generated' for mid in result['measurement_ids']})},
            'receipts': [r['receipt'] for r in results if r.get('receipt')],
            'issues': [issue for r in valid for issue in r['card']['validation_issues']],
            'warnings': [issue for r in valid for issue in r['card'].get('warnings', r['card']['validation_issues'])],
            'unverified_advice': [note for r in valid for note in r['card'].get('unverified_advice', [])],
            'failure_reasons': [r['reason'] for r in results if r.get('reason')]}
        if state['scope']['kind'] == 'property_comparison' and not complete:
            report['saved_batch_analyses'] = [
                {'batch_index': index + 1, 'record_count': len(result['measurement_ids']),
                 'sections': deepcopy(result['card']['sections'])}
                for index, result in enumerate(valid)]
            report['sections'] = {section: [] for section in cards.SECTIONS}
            report['notice'] = '分批内容分别保留，尚未形成全任务综合；批内来源编号和结论不代表全库范围。'
        if any(result.get('input_projection') == 'verified-batch-synthesis/1' for result in results):
            report['reading_basis'] = 'verified-batch-synthesis/1'
            selected = [state['checkpoints'][key] for key in state.get('active_checkpoint_keys', state['checkpoints'])]
            report['batch_coverage'] = [{'measurement_ids': result['measurement_ids'], 'status': result['status']}
                                      for result in selected]
            report['reused_material_reports'] = [result['reused_report_ref'] for result in selected if result.get('reused_report_ref')]
            receipts = [*report['receipts'], *[result['receipt'] for result in selected if result.get('receipt')],
                        *[receipt for result in selected for receipt in result.get('reused_receipts', [])]]
            report['receipts'] = list({receipt.get('attempt_id') or digest(receipt): receipt for receipt in receipts}.values())
        with self.repo.transaction() as c:
            self._check(c, rid)
            response_refs = []
            for result in results:
                if result.get('raw_response') is None:
                    continue
                response_id = 'material-analysis-response-' + digest([rid, result.get('measurement_ids'), (result.get('receipt') or {}).get('attempt_id')])
                existing = c.execute("SELECT content_sha256 FROM objects WHERE task_id=? AND kind='material_analysis_response' AND object_id=? AND version=1", (tid, response_id)).fetchone()
                if existing:
                    response_refs.append({'id': response_id, 'version': 1, 'content_sha256': existing[0]})
                else:
                    response_refs.append(self.repo.put_object(c, tid, 'material_analysis_response', response_id, 1,
                        {'input_hash': state['input_hash'], 'response': result['raw_response'], 'receipt': result.get('receipt')}))
            report['model_response_refs'] = response_refs
            report_id = 'material-analysis-' + digest(scope_content(state['scope']))
            version = c.execute("SELECT coalesce(max(version),0)+1 FROM objects WHERE task_id=? AND kind='material_analysis' AND object_id=?", (tid, report_id)).fetchone()[0]
            ref = self.repo.put_object(c, tid, 'material_analysis', report_id, version, report)
            ref.update(generated_at=report['generated_at'], status=report['status'])
            state['reports'].append(ref)
            state.update(stage='finished', reason=None, completed_records=len(report['coverage']['completed_ids']))
            self._update(c, rid, state, report['status'])

    async def start(self):
        if self._worker:
            return
        self.recover()
        self._closing = False
        async def worker():
            from astroquery_ai.runtime.stages import EXECUTION_POLICY
            limit = EXECUTION_POLICY['insight_units']
            while not self._closing:
                with self.repo.read() as c:
                    queued = [row[0] for row in c.execute("SELECT run_id FROM material_analysis_runs WHERE status='queued' ORDER BY created_at LIMIT ?", (limit,))]
                for rid in queued:
                    if rid not in self._active and len(self._active) < limit:
                        task = asyncio.create_task(self.execute(rid))
                        self._active[rid] = task
                        task.add_done_callback(lambda task, own=rid: self._active.pop(own, None))
                await asyncio.sleep(.5)
        self._worker = asyncio.create_task(worker())

    async def close(self):
        self._closing = True
        if self._worker:
            self._worker.cancel()
        pending = [*self._active.values(), *([self._worker] if self._worker else [])]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self._worker = None
