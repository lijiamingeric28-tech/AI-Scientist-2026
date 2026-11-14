"""Regression of the approved final four fixes; synthetic data is not science evidence."""
import asyncio
from copy import deepcopy
import csv
import io
import json

from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.reviews import presented_review
from astroquery_ai.runtime.run_policy import sweep_ready
from astroquery_ai.science.papers.reconciliation import reviewed_native_fields
from astroquery_ai.science.source_review import SourceItemCheck
from tests.rebuild.test_scientific_review_gate import check_data
from tests.rebuild.test_paper_admission import paper_proposal


def test_native_coordinate_uses_quantity_identity_anchors_without_computing():
    pages, anchors, raw = check_data()
    raw.update(quantity_evidence=[], quantity_identity={
        'reported_quantity': 'SYNTHETIC logarithmic index', 'subject_scale': 'whole target',
        'native_representation': 'source log10 coordinate', 'relation': 'same', 'evidence': anchors})
    item = SourceItemCheck.model_validate({'item_id': 'I1', 'assessment': raw,
        'native_representation': 'log10', 'value_match': 'exact', 'errors_match': 'exact'})
    original = paper_proposal()
    before = original.model_dump(mode='json')
    corrected = reviewed_native_fields(original, item)
    assert corrected.representation == 'log10'
    assert corrected.raw_value == original.raw_value and corrected.value == original.value
    assert corrected.errors == original.errors and original.model_dump(mode='json') == before
    # Neither a unit label nor the requested coordinate can fill missing evidence.
    ungrounded = item.model_copy(update={'assessment': item.assessment.model_copy(
        update={'quantity_identity': None, 'quantity_evidence': [], 'native_unit': 'dex'})})
    assert reviewed_native_fields(original, ungrounded).representation == original.representation


def test_quantity_coordinate_and_copy_coordinate_cannot_disagree():
    import pytest
    from pydantic import ValidationError
    _, anchors, raw = check_data()
    raw['quantity_identity'] = {'reported_quantity': 'SYNTHETIC logarithmic index',
        'subject_scale': 'whole target', 'native_representation': 'source log10 index',
        'native_coordinate_kind': 'log10', 'relation': 'same', 'evidence': anchors}
    with pytest.raises(ValidationError, match='contradicts'):
        SourceItemCheck.model_validate({'item_id':'I1','assessment':raw,
            'native_representation':'linear','value_match':'exact','errors_match':'exact'})
    same=SourceItemCheck.model_validate({'item_id':'I1','assessment':raw,
        'native_representation':'log10','value_match':'exact','errors_match':'exact'})
    assert same.native_representation=='log10'
    from astroquery_ai.science.unified_quality import paper_item_wire
    original={'assessment':raw,'item_id':'I1','value_match':'exact','errors_match':'exact'}
    bound=paper_item_wire(original,0)
    assert bound['native_representation']=='log10' and 'native_representation' not in original


def test_review_action_meaning_is_never_model_button_prose():
    old = {'allowed_actions': ['not_supported', 'unable'], 'issue_kind': 'unit_semantics',
        'choices': [{'action': 'not_supported', 'label': 'Assume parsecs based on context',
                     'impact': 'This misleading label used to submit rejection.'},
                    {'action': 'unable', 'label': 'Unknown', 'impact': 'Unknown'}]}
    before = deepcopy(old)
    shown = presented_review(old)
    assert old == before and shown['allowed_actions'] == old['allowed_actions']
    assert shown['choices'][0]['label'] == '原件不支持当前解释'
    assert shown['choices'][1]['label'] == '无法判断，保留未决'
    assert shown['proposed_choices'] == old['choices']
    assert 'confirm' not in [c['action'] for c in shown['choices']]
    assert presented_review(shown) == shown


def test_idle_catalog_sweep_does_not_scan_historical_objects(tmp_path):
    repo = Repository(tmp_path/'db')
    tid = repo.create_task('SYNTHETIC completed history')['task_id']
    with repo.transaction() as c:
        repo.mutate_task(c, tid, lifecycle='completed', science_state='sealed')
        for n in range(3000):
            repo.put_object(c, tid, 'catalog_window' if n == 0 else 'historical', str(n), 1,
                            {'synthetic': True, 'n': n})
        steps = []
        def tick():
            steps.append(1)
            return len(steps) > 20
        c.set_progress_handler(tick, 100)
        try:
            assert sweep_ready(repo, c) == set()
        finally:
            c.set_progress_handler(None, 0)
        # Progress budget measures SQLite work, not noisy wall-clock timing.
        assert len(steps) <= 20


def test_citation_background_survives_production_seal_and_all_export_views(tmp_path):
    from tests.rebuild.scenario import application, confirmed_case
    from astroquery_ai.science.results.exporting import _serialize
    from astroquery_ai.science.insight_inputs import build_units, explanation_prompt
    async def run():
        app = application(tmp_path/'data')
        def setup(scheduler):
            original = scheduler.handlers['finalize']
            async def seed_existing_bibliography(job):
                with app.repository.transaction() as c:
                    record = app.repository.objects(c, job['task_id'], 'measurement')[0]
                    for n, abstract in enumerate(('SYNTHETIC background; not a new measurement.', None)):
                        app.repository.put_object(c, job['task_id'], 'cited_work', f'cited-{n}', 1,
                            {'cited_work_id': f'cited-{n}', 'title': [f'SYNTHETIC reference {n}'],
                             'abstract': abstract, 'abstract_state': 'available' if abstract else 'not_available'})
                        app.repository.put_object(c, job['task_id'], 'reported_source_ref', f'ref-{n}', 1,
                            {'reference_id': f'ref-{n}', 'measurement_id': record['measurement_id'],
                             'cited_work_id': f'cited-{n}', 'raw_code': f'[{n}]', 'role': 'background',
                             'link_quote': 'SYNTHETIC explicit source reference', 'link_state': 'reported',
                             'evidence_refs': record['evidence_refs']})
                    app.repository.put_object(c, job['task_id'], 'citation_lookup', 'lookup', 1,
                                              {'lookup_id': 'lookup', 'state': 'checked', 'depth': 1})
                return await original(job)
            scheduler.handlers['finalize'] = seed_existing_bibliography
        state, _ = await confirmed_case(app, setup_scheduler=setup)
        with app.repository.read() as c:
            body = app.delivery.get(c, state['task_id'])
            spec = app.repository.objects(c, state['task_id'], 'confirmed_query')[0]
        bundle = body['provenance_bundle']
        assert len(bundle['cited_works']) == 2 and len(bundle['citation_lookups']) == 1
        assert sum(bool(x['abstract']) for x in bundle['cited_works']) == 1
        assert len(body['measurements']) == 1
        units = build_units(body, spec, [], None)
        prompt = explanation_prompt(units, body, spec)
        assert len(prompt['citation_background']) == 2
        assert len(prompt['units'][0]['measurements']) == 1
        wide = json.loads(_serialize(body, 'json_wide')[0])
        assert 'SYNTHETIC background; not a new measurement.' in json.dumps(wide)
        for fmt in ('csv_long', 'csv_wide'):
            rows = list(csv.DictReader(io.StringIO(_serialize(body, fmt)[0].decode('utf-8-sig'))))
            assert len(json.loads(rows[0]['cited_works_json'])) == 2
            assert json.loads(rows[0]['citation_lookups_json'])[0]['depth'] == 1
        with app.repository.read() as c:
            assert digest(body['measurements']) == digest(app.delivery.get(c, state['task_id'])['measurements'])
    asyncio.run(run())
