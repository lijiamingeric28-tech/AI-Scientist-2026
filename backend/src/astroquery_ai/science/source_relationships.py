"""Property-level result relations. A citation alone never proves one result."""
from astroquery_ai.runtime.codec import content_hash, digest


def relationships(records, mentions, reported_refs, interpretations=()):
    by_id = {m['measurement_id']: m for m in records}
    result = []
    for mention in mentions:
        original = mention.get('original_measurement_ref') or {}
        canonical = by_id.get(mention.get('measurement_id'))
        member = by_id.get(original.get('id'))
        if not canonical or not mention.get('source_recheck_ref') or not mention.get('source_quotes'):
            continue
        if member and (member['property_ref'] != canonical['property_ref'] or member['content_sha256'] != original['content_sha256']):
            continue
        result.append({'property_id': canonical['property_ref']['id'], 'kind': 'same_author_reported_result',
            'measurement_ids': [canonical['measurement_id'], original['id']],
            'source_recheck_ref': mention['source_recheck_ref'], 'evidence_refs': mention.get('evidence_refs', []),
            'independence': 'not_asserted', 'values_or_human_answers_changed': False})
    for reference in reported_refs:
        canonical_id = next((m['measurement_id'] for m in mentions
            if (m.get('original_measurement_ref') or {}).get('id') == reference['measurement_id']), reference['measurement_id'])
        record = by_id.get(canonical_id)
        if not record:
            continue
        result.append({'property_id': record['property_ref']['id'], 'kind': 'source_reported_reference',
            'measurement_ids': [record['measurement_id']], 'raw_code': reference['raw_code'],
            'reference_ref': {'id': reference['reference_id'], 'version': reference.get('revision',1), 'content_sha256': content_hash(reference)},
            'reported_at_measurement_id':reference['measurement_id'],
            'citation_role':reference.get('role','unknown'),'link_quote':reference.get('link_quote'),
            'link_state':reference.get('link_state','unknown'),'cited_work_id':reference.get('cited_work_id'),
            'abstract_use':'background_only_not_measurement_verification',
            'result_identity': 'unknown', 'independence': 'not_asserted',
            'evidence_refs': reference['evidence_refs']})
    by_interpretation = {(i['interpretation_id'], i['revision']): i for i in interpretations}
    for record in records:
        ref = record['interpretation_ref']
        interpretation = by_interpretation.get((ref['id'], ref['version']), {})
        verification = interpretation.get('paper_verification') or {}
        check = verification.get('check') or {}
        if (verification.get('state') != 'passed' or check.get('result_role') != 'adopted_measurement'
                or interpretation.get('proposal', {}).get('result_role') != 'adopted_measurement'):
            continue
        anchors = [a for a in check.get('role_evidence', []) if a.get('quote')]
        if not anchors:
            continue
        result.append({'property_id': record['property_ref']['id'], 'kind': 'source_declared_adoption',
            'measurement_ids': [record['measurement_id']], 'source_ref': record['source_ref'],
            'adoption_evidence': anchors, 'evidence_refs': record['evidence_refs'],
            'reference_refs': [r for r in record.get('lineage_refs', [])],
            'adopted_result_identity': 'unresolved_until_exact_reference_and_result_binding',
            'independence': 'not_an_independent_new_measurement_in_this_document',
            'values_or_human_answers_changed': False})
    for row in result:
        row['relationship_id'] = 'result-relation-' + digest(row)
    return result
