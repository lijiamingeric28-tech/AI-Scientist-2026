"""Smoke tests for a credential-free installation and recovery of published originals."""
import asyncio
import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from astroquery_ai.api.http import create_app
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.parsing import Parsers
from astroquery_ai.runtime.paths import source_product
from astroquery_ai.tools.pack_demos import work_pdf_urls


def test_published_history_is_pinned_and_read_only(tmp_path):
    samples = json.loads((source_product() / 'frontend/public/demo-catalog.json').read_bytes())['samples']
    sample = samples[0]
    assert len(samples) == 7 and sample['object'] == 'SN 2014J'
    assert [s['task_id'] for s in samples if s.get('featured')] == [sample['task_id']]
    prefix = '/api/tasks/' + sample['task_id']
    with TestClient(create_app(root=tmp_path, start_worker=False)) as client:
        result = client.get(prefix + '/delivery').json()
        assert result['snapshot_ref'] == sample['snapshot_ref']
        assert result['display_counts']['records'] == sample['record_count']
        workspace = client.get(prefix + '/state', params={'view': 'workspace'}).json()
        assert workspace['lifecycle'] == 'completed'
        assert (workspace['delivery_ref']['id'], workspace['delivery_ref']['version']) == (result['delivery_id'], result['revision'])
        assert workspace['presentation']['cursor'] == workspace['core_event_cursor']
        assert [p['name'] for p in workspace['presentation']['properties']]
        assert 'jobs' not in workspace and 'messages' not in workspace
        url = f"{prefix}/deliveries/{result['delivery_id']}/sources"
        full = client.get(url).json()
        compact = client.get(url, params={'view': 'list', 'delivery_revision': result['revision']}).json()
        assert compact['snapshot_ref'] == full['snapshot_ref']
        assert [s['source_id'] for s in compact['items']] == [s['source_id'] for s in full['items']]
        assert [s.get('title') for s in compact['items']] == [s.get('title') for s in full['items']]
        assert len(json.dumps(compact)) < len(json.dumps(full))
        clock = client.get(prefix + '/replay-clock').json()
        assert clock['terminal_at'] and clock['timeline']
        records = client.get(f"{prefix}/deliveries/{result['delivery_id']}/records",
                             params={'limit': 1, 'view': 'list'}).json()['items']
        preview = client.post(prefix + '/exports/preview', json={
            'task_id': sample['task_id'], 'delivery_id': result['delivery_id'],
            'expected_delivery_revision': result['revision'], 'export_schema_version': 3,
            'operation_id': 'preview-published-record',
            'selection': {'measurement_ids': [records[0]['source']['measurement_id']], 'figure_ids': []},
            'options': {'data_format': 'csv', 'group_by': 'combined', 'container': 'direct', 'include_originals': False},
        })
        assert preview.status_code == 200 and preview.json()['record_count'] == 1
        assert client.post(prefix + '/retry', json={}).status_code == 405
        assert client.get('/api/tasks', params={'source':'user'}).json()['total'] == 0
        assert client.get('/api/tasks', params={'source':'sample'}).json()['total'] == 1


def test_saved_arxiv_identifiers_and_explicit_pdf_locations():
    record = {'arxivs': [['1011.5135', None], ['astro-ph/0101010', 2]], 'raw': {'links_data': [
        json.dumps({'type':'pdf', 'access':'open','url':'https://publisher.example/article.pdf'}),
        json.dumps({'type':'pdf', 'access':'open','url':'https://publisher.example/auth.pdf?token=private'}),
    ]}}
    assert list(work_pdf_urls(record)) == ['https://arxiv.org/pdf/1011.5135',
        'https://arxiv.org/pdf/astro-ph/0101010v2', 'https://arxiv.org/pdf/astro-ph/0101010',
        'https://publisher.example/article.pdf']


def test_uncached_page_can_render_for_display(tmp_path):
    path = tmp_path / 'page.pdf'
    with pymupdf.open() as doc:
        doc.new_page().insert_text((65, 65), 'Original page')
        doc.save(path)
    async def verify():
        parser = Parsers()
        image = await parser.run('page_image', path, page=1, display_only=True)
        assert image.startswith(b'\x89PNG')
        with pytest.raises(DomainError, match='原页预览'):
            await parser.run('inspect_pdf', path, display_only=True)
    asyncio.run(verify())
