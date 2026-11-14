"""Synthetic 50/51 physical-page boundaries using the ordinary acquisition service."""
import asyncio
from dataclasses import asdict

import httpx
import pymupdf
import pytest

from astroquery_ai.runtime.codec import canonical, loads, digest
from astroquery_ai.runtime.run_policy import NORMAL_RUN_POLICY
from astroquery_ai.science.documents import probe_pdf
from astroquery_ai.science.literature import FairReadLedger
from astroquery_ai.science.workflow.paper_service import PaperService
from astroquery_ai.science.workflow.context import ScienceContext
from tests.rebuild.scenario import application


@pytest.mark.parametrize('pages', [50, 51])
def test_physical_page_gate_precedes_reading_figures_and_attachment_hunt(tmp_path, pages):
    async def run():
        app = application(tmp_path / 'runtime')
        with pymupdf.open() as document:
            for i in range(pages):
                page = document.new_page()
                if i == 0:
                    page.insert_text((30, 40), 'Synthetic physical page policy identity example\nDOI: 10.1234/synthetic-pages')
            raw = document.tobytes()
        app.http.transport = httpx.MockTransport(lambda request: httpx.Response(200, content=raw))
        tid = app.repository.create_task('SYNTHETIC physical page boundary')['task_id']
        ledger = FairReadLedger(['synthetic-family'], {'synthetic-family': ['synthetic-work', 'synthetic-next']},
                                {'synthetic-work': ['synthetic-family'], 'synthetic-next': ['synthetic-family']})
        selection = ledger.select()
        work = {'work_id': 'synthetic-work', 'allowed_property_ids': ['synthetic-length'],
                'records': [{'titles': ['Synthetic physical page policy identity example'],
                    'dois': ['10.1234/synthetic-pages'], 'arxivs': [],
                    'raw': {'links_data': [{'link_type': 'PUB_PDF', 'url': 'https://publisher.example/synthetic.pdf'}]}}]}
        with app.repository.transaction() as conn:
            # This tests the physical gate and legacy eager enqueue branch,
            # independently of the separately tested bounded reading policy.
            spec={'run_policy': {'documents':NORMAL_RUN_POLICY['documents']}, 'dependencies': [],
                  'registry_release': {'id': 'synthetic-page-policy'}}
            spec['spec_hash']=digest(spec)
            ref = app.repository.put_object(conn, tid, 'confirmed_query', tid, 1, spec)
            app.repository.mutate_task(conn, tid, lifecycle='running', science_state='open', query_ref=canonical(ref).decode())
            app.repository.put_object(conn, tid, 'read_ledger', tid, 1, asdict(ledger))
            app.repository.enqueue(conn, tid, 'M05', 'acquire_window', {'window': 1})
        job = app.repository.claim_job('synthetic-page-worker', task_id=tid)
        operations = []
        original = app.parsers.run
        async def parser(operation, path, **kwargs):
            operations.append(operation)
            return await original(operation, path, **kwargs)
        app.parsers.run = parser
        await PaperService(ScienceContext(app)).acquire_one(job, selection, work)
        with app.repository.read() as conn:
            jobs = [r[0] for r in conn.execute('SELECT kind FROM jobs WHERE task_id=?', (tid,))]
            state = app.repository.objects(conn, tid, 'acquisition_result')[0]
            saved_ledger = FairReadLedger(**app.repository.objects(conn, tid, 'read_ledger')[0])
        assert operations[0] == 'probe_pdf'
        if pages == 51:
            assert operations == ['probe_pdf']
            assert state['state'] == 'skipped' and state['skipped_versions'][0]['page_count'] == 51
            assert not {'paper_batch', 'paper_figures', 'attachment_discover'} & set(jobs)
            assert saved_ledger.selections['synthetic-work']['state'] == 'released'
            assert saved_ledger.select()['work_id'] == 'synthetic-next'
        else:
            assert 'inspect_pdf' in operations and {'paper_batch', 'paper_figures', 'attachment_discover'} <= set(jobs)
            assert state['state'] == 'acquired'
    asyncio.run(run())
