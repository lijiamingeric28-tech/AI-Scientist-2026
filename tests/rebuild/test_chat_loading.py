"""Combined reads keep command authority and content-based preview identities."""
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from astroquery_ai.api.http import create_app
from astroquery_ai.application.presentation import presentation
from astroquery_ai.runtime.codec import content_hash
from astroquery_ai.runtime.errors import DomainError
from tests.rebuild.test_provisional_preview import preview_case


@pytest.mark.parametrize('lifecycle', ['clarifying', 'paused', 'waiting_input', 'completed'])
def test_chat_preserves_authority_and_uses_one_snapshot(tmp_path, lifecycle):
    api = create_app(tmp_path, start_worker=False)
    app = api.state.application
    tid = app.create('SYNTHETIC combined conversation', str(uuid4()))['task_id']
    with app.repository.transaction() as conn:
        app.repository.mutate_task(conn, tid, lifecycle=lifecycle)
    original_read = app.repository.read
    reads = []

    @contextmanager
    def counted_read():
        reads.append(1)
        with original_read() as conn:
            yield conn

    app.repository.read = counted_read
    with TestClient(api) as client:
        conversation = app.view(tid, for_conversation=True)
        shown = presentation(app, tid, include_chat_activity=True)
        reads.clear()
        response = client.get(f'/api/tasks/{tid}/state?view=chat')
    assert response.status_code == 200
    result = response.json()
    assert len(reads) == 1
    assert result['presentation'] == shown
    assert result['presentation']['cursor'] == result['core_event_cursor']
    for key in ('pending', 'draft', 'reviews', 'revision', 'lifecycle', 'execution_stage',
                'omission_context_hash', 'review_actor'):
        assert result[key] == conversation[key]
    assert not {'messages', 'stages', 'jobs'} & result.keys()
    assert result['preview_revision'] is None


def test_preview_v2_ignores_logs_but_legacy_token_does_not(tmp_path):
    app, tid, _ = preview_case(tmp_path)
    with app.repository.read() as conn:
        before = app.delivery.preview(conn, tid, preview_protocol=2)
        old = app.delivery.preview(conn, tid)
    with app.repository.transaction() as conn:
        app.repository.event(conn, tid, 'unrelated_log', {'message': 'SYNTHETIC heartbeat'})
    with app.repository.read() as conn:
        after = app.delivery.preview(conn, tid, preview_protocol=2, expected_preview_id=before['preview_id'])
        assert app.delivery.preview(conn, tid)['preview_id'] != old['preview_id']
    assert after['schema_version'] == 'ProvisionalSciencePreview/2'
    assert after['preview_revision'] == before['preview_id']
    assert app.view(tid, for_workspace=True)['preview_revision'] == before['preview_id']


@pytest.mark.parametrize('kind', ['measurement', 'candidate', 'admission_disposition', 'derived',
    'current_representation', 'evidence', 'context', 'source', 'source_statement',
    'document_index', 'evidence_page_preview', 'interpretation'])
def test_preview_v2_hint_invalidates_scientific_dependencies(tmp_path, kind):
    app, tid, _ = preview_case(tmp_path)
    before = app.view(tid, for_workspace=True)['preview_revision']
    with app.repository.transaction() as conn:
        app.repository.put_object(conn, tid, kind, 'SYNTHETIC dependency', 1, {'changed': True})
    assert app.view(tid, for_workspace=True)['preview_revision'] != before


def test_preview_v2_review_changes_reject_old_pages_and_keep_authority(tmp_path):
    app, tid, _ = preview_case(tmp_path)
    with app.repository.read() as conn:
        before = app.delivery.preview(conn, tid, preview_protocol=2)
    with app.repository.transaction() as conn:
        conn.execute("UPDATE reviews SET status='accepted' WHERE task_id=?", (tid,))
    with app.repository.read() as conn, pytest.raises(DomainError) as error:
        app.delivery.preview(conn, tid, preview_protocol=2, expected_preview_id=before['preview_id'])
    assert error.value.code == 'PREVIEW_CHANGED'
    result = app.view(tid, for_chat=True)
    assert result['reviews'][0]['status'] == 'accepted'
    assert result['reviews'][0]['evidence_bundle']
    assert result['preview_revision'] != before['preview_id']


def test_preview_v2_materializes_only_requested_page(tmp_path):
    app, tid, record = preview_case(tmp_path)
    with app.repository.transaction() as conn:
        other = deepcopy(record)
        other['measurement_id'] = 'other'
        other['content_sha256'] = content_hash(other)
        app.repository.put_object(conn, tid, 'measurement', 'other', 1, other)
    original = app.repository.object
    original_objects = app.repository.objects
    reads = []
    collections = []

    def counted_objects(conn, task_id, kind):
        collections.append(kind)
        return original_objects(conn, task_id, kind)

    def counted(conn, task_id, kind, *args, **kwargs):
        reads.append(kind)
        return original(conn, task_id, kind, *args, **kwargs)

    app.repository.object = counted
    app.repository.objects = counted_objects
    with app.repository.read() as conn:
        result = app.delivery.preview(conn, tid, preview_protocol=2, offset=1, limit=1)
    assert result['total'] == 2 and len(result['items']) == 1
    assert reads.count('context') == 1
    assert reads.count('evidence') == 1
    assert 'measurement' not in collections


@pytest.mark.parametrize('dependency', ['generation', 'artifact_availability', 'derived_current'])
def test_preview_v2_token_covers_generation_and_reference_availability(tmp_path, dependency):
    app, tid, _ = preview_case(tmp_path)
    with app.repository.transaction() as conn:
        conn.execute("INSERT INTO artifacts VALUES ('artifact','sha',1,'test.bin','text/plain','2020','ready')")
        conn.execute('INSERT INTO artifact_refs VALUES (?,?,?)', (tid, 'artifact', 'source'))
    before = app.view(tid, for_workspace=True)['preview_revision']
    with app.repository.transaction() as conn:
        if dependency == 'generation':
            conn.execute('UPDATE tasks SET generation=generation+1 WHERE task_id=?', (tid,))
        elif dependency == 'artifact_availability':
            conn.execute("UPDATE artifacts SET availability='deleted' WHERE artifact_id='artifact'")
        else:
            app.repository.put_object(conn, tid, dependency, 'pointer', 1, {'changed': True})
    after = app.view(tid, for_workspace=True)['preview_revision']
    assert after != before
    with app.repository.read() as conn:
        assert app.delivery.preview(conn, tid, preview_protocol=2)['preview_id'] == after


def test_chat_keeps_complete_pending_options_and_confirmation_hash(tmp_path):
    app = create_app(tmp_path, start_worker=False).state.application
    tid = app.create('SYNTHETIC question', str(uuid4()))['task_id']
    question = {'question_id': 'question', 'title': 'SYNTHETIC choose properties',
                'kind': 'confirmation', 'choices': [{'id': 'confirm', 'label': 'Confirm'}],
                'preview': {'preview_hash': 'SYNTHETIC exact confirmation hash'},
                'property_catalog': {'bindings': [
                    {'property_id': 'length', 'definition': {'name_cn': '长度'}}]}}
    with app.repository.transaction() as conn:
        draft = app.repository.object(conn, tid, 'draft', tid)
        draft.update(pending_question=question, status='waiting_input', revision=draft['revision'] + 1)
        app.repository.put_object(conn, tid, 'draft', tid, draft['revision'], draft)
        app.repository.event(conn, tid, 'draft_changed', {})
        app.repository.mutate_task(conn, tid, lifecycle='waiting_input')
    state = app.view(tid, for_chat=True)
    assert state['pending'] == question
    assert state['draft']['pending_question'] == question
    assert state['presentation']['draft_question']['options'] == [{'id': 'length', 'name': '长度'}]
    assert state['presentation']['request']['preview']['preview_hash'] == question['preview']['preview_hash']
