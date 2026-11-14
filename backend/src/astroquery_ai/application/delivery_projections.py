"""Pinned display projections, sharing exact definitions, contexts and evidence."""
from collections import defaultdict
from copy import deepcopy

from astroquery_ai.application.material_workbench import MaterialIndex, material_overview
from astroquery_ai.application import research_views, result_views
from astroquery_ai.runtime.errors import DomainError


class ProjectionUnavailable(Exception):
    """A historical per-resource body lacks the full-index sections.

    Keep the already decoded body for the caller's original projection. This
    is an applicability result, never a catch-all for malformed saved content.
    """
    def __init__(self, body):
        super().__init__('snapshot does not contain the full UI index sections')
        self.body = body


def header_projection(body, overview, *, overview_dynamic=False, index=None):
    header = {key: body[key] for key in ('delivery_id', 'revision', 'snapshot_ref', 'status', 'counts',
                                       'insight_report', 'task_score', 'report_state') if key in body}
    header.update(definition_count=len(body.get('definitions', [])),
                  comparison_checked=sum(row.get('state') == 'checked' for row in body.get('comparison_checks', [])),
                  overview_dynamic=overview_dynamic)
    header.update(material_overview=overview, display_counts={
        'records': len(body.get('measurements', [])), 'sources': len(body.get('sources', [])),
        'figures': len(body.get('figures', [])), 'materials': overview['total']})
    if index is not None:
        header['display_counts'].update(material_groups=sum(g['root'].get('kind') != 'cited' for g in index.groups.values()),
                                        citation_groups=sum(g['root'].get('kind') == 'cited' for g in index.groups.values()),
                                        properties=len(index.names))
    return header


def material_state(index):
    groups = {}
    for gid, group in index.groups.items():
        groups[gid] = {**group, 'root': None, 'properties': list(group['properties']),
                       'cited_properties': list(group['cited_properties']),
                       'by_property': list(group['by_property'].items())}
    return {'names': list(index.names.items()), 'works': index.works, 'source_group': index.source_group,
            'attachment_aliases': index.attachment_aliases, 'groups': groups, 'entries': index.entries,
            'records': {mid: {'source_ref': record['source_ref']} for mid, record in index.records.items()}}


def restore_material_index(reader):
    state = reader.get('material_state')
    index = MaterialIndex.__new__(MaterialIndex)
    index.__dict__.update(state)
    index.names = dict(index.names)
    index.materials = {m['material_id']: m for m in reader.rows('material')}
    index.figures = {f['figure_id']: f for f in reader.rows('figure')}
    for gid, group in index.groups.items():
        group['root'] = index.materials[gid]
        group['properties'] = set(group['properties'])
        group['cited_properties'] = set(group['cited_properties'])
        group['by_property'] = defaultdict(lambda: {'records': [], 'figures': []}, group['by_property'])
    return index


def resolve_summary(reader, material_id, property_id):
    """Summary polling reads only small identity/ownership and bibliography rows."""
    resolver = reader.get('material_resolver')
    names = dict(resolver['names'])
    gid = resolver['source_group'].get(material_id) or resolver['works'].get(material_id) or material_id
    group = reader.get('summary_group', gid)
    if group is None:
        raise DomainError('MATERIAL_NOT_FOUND', '当前结果没有此资料', 404)
    if property_id == 'other':
        property_id = None
        if None not in group['properties']:
            raise DomainError('MATERIAL_PROPERTY_NOT_FOUND', '此资料没有该性质的归属', 404)
    elif property_id is None:
        property_id = next((pid for pid in names if pid in group['properties']), None)
    elif property_id not in group['properties']:
        raise DomainError('MATERIAL_PROPERTY_NOT_FOUND', '此资料没有该性质的归属', 404)
    return group, property_id


def _by_members(rows, field):
    result = defaultdict(list)
    for row in rows:
        for mid in dict.fromkeys(field(row)):
            result[mid].append(row)
    return result


def detail_rows(body, report, views, activity):
    """The existing full record contract, indexed once instead of scanning per ID."""
    bundle = body['provenance_bundle']
    outputs = {d['measurement_id']: d for d in body['derived']}
    properties = {b['property_id']: b for b in body['definitions']}
    evidence = {e['evidence_id']: e for e in body['evidence_index']}
    contexts = {c['context_id']: c for c in body['contexts']}
    resolved = {c['context_id']: c for c in body.get('resolved_contexts', [])}
    interpretations = {i['interpretation_id']: i for i in bundle['interpretations']}
    answers = {a['answer_id']: a for a in bundle['human_answers']}
    statements = {s['statement_id']: s for s in bundle.get('source_statements', [])}
    units = {u['unit_id']: u for u in bundle.get('unit_records', [])}
    sources = {s['source_id']: s for s in body['sources']}
    dispositions = result_views.report_dispositions(body)
    projection = report.get('comparison_projection', {'groups': [], 'limitations': []})
    groups = _by_members(projection['groups'], lambda g: g['measurement_ids'])
    limitations = _by_members(projection['limitations'], lambda g: g['measurement_ids'])
    comparisons = _by_members(report.get('result_comparisons', {}).get('groups', []), lambda g: g['measurement_ids'])
    archives = _by_members(body.get('archive_groups', []), lambda g: [r['id'] for r in g['member_refs']])
    activities = _by_members(activity, lambda a: a['measurement_ids'])
    view_map = defaultdict(list)
    for position, view in enumerate(views):
        view_map[view['evidence_id']].append((position, view))
    receipts = {}
    for receipt in bundle.get('processing_receipts', []):
        receipts.setdefault((receipt.get('input_ref') or {}).get('id'), receipt)
    cited = {c['cited_work_id']: c for c in bundle.get('cited_works', [])}
    aliases = {(m.get('original_measurement_ref') or {}).get('id'): m['measurement_id']
               for m in bundle.get('source_mentions', [])}
    citations = _by_members(bundle.get('reported_references', []), lambda r: [aliases.get(r['measurement_id'])])
    refs = {r['reference_id']: r for r in bundle.get('reported_references', [])}
    ref_order = {rid: position for position, rid in enumerate(refs)}
    for record in body['measurements']:
        mid = record['measurement_id']
        context = contexts[record['context_ref']['id']]
        interpretation = interpretations[record['interpretation_ref']['id']]
        ev_ids = {r['id'] for r in record['evidence_refs']}
        # Preserve the saved reference order, including alias-associated citations.
        citation_ids = {r['id'] for r in record.get('lineage_refs', [])}
        citation_ids.update(r['reference_id'] for r in citations[mid])
        source = sources.get(record['source_ref']['id'], {})
        yield mid, {
            'source': record, 'source_title': source.get('title'), 'source_version_grade': source.get('version_grade'),
            'report_checks': result_views.record_dispositions(record, dispositions),
            'record_status': result_views.record_status(record, dispositions),
            'uncertainty_units': {part['component_id']: (units.get((part.get('unit_ref') or {}).get('id'), {}).get('unit_text')
                or units.get((part.get('unit_ref') or {}).get('id'), {}).get('unit_declaration', {}).get('canonical_symbol'))
                for part in record['uncertainty']['components']},
            'workflow_contract': body.get('workflow_contract'), 'archive_groups': archives[mid],
            'derived': outputs.get(mid), 'property_binding': properties[record['property_ref']['id']],
            'target': body['target'], 'interpretation': interpretation,
            'human_answer': answers.get((interpretation.get('human_answer_ref') or {}).get('id')),
            'context': resolved.get(record['context_ref']['id'], context), 'source_context': context,
            'reported_references': [{**refs[rid], 'cited_work': cited.get(refs[rid].get('cited_work_id'))}
                                    for rid in sorted(citation_ids & refs.keys(), key=ref_order.__getitem__)],
            'source_statements': [statements[r['id']] for r in context.get('source_statements', []) if r['id'] in statements],
            'evidence': [evidence[r['id']] for r in record['evidence_refs']],
            'evidence_views': [v for _, v in sorted((pair for eid in ev_ids for pair in view_map[eid]), key=lambda pair: pair[0])],
            'comparison_groups': groups[mid], 'comparison_limitations': limitations[mid],
            'result_comparison_refs': [{k: g[k] for k in ('group_id', 'property_id', 'meaning')} for g in comparisons[mid]],
            '_activity': activities[mid], '_processing_receipt': receipts.get(mid), '_source_metadata': source,
            '_review_answers': [answers[a['id']] for a in activities[mid] if a['kind'] == 'human' and a['id'] in answers],
        }


def build_projections(service, conn, source_task, body, cutoff):
    required = {'definitions', 'measurements', 'sources', 'contexts', 'derived', 'evidence_index', 'provenance_bundle'}
    if not required <= body.keys():
        raise ProjectionUnavailable(body)
    preparation = max(research_views.saved_before(conn, source_task, 'material_preparation', cutoff),
                      key=lambda p: p.get('revision', 0), default={})
    index = MaterialIndex(body, preparation)
    saved_overview = material_overview(body)
    overview = saved_overview if saved_overview is not None else material_overview(body, index)
    header = header_projection(body, overview, overview_dynamic=saved_overview is None, index=index)
    yield 'header', '', header
    yield 'material_state', '', material_state(index)
    from .material_reading import reading_profiles
    for key, profile in reading_profiles(body, index).items():
        yield 'material_profile', key, profile
    yield 'material_resolver', '', {'names': list(index.names.items()), 'works': index.works,
                                    'source_group': index.source_group}
    for gid, group in index.groups.items():
        root = group['root']
        yield 'summary_group', gid, {'group_id': gid, 'properties': list(group['properties']),
            'root': {'title': root.get('title'), 'kind': root.get('kind'), 'abstract': bool(root.get('abstract'))}}
    for mid, material in index.materials.items():
        yield 'material', mid, material
    for source in body['sources']:
        yield 'source', source['source_id'], source
    for figure in body.get('figures', []):
        yield 'figure', figure['figure_id'], figure
    yield 'figure_coverage', '', {'items': body.get('figure_coverage', [])}
    quality_ref = (body.get('quality') or {}).get('report_ref')
    quality = service.repository.object(conn, source_task, 'quality', quality_ref['id'], quality_ref['version']) if quality_ref else None
    reference = (body.get('difference') or {}).get('report_ref')
    report = service.repository.object(conn, source_task, 'difference', reference['id'], reference['version']) if reference else None
    rows = result_views.record_list(body, quality=quality)
    for row in rows:
        yield 'list', row['source']['measurement_id'], row
    for label in result_views.source_list(body):
        yield 'source_list', label['source_id'], label
    for row in result_views.analysis_list(body, quality, report, rows=deepcopy(rows)):
        yield 'analysis', row['source']['measurement_id'], row
    # Minimal historical/list-only fixtures can lack detail metadata; preserve
    # their existing route behavior without making unrelated projections fail.
    contexts = {c['context_id'] for c in body['contexts']}
    interpretations = {i['interpretation_id'] for i in body.get('provenance_bundle', {}).get('interpretations', [])}
    valid_details = report is not None and all((m.get('context_ref') or {}).get('id') in contexts
        and m['interpretation_ref']['id'] in interpretations for m in body['measurements'])
    if valid_details:
        views = body.get('evidence_views')
        if views is None:
            from astroquery_ai.science.evidence_views import build_views
            views = build_views(service.repository, conn, source_task, body['evidence_index'], body['sources'], snapshot=body, cutoff=cutoff)
        activity = research_views.activities(body, report, research_views.review_details(conn, source_task, body))
        for mid, row in detail_rows(body, report, views, activity):
            yield 'detail', mid, row
