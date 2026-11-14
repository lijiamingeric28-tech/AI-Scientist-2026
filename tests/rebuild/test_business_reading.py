from astroquery_ai.runtime.repository import Repository
from astroquery_ai.science.catalog_plan import validate_plan
from astroquery_ai.science.paper_admission import context_fragments
from astroquery_ai.science.paper_admission import resolve_context_locator


def test_no_requested_columns_does_not_require_an_unnecessary_object_identifier():
    raw = dict(id_column=None, identity_namespace=None, properties=[], limitations=['SYNTHETIC non-DM table.'])
    assert validate_plan(raw, ['radio_flux'], ['DM']) == (raw, [])


def test_two_works_progress_but_two_batches_of_one_work_cannot_race(tmp_path):
    repo = Repository(tmp_path / 'runtime.sqlite3')
    task = repo.create_task('SYNTHETIC independent works')
    with repo.transaction() as conn:
        for work, pages in [('A', [1, 2]), ('A', [3, 4]), ('B', [1, 2])]:
            repo.enqueue(conn, task['task_id'], 'M06', 'paper_batch', {'work_id': work, 'core_pages': pages})
    first = repo.claim_job('worker1')
    second = repo.claim_job('worker2')
    assert first['payload']['work_id'] == 'A' and second['payload']['work_id'] == 'B'
    assert repo.claim_job('worker3') is None
    with repo.transaction() as conn:
        repo.finish_job(conn, first)
    third = repo.claim_job('worker1')
    assert third['payload']['work_id'] == 'A' and third['payload']['core_pages'] == [3, 4]


def test_carried_context_is_literal_and_obeys_two_page_bound():
    index = {'pages': [{'page': i, 'text': ('SYNTHETIC PSR B0329+54.' if i == 1 else 'SYNTHETIC previous method context.' if i == 4 else 'SYNTHETIC other page.')} for i in range(1, 7)]}
    fragments, native = context_fragments(index, {'main_id': 'PSR B0329+54', 'aliases': []}, [5, 6], [])
    assert set(native) == {1, 4} and all(f['text'] in native[f['page']] for f in fragments)
    _, native = context_fragments(index, {'main_id': 'PSR B0329+54', 'aliases': []}, [5, 6], [2, 3])
    assert not native  # Two explicit contextual pages already occupy the allowance.


def test_section_context_is_not_replaced_by_nearby_target_mention():
    index = {'pages': [
        {'page': 7, 'text': '4.2 Applying the method to SYNTHETIC OTHER\nTable 2 lists its bursts.'},
        {'page': 8, 'text': 'Figure 6. SYNTHETIC TARGET pulse plot.'},
        {'page': 9, 'text': 'Table 2. Burst results\n348.82'},
    ]}
    fragments, native = context_fragments(index, {'main_id': 'SYNTHETIC TARGET', 'aliases': []}, [9], [])
    assert set(native) == {7, 8}
    assert any('SYNTHETIC OTHER' in b['text'] for b in fragments)
    assert resolve_context_locator(index, 'Section 4.2', [9]) == [7]
    assert resolve_context_locator(index, 'Table 2', [7]) == [9]
    index['pages'].append({'page': 10, 'text': '10\nFooter only'})
    assert resolve_context_locator(index, 'Section 10', []) == []


def test_source_identity_fills_free_slot_after_preceding_section():
    index = {'pages': [
        {'page': 2, 'text': 'SYNTHETIC TARGET observed in this paper.'},
        {'page': 7, 'text': '3. Methods\nSame source fiducials described here.'},
        {'page': 8, 'text': 'Table 2. Five fiducial fits; target name omitted in table.'},
    ]}
    fragments, native = context_fragments(index, {'main_id': 'SYNTHETIC TARGET', 'aliases': []}, [8], [])
    assert set(native) == {2, 7} and any('SYNTHETIC TARGET' in b['text'] for b in fragments)


def test_exhausted_reading_scope_does_not_split_or_render_more_pages(tmp_path):
    import asyncio
    from astroquery_ai.runtime.errors import DomainError
    from astroquery_ai.science.workflow.paper_service import PaperService
    repo = Repository(tmp_path / 'runtime.sqlite3')
    task = repo.create_task('SYNTHETIC budget termination')
    with repo.transaction() as conn:
        for work in ['A', 'B']:
            repo.enqueue(conn, task['task_id'], 'M06', 'paper_batch', {'work_id': work, 'core_pages': [1, 2]})
    service = object.__new__(PaperService)
    service.repo = repo
    rendered = []

    async def extract(job):
        rendered.append(job['job_id'])
        raise DomainError('PILOT_BUDGET_EXHAUSTED', 'SYNTHETIC exhausted')

    service.extract_paper_once = extract
    for _ in range(2):
        job = repo.claim_job('SYNTHETIC worker')
        asyncio.run(service.extract_paper(job))
    assert len(rendered) == 1
    assert repo.claim_job('SYNTHETIC worker') is None
    with repo.read() as conn:
        assert len(repo.objects(conn, task['task_id'], 'reading_stop')) == 1
        assert len(repo.objects(conn, task['task_id'], 'coverage')) == 2
