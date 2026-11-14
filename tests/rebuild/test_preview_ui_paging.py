"""Exercise the actual UI endpoint, including table evidence enrichment."""
from copy import deepcopy

from fastapi.testclient import TestClient

from astroquery_ai.runtime.codec import content_hash
from tests.rebuild.test_provisional_preview import preview_case
from web.runtime_app import create_app


def test_ui_preview_page_bounds_decoding_and_keeps_cross_record_columns(tmp_path, monkeypatch):
    app, tid, original = preview_case(tmp_path)
    repo = app.repository
    with repo.transaction() as conn:
        evidence = repo.put_object(conn, tid, 'evidence', 'evidence', 2, {
            'evidence_id': 'evidence', 'source_id': 'source', 'text_origin': 'original_cells',
            'artifact_ref': {'id': 'saved-cells', 'content_sha256': 'cells-hash'},
            'raw_text': '{"cells":{"v":"2","own_error":"0.1","cross_error":"0.2","unused":"3"}}',
            'locator': {'column': 'v', 'row': 1}})
        own = repo.put_object(conn, tid, 'interpretation', 'own', 1,
            {'interpretation_id': 'own', 'proposal': {'errors': [{'location': 'own_error'}]}})
        cross = repo.put_object(conn, tid, 'interpretation', 'cross', 1,
            {'interpretation_id': 'cross', 'proposal': {'catalog_field_roles': [{'column': 'cross_error'}]}})
        first = deepcopy(original)
        first.update(revision=2, evidence_refs=[evidence], interpretation_ref=own)
        first['content_sha256'] = content_hash(first)
        repo.put_object(conn, tid, 'measurement', first['measurement_id'], 2, first)
        processing = {'derived_id': 'processing-first', 'measurement_id': first['measurement_id'], 'status': 'saved'}
        repo.put_object(conn, tid, 'derived', processing['derived_id'], 1, processing)
        for index in range(120):
            record = deepcopy(first)
            record.update(measurement_id=f'zz-{index:03}', revision=1, interpretation_ref=cross if index == 0 else own)
            record['content_sha256'] = content_hash(record)
            repo.put_object(conn, tid, 'measurement', record['measurement_id'], 1, record)
            repo.put_object(conn, tid, 'derived', f'processing-{index:03}', 1,
                {'derived_id': f'processing-{index:03}', 'measurement_id': record['measurement_id'], 'status': 'other'})
            repo.put_object(conn, tid, 'interpretation', f'unrelated-{index:03}', 1,
                {'interpretation_id': f'unrelated-{index:03}', 'proposal': {'errors': [{'location': 'unused'}]}})
    with TestClient(create_app(tmp_path, application=app, start_worker=False)) as client:
        old = client.get(f'/api/tasks/{tid}/preview?view=ui&limit=1').json()
        calls, reads = [], []
        objects, object_ = repo.objects, repo.object
        def collection(conn, task_id, kind):
            calls.append(kind)
            return objects(conn, task_id, kind)
        def individual(conn, task_id, kind, *args, **kwargs):
            reads.append(kind)
            return object_(conn, task_id, kind, *args, **kwargs)
        monkeypatch.setattr(repo, 'objects', collection)
        monkeypatch.setattr(repo, 'object', individual)
        response = client.get(f'/api/tasks/{tid}/preview?view=ui&preview_protocol=2&limit=1')
        assert response.status_code == 200
        body = response.json()
        assert body['total'] == 121 and len(body['items']) == 1
        assert body['items'] == old['items']
        assert body['items'][0]['saved_processing'] == processing
        cells = body['items'][0]['evidence_views'][0]['cells']
        assert {c['column'] for c in cells if c['is_selected']} == {'v', 'own_error', 'cross_error'}
        assert not {'measurement', 'interpretation', 'derived'}.intersection(calls)
        assert reads.count('interpretation') == 2 and reads.count('derived') == 1


def test_preview_paper_enrichment_decodes_only_latest_matching_artifacts(tmp_path, monkeypatch):
    from astroquery_ai.application.preview_views import enrich_preview_page
    from astroquery_ai.runtime.repository import Repository
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC bounded paper enrichment')['task_id']
    with repo.transaction() as conn:
        for object_id, sha, width in [('good-index', 'target-sha', 100), ('stale-index', 'target-sha', 999),
                                      ('unrelated-index', 'other-sha', 777)]:
            repo.put_object(conn, tid, 'document_index', object_id, 1,
                {'sha256': sha, 'pages': [{'page': 2, 'width': width, 'height': 200}]})
        repo.put_object(conn, tid, 'document_index', 'stale-index', 2,
            {'sha256': 'other-sha', 'pages': [{'page': 2, 'width': 999, 'height': 200}]})
        for object_id, pdf in [('good-preview', 'target-pdf'), ('stale-preview', 'target-pdf'),
                               ('unrelated-preview', 'other-pdf')]:
            repo.put_object(conn, tid, 'evidence_page_preview', object_id, 1,
                {'pdf_artifact_id': pdf, 'page': 2, 'artifact': {'artifact_id': object_id}})
        repo.put_object(conn, tid, 'evidence_page_preview', 'stale-preview', 2,
            {'pdf_artifact_id': 'other-pdf', 'page': 2, 'artifact': {'artifact_id': 'stale-preview'}})
    read = repo.object
    loaded = []
    def counted(conn, task_id, kind, object_id, version=None):
        loaded.append((kind, object_id, version))
        return read(conn, task_id, kind, object_id, version)
    monkeypatch.setattr(repo, 'object', counted)
    rows = [{'source': {'measurement_id': 'm'}, 'source_document': {'source_id': 'paper'},
             'evidence': [{'evidence_id': 'paper-evidence', 'raw_text': 'Saved excerpt',
                'locator': {'page': 2}, 'artifact_ref': {'id': 'target-pdf', 'content_sha256': 'target-sha'}}]}]
    with repo.read() as conn:
        enrich_preview_page(repo, conn, tid, rows)
    point = rows[0]['evidence_views'][0]['points'][0]
    assert point['width'] == 100 and point['preview_artifact']['artifact_id'] == 'good-preview'
    assert loaded == [('document_index', 'good-index', 1), ('evidence_page_preview', 'good-preview', 1)]
