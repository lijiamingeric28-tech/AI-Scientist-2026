"""Service-generated M08 outcomes and diffs, committed with their representation."""
from .codec import digest, loads, utcnow


def field_diff(before, after, path=''):
    if isinstance(before, dict) and isinstance(after, dict):
        return [change for key in sorted(before.keys() | after.keys())
                for change in field_diff(before.get(key), after.get(key), f'{path}/{key}')]
    return [] if before == after else [{'path': path, 'before': before, 'after': after}]


def record_normalization_outcome(repo, conn, task_id, record, output, result, derived_ref, job=None):
    # One receipt per actual commit. Retrying an already committed step must not
    # regenerate timestamps, duplicate a change, or relabel an unknown failure.
    identity = {'source': record['content_sha256'], 'derived': derived_ref,
                'job_id': job['job_id'] if job else None}
    receipt_id = 'normalization-receipt-' + digest(identity)
    if conn.execute("SELECT 1 FROM objects WHERE task_id=? AND kind='processing_receipt' AND object_id=?",
                    (task_id, receipt_id)).fetchone():
        return
    attempts = []
    if job:
        for row in conn.execute('SELECT attempt_id,status,receipt FROM attempts WHERE job_id=? ORDER BY created_at,attempt_id',
                                (job['job_id'],)):
            receipt = loads(row['receipt']) if row['receipt'] else {}
            attempts.append({'attempt_id': row['attempt_id'], 'status': row['status'],
                'receipt_sha256': digest(receipt), 'model': receipt.get('model'),
                'profile': receipt.get('profile'), 'operation': receipt.get('operation')})
    state = result['status']
    postcheck = ('not_checked' if state == 'not_checked' else 'not_run' if state == 'not_run'
                 else 'passed' if state == 'ready' else 'failed')
    revision = repo.task(conn, task_id)['revision']
    timestamp = utcnow()
    source_ref = {'id': record['measurement_id'], 'version': record['revision'],
                  'content_sha256': record['content_sha256']}
    components = (result.get('uncertainty_typed') or {}).get('components', [])
    checks = [{'target': 'main_value', 'status': ('check_failed' if state == 'not_checked'
        else 'not_applicable' if state == 'not_run' else 'passed' if result['main_state'] == 'ready' else 'failed'),
        'validation_ref': result.get('validation_receipt_ref')}]
    checks.extend({'target': 'uncertainty_component', 'component_id': c['source_component_id'],
        'status': 'passed' if c['status'] in {'exact', 'approximate', 'source_preserved'}
                  else 'not_applicable' if c['status'] == 'source_unresolved' else 'failed',
        'validation_ref': c.get('validation_ref'), 'reason': c.get('reason')} for c in components)
    receipt = {'schema_version': 'NormalizationReceipt/1', 'receipt_id': receipt_id, 'owner': 'M08',
        'processing_item_id': 'normalization-' + digest({'source': source_ref, 'output': result['output_profile_ref']}),
        'input_ref': source_ref, 'output_ref': derived_ref, 'status': state,
        'processing_state': 'succeeded' if state == 'ready' else 'not_run' if state == 'not_run' else 'failed',
        'postcheck': postcheck, 'per_measurement': [{'measurement_id': record['measurement_id'],
            'main_state': result['main_state'], 'status': state}], 'per_component': components,
        'checks': checks, 'issues': result.get('issues', []), 'reason': result.get('reason'),
        'transform_ref': result.get('transform_ref'), 'execution_profile_ref': result.get('execution_profile_ref'),
        'output_profile_ref': result['output_profile_ref'], 'method': result.get('method'),
        'interpretation_receipt_ref': result.get('interpretation_receipt_ref'),
        'actual_attempt_refs': attempts, 'committed_revision': revision, 'timestamp': timestamp}
    receipt['model_proposal_checks'] = [check for check in repo.objects(conn, task_id, 'normalization_proposal_check')
        if job and check['job_id'] == job['job_id']]
    receipt_ref = repo.put_object(conn, task_id, 'processing_receipt', receipt_id, 1, receipt)
    # Failed/not-run attempts have an outcome, never a fictitious successful edit.
    if result['main_state'] != 'ready':
        return
    before = {'value': record['value'], 'unit': record['unit'], 'representation': record['representation'],
        'limit': record['limit'], 'components': {c['component_id']: c for c in record['uncertainty']['components']}}
    after = {'value': result['value_typed'], 'unit': output.get('unit', {}).get('canonical_symbol', record['unit']),
        'representation': output.get('representation', {}).get('kind', record['representation']),
        'limit': result['limit'], 'components': {c['source_component_id']: c.get('output_component') for c in components}}
    changes = field_diff(before, after)
    if not changes:
        return
    event_id = 'normalization-change-' + digest(identity)
    repo.put_object(conn, task_id, 'change_event', event_id, 1, {
        'schema_version': 'ChangeEvent/1', 'event_id': event_id, 'owner': 'M08',
        'operation': 'same_quantity_representation', 'measurement_ref': source_ref,
        'before_ref': source_ref, 'after_ref': derived_ref, 'before_representation_hash': digest(before),
        'after_representation_hash': digest(after), 'field_diff': changes, 'generated_by': 'service_diff',
        'method': result.get('method') or 'independently_checked_transform',
        'validation_ref': receipt_ref, 'actual_attempt_refs': attempts,
        'commit_revision': revision, 'timestamp': timestamp,
        'source_replaced': False, 'partial': state == 'partial'})
