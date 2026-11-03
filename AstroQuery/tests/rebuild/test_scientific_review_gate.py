"""Synthetic routing boundaries; never a scientific accuracy claim."""
from astroquery_ai.science.measurements.admission_contracts import AdmissionCheck
from astroquery_ai.science.paper_admission import check_local_evidence, page_blocks
from astroquery_ai.science.processing.assessment import scientific_candidate_question
from astroquery_ai.science.units import decimal_unit_factor
from tests.rebuild.test_paper_admission import paper_proposal


def check_data():
    pages = {3: 'SYNTHETIC: target-like table label\nReported DM 26.74870(7).'}
    anchors = [{'page': 3, 'block_ids': [b['block_id']], 'quote': None} for b in page_blocks(pages)]
    return pages, anchors, dict(index=0, subject='target', printed_subject='typographic label',
        subject_evidence=anchors, role_evidence=anchors, result_role='reported_result',
        quantity_match='exact', quantity_evidence=anchors,
        subject_link=dict(method='semantic_scope', relation='target', local_evidence=anchors,
            scope_evidence=anchors, counter_evidence=[], reason='Synthetic explicit semantic relationship.'),
        reason='SYNTHETIC independent relation with actual source blocks.')


def test_semantic_scope_is_explicit_and_all_anchors_must_exist():
    pages, anchors, raw = check_data()
    target = {'main_id': 'SYNTHETIC_TARGET', 'aliases': []}
    p = paper_proposal()
    assert check_local_evidence(p, AdmissionCheck.model_validate(raw), target, pages, {}, require_quantity=True)['state'] == 'passed'
    raw['subject_link']['scope_evidence'] = [{'page': 3, 'block_ids': ['invented'], 'quote': None}]
    assert check_local_evidence(p, AdmissionCheck.model_validate(raw), target, pages, {}, require_quantity=True)['state'] != 'passed'


def test_grounded_ambiguity_can_ask_unable_but_unit_typo_cannot_be_confirmed():
    pages, anchors, raw = check_data()
    raw['review_issue'] = dict(issue_kind='unit_semantics', issue_key='printed-unit-conflict',
        question='SYNTHETIC：原文单位与所选量矛盾，应保留未决还是不采用？',
        undecided_fact='原文没有提供可核实的正确单位。', scope_evidence=anchors,
        support_evidence=anchors, counter_evidence=[], choices=[
            dict(action='not_supported', label='不采用当前解释', impact='不准入该候选。'),
            dict(action='unable', label='无法判断', impact='保留原件及未决候选。')])
    target = {'main_id': 'SYNTHETIC_TARGET', 'aliases': []}
    result = check_local_evidence(paper_proposal(), AdmissionCheck.model_validate(raw), target, pages, {}, require_quantity=True)
    assert result['reason'] == 'scientific_ambiguity'
    assert result['review_issue']['support_evidence'][0]['quote']
    raw['review_issue']['choices'][0]['action'] = 'confirm'
    result = check_local_evidence(paper_proposal(), AdmissionCheck.model_validate(raw), target, pages, {}, require_quantity=True)
    assert 'review_issue' not in result and result['review_issue_validation']


def test_technical_unresolved_candidate_does_not_become_generic_question():
    c = {'id': 'synthetic', 'proposal': {}, 'assembly_context': {'owner': 'M06'},
         'reason': 'local_subject_or_result_evidence_unresolved'}
    assert scientific_candidate_question(c, {}, {}) is None
    assert decimal_unit_factor('days', 's') == 86400


def test_bad_sibling_is_isolated_and_missing_units_stay_technical():
    from astroquery_ai.science.measurements.admission_contracts import admission_outcome
    from astroquery_ai.science.source_review import source_review_outcome
    pages, anchors, raw = check_data()
    checked, errors = admission_outcome({'results': [raw, {'index': 1, 'subject': 'invalid'}]})
    assert list(checked) == [0] and errors
    review, errors = source_review_outcome({'items': [dict(item_id='good', assessment=raw),
        dict(item_id='bad', assessment={'index': 1})], 'same_results': None})
    assert [i.item_id for i in review.items] == ['good'] and errors
    target = {'main_id': 'SYNTHETIC_TARGET', 'aliases': []}
    result = check_local_evidence(paper_proposal(), checked[0], target, pages, {}, require_units=True)
    assert result['reason'] == 'native_unit_not_verified' and 'review_issue' not in result


def test_declared_unit_check_cannot_be_overridden_by_exact_boolean():
    pages, anchors, raw = check_data()
    pages[3] += ' Unit: mag.'
    raw.update(unit_match='exact', native_unit='mag', unit_evidence=anchors)
    p=paper_proposal().model_copy(update={'unit':'d'})
    result=check_local_evidence(p,AdmissionCheck.model_validate(raw),{'main_id':'SYNTHETIC_TARGET','aliases':[]},pages,{},require_units=True)
    assert result['reason']=='scientific_ambiguity'
    assert [c['action'] for c in result['review_issue']['choices']]==['not_supported','unable']
    raw['native_unit']='days'
    assert check_local_evidence(p,AdmissionCheck.model_validate(raw),{'main_id':'SYNTHETIC_TARGET','aliases':[]},pages,{},require_units=True)['state']=='passed'


def test_native_log_basis_is_evidenced_and_does_not_supply_a_missing_basis():
    from astroquery_ai.science.source_review import source_review_outcome
    from copy import deepcopy
    _, anchors, assessment = check_data()
    assessment.update(unit_match='exact', native_unit=None, unit_evidence=anchors)
    item = dict(item_id='synthetic-log', assessment=assessment,
                native_representation='log10', coordinate_reference_unit='yr')
    review, errors = source_review_outcome({'items': [item]})
    assert not errors and review.items[0].assessment.native_unit == 'yr'
    assert review.items[0].assessment.unit_evidence[0].block_ids == anchors[0]['block_ids']
    for field, value in [('unit_evidence', []), ('unit_match', 'unresolved')]:
        unresolved = deepcopy(item)
        unresolved['assessment'][field] = value
        review, _ = source_review_outcome({'items': [unresolved]})
        assert review.items[0].assessment.native_unit is None
    absent = deepcopy(item)
    del absent['coordinate_reference_unit']
    review, _ = source_review_outcome({'items': [absent]})
    assert review.items[0].assessment.native_unit is None


def test_grouped_question_has_individual_bases_and_rejects_stale_answer(tmp_path):
    import asyncio
    from copy import deepcopy
    from uuid import uuid4
    import pytest
    from astroquery_ai.runtime.codec import content_hash
    from astroquery_ai.runtime.errors import DomainError
    from astroquery_ai.runtime.reviews import ReviewAnswer
    from tests.rebuild.scenario import application, confirmed_case, run_until_wait

    async def run():
        app = application(tmp_path)
        state, scheduler = await confirmed_case(app, ambiguous=True)
        first = state['reviews'][0]
        tid = state['task_id']
        with app.repository.transaction() as conn:
            original = app.repository.object(conn, tid, 'candidate', first['scope']['candidate_ids'][0])
            second = deepcopy(original)
            second['candidate_id'] += '-second-mention'
            app.repository.put_object(conn, tid, 'candidate', second['candidate_id'], 1, second)
            spec = app.repository.objects(conn, tid, 'confirmed_query')[0]
            definition = spec['properties'][0]['definition']
            item = app.reviews.register(conn, tid, scientific_candidate_question(second, definition, spec))
        assert item['review_id'] == first['review_id'] and item['revision'] == first['revision'] + 1
        assert len(item['scope']['candidate_ids']) == 2
        assert item['basis']['candidate_refs'][second['candidate_id']]['content_sha256'] == content_hash(second)
        stale = ReviewAnswer(task_id=tid, review_id=first['review_id'], review_revision=first['revision'],
            basis_hash=first['basis_hash'], client_request_id=str(uuid4()), action='unable', reason='SYNTHETIC stale basis')
        with pytest.raises(DomainError, match='已变化'):
            app.reviews.answer(stale)
        valid = stale.model_copy(update={'review_revision': item['revision'], 'basis_hash': item['basis_hash'],
                                         'client_request_id': str(uuid4())})
        saved = app.reviews.answer(valid)
        assert app.reviews.answer(valid) == saved
        await run_until_wait(app, scheduler)
        final = app.view(tid)['reviews'][0]
        assert len(final['application']['results']) == 2 and final['status'] == 'unable'
    asyncio.run(run())
