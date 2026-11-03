"""Resolve carried context interpretations from one immutable delivery snapshot."""
from astroquery_ai.runtime.codec import content_hash
from astroquery_ai.registry.science_conditions import binding_condition_hashes


def checked_context(context, check):
    if check is None:
        return context
    conditions = {c['key']: c for c in context.get('conditions', [])}
    ref = {'id': check['check_id'], 'version': 1, 'content_sha256': check['content_sha256']}
    for key, value in check.get('contexts', {}).items():
        original = conditions.get(key, {})
        if original.get('human_answer_ref'):
            conditions[key] = {**original, 'subsequent_model_context_check': value,
                'interpretation_origin': 'protected_human_context_answer'}
            continue
        conditions[key] = {**original, **value, 'key': key, 'check_ref': ref,
            'source_reported_condition': original, 'interpretation_origin': 'carried_scientific_condition_check'}
    view = {**context, 'conditions': list(conditions.values()), 'scientific_condition_ref': ref,
        'context_resolution': 'raw_context_plus_exact_checked_facts/1'}
    if context.get('content_sha256'):
        view['source_context_ref'] = {'id': context['context_id'], 'version': context['revision'],
            'content_sha256': context['content_sha256']}
        view.pop('content_sha256', None)
    return view


def delivery_contexts(delivery):
    if 'resolved_contexts' in delivery:
        return delivery['resolved_contexts']
    checks = {c['content_sha256']: c for c in delivery.get('provenance_bundle', {}).get('science_condition_checks', [])}
    records = {m['measurement_id']: m for m in delivery['measurements']}
    outputs = {d['measurement_id']: d for d in delivery['derived']}
    bindings = {b['property_id']: b for b in delivery.get('definitions', [])}
    result = []
    for context in delivery['contexts']:
        mid = context['measurement_ref']['id']
        record, output = records.get(mid), outputs.get(mid, {})
        check = checks.get((output.get('scientific_condition_ref') or {}).get('content_sha256'))
        binding = bindings.get(record['property_ref']['id'], {}) if record else {}
        if (check is None or record is None or check['source_hash'] != record['content_sha256']
                or check['science_record_hash'] not in binding_condition_hashes(binding)
                or content_hash(check) != check['content_sha256']):
            check = None
        result.append(checked_context(context, check))
    return result
