"""Synthetic engineering boundaries, separate from real paper validation."""
import pytest
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.papers.figures import crop_page, inspect_figure_pages, validate_figures


def test_crop_keeps_labels_above_the_matching_native_caption():
    from astroquery_ai.science.papers.figures import protective_box
    proposal = {'label': 'Figure 3', 'bbox': [.12, .2, .86, .60]}
    candidate = {'captions': [{'text': 'Fig. 3. Synthetic caption', 'bbox': [60, 650, 540, 750]},
                              {'text': 'Fig. 4. Other figure', 'bbox': [60, 900, 540, 980]}]}
    box = protective_box(proposal, candidate, {'height': 1000})
    assert box[3] == .655 and box[3] < .9


def test_local_candidates_and_faithful_crop(tmp_path):
    import pymupdf as fitz
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(60, 100, 540, 500))
    page.insert_text((60, 540), 'Figure 1. SYNTHETIC target plot.')
    scan = page.get_pixmap().tobytes('png')
    doc.new_page().insert_text((60, 60), 'SYNTHETIC ordinary text, not a figure.')
    blank_scan = doc.new_page()
    blank_scan.insert_image(blank_scan.rect, stream=scan)
    path = tmp_path / 'synthetic.pdf'
    doc.save(path)
    doc.close()
    layout = inspect_figure_pages(path)
    assert [c['page'] for c in layout['candidates']] == [1]
    assert layout['other_pages'] == [2]
    assert layout['unclassified_pages'] == [3]
    selected = inspect_figure_pages(path, pages=[1])
    assert [c['page'] for c in selected['candidates']] == [1]
    assert selected['other_pages'] == selected['unclassified_pages'] == []
    for pages in ([0], [4], [1, 1], [True]):
        with pytest.raises(DomainError):
            inspect_figure_pages(path, pages=pages)
    raw = crop_page(path, 1, [.05, .08, .95, .7], dpi=72)
    pix = fitz.Pixmap(raw)
    assert pix.width == 540 and pix.height == 496
    for box in ([0, 0, 2, 1], [0, 0, float('nan'), 1], [1, 0, 0, 1]):
        with pytest.raises(DomainError):
            crop_page(path, 1, box)


def example():
    spec = {'properties': [{'property_id': 'synthetic-dm'}]}
    source = {'work': {'allowed_property_ids': ['synthetic-dm']}}
    context = [{'page': 1, 'text': 'Figure 1. DM of SYNTHETIC_A (circles) and SYNTHETIC_B (squares).'}]
    item = {'label': 'Figure 1', 'bbox': [.1, .1, .9, .8], 'caption': context[0]['text'],
            'description': 'Synthetic example', 'relevance': 'DM', 'property_ids': ['synthetic-dm'],
            'target_association': 'B is squares', 'association_quote': 'DM of ... SYNTHETIC_B (squares)',
            'association_basis': 'caption'}
    return spec, source, context, {'outcome': 'relevant', 'figures': [item]}


def test_quoted_fragments_and_scope_are_checked_without_numeric_admission():
    spec, source, context, response = example()
    assert validate_figures(response, spec, source, context, 1) == response['figures']
    response['figures'][0]['association_quote'] = 'SYNTHETIC_B ... DM of'
    with pytest.raises(DomainError, match='目标关联'):
        validate_figures(response, spec, source, context, 1)
    spec, source, context, response = example()
    response['figures'][0]['property_ids'] = ['unconfirmed']
    with pytest.raises(DomainError, match='性质'):
        validate_figures(response, spec, source, context, 1)
    assert validate_figures({'outcome': 'no_relevant', 'figures': []}, spec, source, context, 1) == []
    assert validate_figures({'outcome': 'no_relevant', 'figures': [{'property_ids': []}]}, spec, source, context, 1) == []
    spec, source, context, response = example()
    context[0]['text'] = context[0]['text'].replace('squares', 'SQUA-\nRES')
    assert validate_figures(response, spec, source, context, 1)


def test_figure_work_shares_source_lock_and_stage_barrier(tmp_path):
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.runtime.stages import set_stage
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC figures stage')['task_id']
    with repo.transaction() as conn:
        set_stage(repo, conn, tid, 'extraction')
        one = repo.enqueue(conn, tid, 'M06', 'paper_figure_page', {'work_id': 'a'})
        two = repo.enqueue(conn, tid, 'M06', 'paper_batch', {'work_id': 'a'})
        three = repo.enqueue(conn, tid, 'M06', 'paper_figure_page', {'work_id': 'b'})
        repo.enqueue(conn, tid, 'M07', 'assess_batch', {'measurement_ids': []})
    assert {repo.claim_job('worker')['job_id'], repo.claim_job('worker')['job_id']} == {one, three}
    assert repo.claim_job('worker') is None


def test_figure_failure_is_not_a_numeric_gap_or_task_interrupt(tmp_path):
    from astroquery_ai.application.service import Application
    from astroquery_ai.runtime.scheduler import Scheduler
    app = Application(tmp_path / 'runtime', allow_synthetic=True)
    tid = app.repository.create_task('SYNTHETIC failed figure')['task_id']
    with app.repository.transaction() as conn:
        app.repository.enqueue(conn, tid, 'M06', 'paper_figure_page', {'work_id': 'synthetic', 'candidate': {'page': 2}})
    job = app.repository.claim_job('worker')
    Scheduler(app).fail(job, DomainError('FIGURE_BOX_INVALID', 'Synthetic bad box'))
    with app.repository.read() as conn:
        coverage = app.repository.objects(conn, tid, 'figure_coverage')
        assert coverage[0]['state'] == 'failed'
        assert app.repository.objects(conn, tid, 'coverage') == []
        assert app.repository.task(conn, tid)['lifecycle'] != 'interrupted'


def test_api_reads_only_sealed_figures_and_enforces_artifact_ownership(tmp_path):
    from fastapi.testclient import TestClient
    from astroquery_ai.api.http import create_app
    from astroquery_ai.application.service import Application
    app = Application(tmp_path / 'runtime', allow_synthetic=True)
    tid = app.repository.create_task('SYNTHETIC delivery')['task_id']
    other = app.repository.create_task('SYNTHETIC other task')['task_id']
    png = app.artifacts.write(b'synthetic image bytes', 'image/png')
    with app.repository.transaction() as conn:
        app.artifacts.register(conn, tid, 'synthetic-figure', png)
        app.repository.put_object(conn, tid, 'figure', 'unbound', 1, {'figure_id': 'unbound'})
        body = {'delivery_id': 'synthetic-delivery', 'revision':1, 'snapshot_ref': {'id': 'synthetic-snapshot'},
                'figures': [{'figure_id': 'bound', 'image_artifact': png, 'page_artifact': png,
                             'pdf_artifact_id': png['artifact_id'], 'page': 1}],
                'figure_coverage': [{'state': 'available'}]}
        ref = app.repository.put_object(conn, tid, 'delivery', body['delivery_id'], 1, body)
        app.repository.mutate_task(conn, tid, delivery_ref=canonical(ref).decode(), science_state='sealed')
    with TestClient(create_app(app.root, application=app, start_worker=False)) as client:
        r = client.get(f'/api/tasks/{tid}/deliveries/synthetic-delivery/figures')
        assert r.status_code == 200
        assert [f['figure_id'] for f in r.json()['items']] == ['bound']
        assert r.json()['coverage'] == [{'state': 'available'}]
        assert r.json()['delivery_revision']==1
        image = client.get(r.json()['items'][0]['image_url'])
        assert image.content == b'synthetic image bytes' and image.headers['content-disposition'].startswith('inline')
        assert client.get(f"/api/tasks/{other}/artifacts/{png['artifact_id']}").status_code != 200


@pytest.mark.parametrize('layout_failure', [False, True])
def test_null_reading_hint_label_cannot_erase_valid_sibling_figures(tmp_path, layout_failure):
    import asyncio
    from tests.rebuild.test_bounded_reading import fixture
    async def run():
        app,service,tid,_=fixture(tmp_path,'empty');repo=app.repository
        await service.extract_paper(repo.claim_job('worker',lease_seconds=600))
        with repo.read() as c:
            source=repo.object(c,tid,'source','synthetic-source')
            spec=service.spec(c,tid)
        _,_,context,response=example();good=response['figures'][0]
        good.update(page=1,property_ids=[spec['properties'][0]['property_id']],
            work_id=source['source_id'],reading_attempt_id='synthetic-reader')
        with repo.transaction() as c:
            repo.put_object(c,tid,'document_index',source['source_id'],2,{'pages':context})
            repo.put_object(c,tid,'reading_figure_hint','bad',1,
                {**good,'label':None,'caption':'','description':'SYNTHETIC no figure mentioned'})
            repo.put_object(c,tid,'reading_figure_hint','good',1,good)
            repo.enqueue(c,tid,'M06','paper_figures',{'work_id':source['source_id'],
                'artifact_ref':source['artifact']['artifact_id'],'reuse_body_hints':True})
        async def parsed(tid,aid,operation,**kwargs):
            if operation=='figure_candidates':
                assert kwargs['pages']==[1]  # No whole-paper geometry scan.
                if layout_failure:
                    raise DomainError('PARSER_FAILED', 'SYNTHETIC optional geometry unavailable')
                return {'candidates':[{'page':1,'reliable_bbox':None}]}
            return b'SYNTHETIC image bytes'
        app.parse_owned=parsed
        while (job:=repo.claim_job('worker',lease_seconds=600)) and job['kind']!='paper_figures':
            with repo.transaction() as c:repo.finish_job(c,job)
        await service.discover_figures(job)
        with repo.read() as c:
            figures=repo.objects(c,tid,'figure');coverage=repo.objects(c,tid,'figure_coverage')
            assert len(figures)==1 and figures[0]['label']=='Figure 1'
            assert not figures[0]['numeric_extraction']
            assert coverage[0]['failures'] and coverage[0]['understanding_reused']
            if layout_failure:
                assert figures[0]['crop_precision']=='original_page_fallback'
                assert any(x.get('scope')=='layout_only' for x in coverage[0]['failures'])
    asyncio.run(run())
