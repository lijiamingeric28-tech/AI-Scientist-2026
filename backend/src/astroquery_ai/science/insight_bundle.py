"""Two independent report layers over one immutable task knowledge context.

Children checkpoint without publishing. The parent alone crosses the delivery
publication barrier after both terminal component reports have been saved.
"""
from copy import deepcopy
from astroquery_ai.runtime.codec import canonical, digest, loads
from astroquery_ai.runtime.errors import DomainError
from . import material_summaries, property_insight_generation, property_insights, task_knowledge
from .insight_recheck import STOP

MODE = 'research-workbench/2'
SCHEMA = 'InsightBundle/1'
STOP_CODES = STOP | material_summaries.STOP | {'DELIVERY_CHANGED', 'INSIGHT_SNAPSHOT_CHANGED', 'INSIGHT_PLAN_CHANGED'}


def enabled(spec):
    return spec.get('run_policy', {}).get('insights', {}).get('presentation') == MODE


def _check_child(delivery, spec, name, report):
    schema = {'material': 'MaterialSummaryReport/1', 'property': 'InsightReport/4'}[name]
    if report.get('schema_version') != schema:
        raise DomainError('INSIGHT_PUBLICATION_MODE', '洞察子报告格式不匹配')
    if report.get('snapshot_ref') != delivery['snapshot_ref'] or report.get('delivery_id') != delivery['delivery_id']:
        raise DomainError('INSIGHT_SNAPSHOT_CHANGED', '洞察子报告不属于本次科学快照')
    if canonical(report.get('knowledge_context_ref')) != canonical(spec.get('knowledge_context_ref')):
        raise DomainError('TASK_KNOWLEDGE_HASH', '洞察子报告的知识引用与确认任务不一致')


def compose(delivery, spec, material, prop):
    _check_child(delivery, spec, 'material', material)
    _check_child(delivery, spec, 'property', prop)
    components = {name: {'status': report['status'], 'reason': report.get('reason'),
                        'report_id': report['report_id']}
                  for name, report in (('material', material), ('property', prop))}
    states = {c['status'] for c in components.values()}
    status = 'pending' if 'pending' in states else 'complete' if states <= {'generated', 'complete', 'not_applicable'} else 'partial'
    return {'schema_version': SCHEMA, 'presentation': MODE,
            'report_id': 'insight-bundle-' + delivery['delivery_id'],
            'delivery_id': delivery['delivery_id'], 'snapshot_ref': deepcopy(delivery['snapshot_ref']),
            'generation_delivery_revision': delivery['revision'],
            'delivery_revision': delivery['revision'] + (status != 'pending'), 'status': status,
            'knowledge_context_ref': deepcopy(spec.get('knowledge_context_ref')),
            'material_report': deepcopy(material), 'property_report': deepcopy(prop),
            'components': components, 'complete_data_preserved': True,
            'qualified_property_ids': deepcopy(prop.get('qualified_property_ids', []))}


def pending_report(delivery, spec):
    material = material_summaries.report(delivery, state='pending')
    prop = property_insights.pending_report(delivery, spec.get('knowledge_release'))
    for report in (material, prop):report['knowledge_context_ref'] = deepcopy(spec.get('knowledge_context_ref'))
    return compose(delivery, spec, material, prop)


def _key(delivery, spec, name):
    return 'bundle-component-' + digest([delivery['delivery_id'], delivery['revision'],
        delivery['snapshot_ref'], spec.get('knowledge_context_ref'), name])


def save_component(repo, conn, tid, delivery, spec, name, report):
    _check_child(delivery, spec, name, report)
    key = _key(delivery, spec, name)
    body = {'component_id': key, 'component': name, 'delivery_id': delivery['delivery_id'],
            'delivery_revision': delivery['revision'], 'snapshot_ref': deepcopy(delivery['snapshot_ref']),
            'knowledge_context_ref': deepcopy(spec.get('knowledge_context_ref')), 'report': deepcopy(report)}
    repo.put_object(conn, tid, 'insight_bundle_component', key, 1, body)
    return body


def _saved_components(repo, conn, tid, delivery, spec):
    """Validate all relevant persisted scopes before dispatch or reconstruction."""
    keys = {_key(delivery, spec, name): name for name in ('material', 'property')}
    saved = {}
    for component in repo.objects(conn, tid, 'insight_bundle_component'):
        key = component.get('component_id')
        if key not in keys:
            continue  # Another immutable snapshot/context scope is not reusable.
        name = keys[key]
        if canonical(component.get('knowledge_context_ref')) != canonical(spec.get('knowledge_context_ref')):
            raise DomainError('TASK_KNOWLEDGE_HASH', '恢复组件的知识引用与确认任务不一致')
        scope = {k: component.get(k) for k in ('component', 'delivery_id', 'delivery_revision', 'snapshot_ref')}
        expected = {'component': name, 'delivery_id': delivery['delivery_id'],
                    'delivery_revision': delivery['revision'], 'snapshot_ref': delivery['snapshot_ref']}
        if canonical(scope) != canonical(expected):
            raise DomainError('INSIGHT_COMPONENT_SCOPE', '恢复组件不属于本次交付修订')
        _check_child(delivery, spec, name, component['report'])
        saved[key] = component
    return saved


def _guard(service, conn, job, delivery):
    service.repo.validate_lease(conn, job, scientific=False)
    task = service.repo.task(conn, job['task_id'])
    if task['lifecycle'] not in {'running', 'queued'}:
        raise DomainError('DISPATCH_FORBIDDEN', '洞察已停止，保留检查点等待恢复')
    ref = loads(task['delivery_ref'])
    if ref['id'] != delivery['delivery_id'] or ref['version'] != delivery['revision']:
        raise DomainError('DELIVERY_CHANGED', '洞察所属交付修订已变化', 409)


def unfinished_report(repo, conn, tid, delivery, spec, reason):
    saved = _saved_components(repo, conn, tid, delivery, spec)
    try:
        context = task_knowledge.load(repo, conn, tid, spec)
    except DomainError:
        context = None
    material = saved.get(_key(delivery, spec, 'material'), {}).get('report')
    prop = saved.get(_key(delivery, spec, 'property'), {}).get('report')
    if material is None:
        # Retain already checkpointed summaries without reading the current KB.
        from astroquery_ai.application.material_workbench import MaterialIndex
        counts = material_summaries.report_counts(repo, conn, tid, delivery, MaterialIndex(delivery))
        material = material_summaries.report(delivery, state='partial', counts=dict(counts), reason=reason)
        material['knowledge_context_ref'] = deepcopy(spec.get('knowledge_context_ref'))
    if prop is None:
        prop = property_insight_generation.unfinished_report(repo, conn, tid, delivery, spec, reason,
                                                             knowledge_context=context)
        prop['knowledge_context_ref'] = deepcopy(spec.get('knowledge_context_ref'))
    return compose(delivery, spec, material, prop)


async def generate(service, job, spec):
    repo, tid = service.repo, job['task_id']
    with repo.read() as conn:
        delivery = service.app.delivery.get(conn, tid, job['payload']['delivery_id'])
        if delivery.get('report_state') == 'final':
            report = delivery.get('insight_report', {})
            if report.get('schema_version') == SCHEMA:return report
            raise DomainError('INSIGHT_ALREADY_FINAL', '已发布报告不能覆盖')
        _guard(service, conn, job, delivery)
        saved = _saved_components(repo, conn, tid, delivery, spec)
        try:
            context = task_knowledge.load(repo, conn, tid, spec)
            if context is None:raise DomainError('TASK_KNOWLEDGE_MISSING', '任务知识快照缺失')
            context_error = None
        except DomainError as exc:
            context, context_error = None, exc.code
    reports = {}
    # Sequential scheduling shares existing M11 budgets and concurrency limits.
    # A completed child can always be reused independently after interruption.
    for name in ('material', 'property'):
        with repo.read() as conn:_guard(service, conn, job, delivery)
        cached = saved.get(_key(delivery, spec, name))
        if cached:
            reports[name] = cached['report'];continue
        try:
            if context_error:raise DomainError(context_error, '任务知识快照不可读')
            if name == 'material':
                report = await material_summaries.generate(service, job, spec, publish=False, knowledge_context=context)
            else:
                report = await property_insight_generation.generate(service, job, publish=False, knowledge_context=context)
        except (DomainError, OSError) as exc:
            reason = exc.code if isinstance(exc, DomainError) else "COMPONENT_IO_ERROR"
            if reason in STOP_CODES:raise
            with repo.read() as conn:
                partial = unfinished_report(repo, conn, tid, delivery, spec, reason)
            report = partial[name + '_report']
        with repo.transaction() as conn:
            _guard(service, conn, job, delivery)
            save_component(repo, conn, tid, delivery, spec, name, report)
        reports[name] = report
    result = compose(delivery, spec, reports['material'], reports['property'])
    with repo.transaction() as conn:
        _guard(service, conn, job, delivery)
        repo.finish_job(conn, job)
        service.app.delivery.finish_insights(conn, tid, result)
    return result
