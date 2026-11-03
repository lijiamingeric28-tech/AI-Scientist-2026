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
    assert len(samples) == 6 and sample['object'] == 'SN 2014J'
    assert [s['task_id'] for s in samples if s.get('featured')] == [sample['task_id']]
    prefix = '/api/tasks/' + sample['task_id']
    with TestClient(create_app(root=tmp_path, start_worker=False)) as client:
        result = client.get(prefix + '/delivery').json()
        assert result['snapshot_ref'] == sample['snapshot_ref']
        assert result['display_counts']['records'] == sample['record_count']
        clock = client.get(prefix + '/replay-clock').json()
        assert clock['terminal_at'] and clock['timeline']
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
