"""Provisional evidence cannot become a delivery or a human answer."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.codec import canonical, content_hash
from astroquery_ai.runtime.errors import DomainError
from tests.rebuild.factories import measurement, error_component
from web.runtime_app import create_app


def preview_case(tmp_path):
    app = Application(tmp_path)
    repo = app.repository
    tid = repo.create_task('SYNTHETIC provisional evidence')['task_id']
    with repo.transaction() as conn:
        record = measurement(components=[error_component()])
        record['task_id'] = tid
        evidence = repo.put_object(conn, tid, 'evidence', 'evidence', 1,
            {'evidence_id': 'evidence', 'raw_text': 'SYNTHETIC 2 ± 0.1 m', 'locator': {'page': 2}})
        record['evidence_refs'] = [evidence]
        record['context_ref'] = repo.put_object(conn, tid, 'context', 'context', 1,
            {'context_id': 'context', 'conditions': [], 'source_statements': []})
        record['source_ref'] = repo.put_object(conn, tid, 'source', 'source', 1,
            {'source_id': 'source', 'kind': 'paper', 'title': 'SYNTHETIC manuscript'})
        record['content_sha256'] = content_hash(record)
        repo.put_object(conn, tid, 'measurement', record['measurement_id'], 1, record)
        spec_ref = repo.put_object(conn, tid, 'confirmed_query', 'spec', 1, {
            'target': {'main_id': 'SYNTHETIC object'}, 'properties': [
                {'property_id': record['property_ref']['id'], 'definition': {'name_cn': '合成长度'}}]})
        repo.mutate_task(conn, tid, query_ref=canonical(spec_ref).decode(), lifecycle='waiting_review', science_state='open')
        app.reviews.register(conn, tid, {'origin': 'M06', 'owner': 'M06',
            'issue_kind': 'value_transcription', 'issue_key': 'SYNTHETIC check',
            'question': 'SYNTHETIC source check', 'impact': 'SYNTHETIC admission',
            'scope': {'measurement_ids': [record['measurement_id']]},
            'basis': {'measurement_ref': {'id': record['measurement_id'], 'version': 1,
                                        'content_sha256': record['content_sha256']}},
            'evidence_refs': [evidence]})
    return app, tid, record


def test_pending_preview_preserves_separate_errors_and_does_not_publish_or_answer(tmp_path):
    app, tid, record = preview_case(tmp_path)
    before = app.repository.get_task(tid)
    with TestClient(create_app(tmp_path, start_worker=False, application=app)) as client:
        body = client.get(f'/api/tasks/{tid}/preview').json()
        assert body['status'] == 'provisional_read_only' and body['exportable'] is False
        assert body['final_quality_available'] is False and body['counts']['pending_questions'] == 1
        row = body['items'][0]
        assert row['source'] == record and row['provisional_state'] == 'under_review'
        assert row['source']['uncertainty']['components'][0]['values'] == {'delta': '0.1'}
        assert row['evidence'][0]['locator']['page'] == 2 and row['review_ids']
        assert client.get(f'/api/tasks/{tid}/delivery').status_code != 200
    assert app.repository.get_task(tid) == before
    with app.repository.read() as conn:
        assert not app.repository.objects(conn, tid, 'delivery')
        assert not app.repository.objects(conn, tid, 'quality')
        assert not app.repository.objects(conn, tid, 'human_answer')
        assert conn.execute('SELECT status FROM reviews WHERE task_id=?', (tid,)).fetchone()[0] == 'pending'
    assert app.budget.summary()['committed_micros'] == 0


def test_preview_page_token_changes_when_records_change_without_task_revision_change(tmp_path):
    app, tid, record = preview_case(tmp_path)
    with app.repository.read() as conn:
        initial = app.delivery.preview(conn, tid)
    with app.repository.transaction() as conn:
        revised = deepcopy(record)
        revised['measurement_id'] = 'SYNTHETIC another result'
        revised['content_sha256'] = content_hash(revised)
        app.repository.put_object(conn, tid, 'measurement', revised['measurement_id'], 1, revised)
    with app.repository.read() as conn, pytest.raises(DomainError) as failure:
        app.delivery.preview(conn, tid, offset=1, expected_preview_id=initial['preview_id'])
    assert failure.value.code == 'PREVIEW_CHANGED'


def test_sealed_task_rejects_provisional_preview(tmp_path):
    app, tid, _ = preview_case(tmp_path)
    with app.repository.transaction() as conn:
        app.repository.mutate_task(conn, tid, science_state='sealed')
    with app.repository.read() as conn, pytest.raises(DomainError) as failure:
        app.delivery.preview(conn, tid)
    assert failure.value.code == 'PREVIEW_UNAVAILABLE'
