import asyncio
from types import SimpleNamespace

from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.delivery import current_delivery_measurements
from astroquery_ai.science.source_review import SameResultGroup, validated_group
from astroquery_ai.science.workflow.quality_service import QualityService
from tests.rebuild.factories import measurement
from tests.rebuild.test_catalog_transcription import proposal
from tests.rebuild.test_literature_and_review import review_case as review_case


def test_explicit_native_log_reference_basis_is_not_lost_as_an_unlabelled_coefficient():
    from astroquery_ai.science.source_review import source_review_outcome
    # Same response field relationship observed in the real current review:
    # coefficient has no physical label; reference basis is explicitly given.
    anchor={'page':3,'block_ids':['p3:l1-1']}
    assessment={'index':0,'subject':'target','printed_subject':'SYNTHETIC',
        'subject_evidence':[anchor],'result_role':'reported_result','role_evidence':[anchor],
        'quantity_match':'exact','quantity_evidence':[anchor],'native_unit':None,
        'unit_match':'unresolved','unit_evidence':[anchor],'reason':'SYNTHETIC log coefficient'}
    item={'item_id':'I1','native_representation':'log10','value_match':'exact',
        'coordinate_reference_unit':'yr','assessment':assessment,
        'source_quality':{'state':'checked','raw_info':['p3:l1-1'],'caution_quotes':[],'note':'actual scope'}}
    result,errors=source_review_outcome({'items':[item]})
    assert not errors and result.items[0].assessment.native_unit=='yr'
    assert result.items[0].assessment.unit_match=='exact'
    assert item['assessment']['unit_match']=='unresolved'  # Original response unchanged.
    item['assessment']={**assessment,'unit_match':'different'}
    result,_=source_review_outcome({'items':[item]})
    assert result.items[0].assessment.unit_match=='different'
    assert result.items[0].assessment.native_unit is None


def test_local_uncertainty_waits_for_existing_whole_source_owner_review(tmp_path):
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.runtime.reviews import ReviewService
    repo = Repository(tmp_path / 'SYNTHETIC-prereview.sqlite3')
    tid = repo.create_task('SYNTHETIC cross-page candidate')['task_id']
    with repo.transaction() as conn:
        repo.mutate_task(conn, tid, lifecycle='queued')
        original = repo.enqueue(conn, tid, 'M06', 'paper_batch', {'work_id': 'source'})
    reader = repo.claim_job('synthetic-reader')
    with repo.transaction() as conn:
        repo.finish_job(conn, reader)
        repo.put_object(conn, tid, 'candidate', 'c', 1, {'candidate_id': 'c', 'state': 'review_candidate',
            'evidence_ref': {'id': 'saved-original', 'version': 1},
            'assembly_context': {'owner': 'M06', 'batch_id': original, 'source': {'source_id': 'source'}}})
        repo.enqueue(conn, tid, 'M07', 'assess_batch', {'measurement_ids': [], 'candidate_ids': ['c']})
    reviews = ReviewService(repo)
    service = QualityService(SimpleNamespace(app=SimpleNamespace(reviews=reviews), repo=repo,
        steps=None, extractor=None))
    service.spec = lambda conn, tid: {'properties': []}
    job = repo.claim_job('synthetic-quality')
    asyncio.run(service.assess_batch(job))
    with repo.read() as conn:
        assert reviews.list(conn, tid) == []
        assert repo.objects(conn, tid, 'candidate_pre_review_pending')[0]['owner'] == 'M06'
        assert repo.objects(conn, tid, 'candidate')[0]['state'] == 'review_candidate'
        assert conn.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0


def test_recheck_carries_native_minus_and_header_instead_of_grepping_decimal():
    from astroquery_ai.science.source_review import source_review_blocks
    from astroquery_ai.science.paper_admission import page_blocks
    from types import SimpleNamespace
    pages = {1: 'SYNTHETIC object X. Values are residuals relative to a fixed reference.',
             4: 'SYNTHETIC fitted residual table\n' + ('header details ' * 60) + '\nBase Q (10^-5 units)\n−4 ± 1'}
    anchors = page_blocks(pages)
    verification = {'check': {'quantity_evidence': [{'page': 4, 'block_ids': [anchors[-1]['block_id']]}],
                              'context': [{'anchor': {'page': 1, 'block_ids': [anchors[0]['block_id']]}}]}}
    selected, omitted = source_review_blocks(pages, [SimpleNamespace(page=4)], [verification], {'main_id': 'X'})
    text = '\n'.join(b['text'] for b in selected)
    assert '−4 ± 1' in text and 'fitted residual table' in text and 'relative to a fixed reference' in text
    assert not omitted
    tiny, omissions = source_review_blocks(pages, [SimpleNamespace(page=4)], [verification], {'main_id': 'X'}, byte_limit=80)
    assert omissions and sum(len(b['text'].encode()) for b in tiny) <= 80


def test_scoped_context_continuation_carries_bounded_original_neighbors():
    from astroquery_ai.science.source_review import source_review_blocks
    from astroquery_ai.science.paper_admission import page_blocks
    from types import SimpleNamespace
    # Actual block boundaries and a page continuation, with no science-name
    # or expected-value lookup in the assembly path.
    pages={1:'SYNTHETIC target X',2:'\n'.join('SYNTHETIC adjacent '+str(i)+' '+('a'*650) for i in range(6)),
           3:'SYNTHETIC continuation '+('b'*650)+'\nSYNTHETIC following '+('c'*650),
           8:'SYNTHETIC original value'}
    blocks=page_blocks(pages);note=next(b for b in blocks if b['page']==3)
    before,_=source_review_blocks(pages,[SimpleNamespace(page=8)],[],{'main_id':'X'},context_blocks=[note])
    after,_=source_review_blocks(pages,[SimpleNamespace(page=8)],[],{'main_id':'X'},context_blocks=[note],context_neighbors=True)
    added={b['block_id'] for b in after}-{b['block_id'] for b in before}
    previous=[b['block_id'] for b in blocks if b['page']==2][-3:]
    following=[b['block_id'] for b in blocks if b['page']==3][1]
    assert added==set([*previous,following])
    assert all(b in blocks for b in after)
    limited,omitted=source_review_blocks(pages,[SimpleNamespace(page=8)],[],{'main_id':'X'},context_blocks=[note],context_neighbors=True,byte_limit=800)
    assert omitted and sum(len(b['text'].encode()) for b in limited)<=800


def test_text_tables_keep_original_layout_in_the_same_bounded_review():
    from astroquery_ai.science.source_review import review_image_pages,initial_review_groups
    from types import SimpleNamespace
    pages={i:'SYNTHETIC full native text '+('x'*900) for i in range(1,6)}
    props=[SimpleNamespace(page=i,location_kind='table') for i in pages]
    assert review_image_pages(props,pages)==[]
    assert review_image_pages(props,pages,table_layout=True)==list(pages)
    refs=[{'id':str(i)} for i in pages]
    candidates={str(i):{'proposal':{'page':i,'location_kind':'table'}} for i in pages}
    groups=list(initial_review_groups(refs,candidates,pages,table_layout=True))
    assert [len(g) for g in groups]==[4,1]
    assert [r['id'] for g in groups for r in g]==[str(i) for i in pages]


def test_source_recheck_never_answers_pending_human_review_or_promotes_candidate(review_case):
    repo, tid, reviews, original = review_case
    with repo.transaction() as conn:
        before = canonical(reviews.list(conn, tid))
        report = {'outcomes': [
            {'item_ref': {'kind': 'measurement', 'id': 'm1'}, 'state': 'rejected'},
            {'item_ref': {'kind': 'candidate', 'id': 'c1'}, 'state': 'passed'},
        ], 'same_results': [{'member_refs': [{'id': 'm1'}, {'id': 'm2'}]}]}
        reference = repo.put_object(conn, tid, 'source_recheck', 'SYNTHETIC recheck', 1, report)
        repo.enqueue(conn, tid, 'M07', 'apply_source_recheck', {'recheck_ref': reference})
    context = SimpleNamespace(app=SimpleNamespace(reviews=reviews), repo=repo, steps=None,
                              extractor=None, spec=lambda conn, tid: {'properties': []})
    service = QualityService(context)
    job = repo.claim_job('SYNTHETIC owner')
    asyncio.run(service.apply_source_recheck(job))
    with repo.read() as conn:
        assert canonical(reviews.list(conn, tid)) == before
        assert not repo.objects(conn, tid, 'admission_disposition')
        assert not repo.objects(conn, tid, 'measurement')
        assert not repo.objects(conn, tid, 'review_answer')


def test_duplicate_result_requires_source_identity_and_keeps_different_values():
    p = proposal().model_dump(mode='json')
    p['location_kind'] = 'table'
    q = {**p, 'location_kind': 'caption'}
    block = {'page': 1, 'block_id': 'p1:l1-3', 'text': 'SYNTHETIC midpoint fit repeated in caption.'}
    group = SameResultGroup(canonical_id='a', member_ids=['a', 'b'], discriminator='midpoint fit',
                            evidence=[{'page': 1, 'block_ids': [block['block_id']]}], reason='Same source result.')
    assert validated_group(group, {'a': p, 'b': q}, {'a', 'b'}, {block['block_id']: block})
    paraphrase = group.model_copy(update={'discriminator': 'same midpoint-derived observation'})
    assert validated_group(paraphrase, {'a': p, 'b': q}, {'a', 'b'}, {block['block_id']: block})
    distant = {**q, 'page': 7}
    assert not validated_group(paraphrase, {'a': p, 'b': distant}, {'a', 'b'}, {block['block_id']: block})
    assert not validated_group(group, {'a': p, 'b': q}, {'a'}, {block['block_id']: block})
    q['value'] = {'kind': 'real', 'value': '26.764101'}
    assert not validated_group(group, {'a': p, 'b': q}, {'a', 'b'}, {block['block_id']: block})
    q['value'] = p['value']
    q['errors'] = [{'kind': 'symmetric_delta', 'role': 'sys', 'meaning': 'reported_error',
                    'interpretation_state': 'parsed', 'values': {'delta': '0.001'}, 'raw_text': 'SYNTHETIC sys +/-0.001'}]
    assert not validated_group(group, {'a': p, 'b': q}, {'a', 'b'}, {block['block_id']: block})


def test_source_disposition_cannot_exclude_later_human_revision():
    old = measurement('SYNTHETIC m1')
    old_ref = {'id': old['measurement_id'], 'version': 1, 'content_sha256': old['content_sha256']}
    disposition = {'measurement_id': old['measurement_id'], 'measurement_ref': old_ref, 'status': 'unresolved_main'}
    assert current_delivery_measurements([old], [disposition]) == []
    new = {**old, 'revision': 2, 'content_sha256': 'SYNTHETIC human-rechecked-version'}
    assert current_delivery_measurements([new], [disposition]) == [new]


def test_explicit_canonical_location_is_part_of_declared_duplicate_group():
    from astroquery_ai.science.source_review import source_review_outcome
    response={'items':[], 'same_results':[{'canonical_id':'a','member_ids':['b','c'],
        'discriminator':'SYNTHETIC same fitted observation', 'reason':'Explicit source result identity',
        'evidence':[{'page':1,'block_ids':['actual-block']}]}]}
    review,errors=source_review_outcome(response)
    assert not errors and review.same_results[0].member_ids==['a','b','c']
    p=proposal().model_dump(mode='json')
    p['location_kind']='table'
    block={'page':1,'block_id':'actual-block','text':'SYNTHETIC fitted result repeated.'}
    assert validated_group(review.same_results[0],{k:p for k in ('a','b','c')}, {'a','b','c'}, {'actual-block':block})
    assert not validated_group(review.same_results[0],{k:p for k in ('a','b','c')}, {'a','b'}, {'actual-block':block})


def test_owner_repair_clears_only_exact_failed_machine_finding():
    from astroquery_ai.runtime.codec import content_hash
    record = measurement('synthetic-exact-repair')
    ref = {'id': record['measurement_id'], 'version': 1, 'content_sha256': record['content_sha256']}
    failed = {'disposition_id': 'failed', 'measurement_id': record['measurement_id'],
        'measurement_ref': ref, 'status': 'unresolved_main'}
    repaired = {'status': 'owner_rechecked_eligible', 'measurement_id': record['measurement_id'],
        'measurement_ref': ref, 'resolves_disposition_refs': [{'id': 'failed', 'content_sha256': content_hash(failed)}]}
    assert current_delivery_measurements([record], [failed]) == []
    assert current_delivery_measurements([record], [failed, repaired]) == [record]
    repaired['resolves_disposition_refs'][0]['content_sha256'] = 'different-finding'
    assert current_delivery_measurements([record], [failed, repaired]) == []
    failed['answer_ref'] = {'id': 'actual-human-decision'}
    repaired['resolves_disposition_refs'][0]['content_sha256'] = content_hash(failed)
    assert current_delivery_measurements([record], [failed, repaired]) == []


def test_repaired_source_gets_new_plan_only_when_actual_items_change(tmp_path):
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.science.workflow.orchestration_service import OrchestrationService
    repo = Repository(tmp_path / 'SYNTHETIC plans.sqlite3')
    tid = repo.create_task('SYNTHETIC incremental source')['task_id']
    with repo.transaction() as conn:
        reference = repo.put_object(conn, tid, 'confirmed_query', 'SYNTHETIC spec', 1,
            {'dependencies': [], 'registry_release': {'id': 'SYNTHETIC release'}})
        repo.mutate_task(conn, tid, query_ref=canonical(reference).decode(), science_state='open', lifecycle='queued')
        repo.put_object(conn, tid, 'source', 'SYNTHETIC source', 1, {'source_id': 'SYNTHETIC source', 'kind': 'paper'})
        first = measurement('SYNTHETIC m1', source='SYNTHETIC source')
        repo.put_object(conn, tid, 'measurement', first['measurement_id'], 1, first)
        repo.enqueue(conn, tid, 'M06', 'paper_batch', {'work_id': 'SYNTHETIC source', 'core_pages': [1]})
    job = repo.claim_job('SYNTHETIC worker')
    with repo.transaction() as conn:
        repo.finish_job(conn, job)
    context = SimpleNamespace(app=None, repo=repo, steps=None, extractor=None,
        spec=lambda conn, task_id: repo.object(conn, task_id, 'confirmed_query', 'SYNTHETIC spec'))
    service = OrchestrationService(context)
    asyncio.run(service.advance(tid))
    asyncio.run(service.advance(tid))
    with repo.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM jobs WHERE kind='source_reconcile'").fetchone()[0] == 1
        second = measurement('SYNTHETIC m2', source='SYNTHETIC source')
        repo.put_object(conn, tid, 'measurement', second['measurement_id'], 1, second)
    asyncio.run(service.advance(tid))
    with repo.read() as conn:
        assert conn.execute("SELECT count(*) FROM jobs WHERE kind='source_reconcile'").fetchone()[0] == 2
        plan = repo.object(conn, tid, 'source_review_plan', 'SYNTHETIC source')
        assert plan['revision'] == 2 and len(plan['items']) == 2


def test_unavailable_source_check_routes_current_inputs_without_paid_retry(review_case):
    from astroquery_ai.runtime.codec import content_hash
    repo, tid, reviews, original = review_case
    with repo.transaction() as conn:
        # The existing m1 question must remain authoritative; m2 needs review.
        for mid in ['m1', 'm2', 'checked', 'stale']:
            m = measurement(mid)
            m['evidence_refs'] = original['evidence_refs']
            m['content_sha256'] = content_hash(m)
            repo.put_object(conn, tid, 'measurement', mid, 1, m)
        repo.put_object(conn, tid, 'interpretation', 'interpretation', 1, {'proposal': proposal().model_dump(mode='json')})
        rows = repo.objects(conn, tid, 'measurement')
        refs = [{'kind': 'measurement', 'id': m['measurement_id'], 'version': 1, 'content_sha256': m['content_sha256']} for m in rows]
        next(r for r in refs if r['id'] == 'stale')['content_sha256'] = 'SYNTHETIC superseded input'
        checked = next(r for r in refs if r['id'] == 'checked')
        repo.put_object(conn, tid, 'source_recheck', 'SYNTHETIC checked', 1, {'outcomes': [{'item_ref': checked, 'state': 'passed'}]})
        repo.put_object(conn, tid, 'coverage', 'SYNTHETIC source gap', 1,
            {'reason': 'source_recheck_MODULE_READING_LIMIT', 'scope': {'items': refs}})
        repo.enqueue(conn, tid, 'M07', 'review_source_gap', {'gap_id': 'SYNTHETIC source gap'})
    service = QualityService(SimpleNamespace(app=SimpleNamespace(reviews=reviews), repo=repo, steps=None, extractor=None))
    service.spec = lambda conn, tid: {'spec_hash': 'SYNTHETIC spec', 'properties': [{
        'property_id': 'synthetic-property', 'definition': {'name_cn': 'SYNTHETIC quantity', 'measurement_conditions_schema': []}}]}
    job = repo.claim_job('SYNTHETIC worker')
    asyncio.run(service.review_source_gap(job))
    with repo.read() as conn:
        questions = reviews.list(conn, tid)
        assert len(questions) == 1 and questions[0]['review_id'] == original['review_id']
        assert not repo.objects(conn, tid, 'admission_disposition')
        assert repo.objects(conn, tid, 'source_review_gap_application')[0]['reason'] == 'owner_technical_failure_not_scientific_ambiguity'
        assert conn.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
        assert not repo.objects(conn, tid, 'review_answer')


def test_resume_without_ready_workers_still_reconciles_once(review_case):
    repo, tid, reviews, original = review_case
    with repo.transaction() as conn:
        reference = repo.put_object(conn, tid, 'confirmed_query', 'SYNTHETIC query', 1, {'spec_hash': 'SYNTHETIC spec'})
        repo.mutate_task(conn, tid, lifecycle='paused', query_ref=canonical(reference).decode())
        before = repo.task(conn, tid)
    result = repo.control(tid, 'continue', 'SYNTHETIC resume', before['revision'])
    assert result == repo.control(tid, 'continue', 'SYNTHETIC resume', before['revision'])
    with repo.read() as conn:
        assert conn.execute("SELECT count(*) FROM jobs WHERE kind='reconcile' AND status='ready'").fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
