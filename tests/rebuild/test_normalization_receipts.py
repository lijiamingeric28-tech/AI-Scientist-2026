from copy import deepcopy
from decimal import Decimal

import pytest

from astroquery_ai.runtime.codec import content_hash, canonical
from astroquery_ai.runtime.representations import commit_current_representation
from astroquery_ai.runtime.errors import DomainError
from tests.rebuild.factories import error_component, measurement
from tests.rebuild.test_normalization_failure_authority import case
from astroquery_ai.science.normalization import SameQuantityTransform, normalize_checked
from astroquery_ai.runtime.models import SourceMeasurement
from astroquery_ai.registry.models import Representation


def test_commit_logs_actual_separate_error_changes_once_and_rollback_is_atomic(tmp_path):
    app, tid, _, binding = case(tmp_path)
    source = measurement(components=[error_component(), error_component('SYNTHETIC sys', role='sys', values={'delta': '0.4'})])
    source['task_id'] = tid
    source['revision'] = 2
    source['content_sha256'] = content_hash(source)
    output = binding['output_profile']
    output.update(unit={'canonical_symbol': 'cm'}, representation={'kind': 'linear'})
    profile = {'id': output['profile_id'], 'version': 1, 'content_sha256': output['content_sha256']}
    result = normalize_checked(SourceMeasurement.model_validate(source),
        SameQuantityTransform(Representation(kind='linear'), Representation(kind='linear'), 'm', 'cm',
            source_quantity_key='SYNTHETIC length', target_quantity_key='SYNTHETIC length'), profile,
        target_unit_ref=profile, target_representation_ref=profile)
    before = deepcopy(source)
    with app.repository.transaction() as conn:
        query_ref = app.repository.put_object(conn, tid, 'confirmed_query', 'SYNTHETIC query', 2,
            {'properties': [binding], 'dependencies': [], 'registry_release': {'id': 'SYNTHETIC registry'}})
        app.repository.mutate_task(conn, tid, query_ref=canonical(query_ref).decode())
        app.repository.put_object(conn, tid, 'measurement', source['measurement_id'], 2, source)
    with pytest.raises(RuntimeError):
        with app.repository.transaction() as conn:
            commit_current_representation(app.repository, conn, tid, source, result)
            raise RuntimeError('SYNTHETIC interrupted transaction')
    with app.repository.read() as conn:
        assert not app.repository.objects(conn, tid, 'processing_receipt')
        assert not app.repository.objects(conn, tid, 'derived')
    with app.repository.transaction() as conn:
        commit_current_representation(app.repository, conn, tid, source, result)
        commit_current_representation(app.repository, conn, tid, source, result)
    with app.repository.read() as conn:
        receipts = app.repository.objects(conn, tid, 'processing_receipt')
        events = app.repository.objects(conn, tid, 'change_event')
        assert len(receipts) == len(events) == 1
        assert receipts[0]['postcheck'] == 'passed'
        assert [Decimal(c['output_component']['values']['delta']) for c in receipts[0]['per_component']] == [Decimal('10'), Decimal('40')]
        assert {d['path'] for d in events[0]['field_diff']} >= {
            '/value/value', '/components/synthetic-stat/values/delta', '/components/SYNTHETIC sys/values/delta'}
        assert events[0]['source_replaced'] is False
        assert app.repository.object(conn, tid, 'measurement', source['measurement_id']) == before
        assert receipts[0]['actual_attempt_refs'] == []


def test_source_change_refuses_both_result_and_processing_receipt(tmp_path):
    app, tid, source, binding = case(tmp_path)
    changed = deepcopy(source)
    changed['revision'] += 1
    changed['value']['value'] = '3'
    changed['content_sha256'] = content_hash(changed)
    with app.repository.transaction() as conn:
        app.repository.put_object(conn, tid, 'measurement', source['measurement_id'], 2, changed)
    with pytest.raises(DomainError, match='更新后的来源解释'):
        with app.repository.transaction() as conn:
            commit_current_representation(app.repository, conn, tid, source, {
                'source_representation_hash': source['content_sha256']})
    with app.repository.read() as conn:
        assert not app.repository.objects(conn, tid, 'processing_receipt')
        assert not app.repository.objects(conn, tid, 'change_event')
