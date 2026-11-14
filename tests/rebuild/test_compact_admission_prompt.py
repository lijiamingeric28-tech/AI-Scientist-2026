from copy import deepcopy

from astroquery_ai.science.paper_admission import verification_instruction, page_blocks, complete_native_evidence
from tests.rebuild.test_paper_admission import paper_proposal


def test_compact_verifier_keeps_source_and_scientific_boundaries_but_hides_primary_judgment():
    proposal = paper_proposal().model_copy(update={'page': 3, 'subject_role': 'target', 'result_role': 'reported_result'})
    spec = {'target': {'main_id': 'PSR B0329+54', 'aliases': ['PSR J0332+5434']},
        'properties': [{'property_id': proposal.property_id,
            'definition': {'description': 'SYNTHETIC exact quantity', 'definition_qualifiers': ['SYNTHETIC source-reported total'],
                           'measurement_conditions_schema': {'required': ['SYNTHETIC aperture']}},
            'output_profile': {'unit': {'canonical_symbol': 'm'}, 'representation': {'kind': 'linear'}},
            'dependency_refs': [{'id': 'SYNTHETIC audit-only metadata'}]}]}
    before = deepcopy(spec)
    pages = {3: 'SYNTHETIC B0329+54 whole length and separate error; not a trial bound.'}
    blocks = page_blocks(pages)
    prompt = verification_instruction(spec, [proposal], pages, visible_blocks=blocks, compact=True)
    assert prompt['saved_pages'] == blocks and spec == before
    assert prompt['properties'][0]['definition'] == spec['properties'][0]['definition']
    assert 'subject_role' not in prompt['candidates'][0] and 'result_role' not in prompt['candidates'][0]
    assert 'source_quote' not in prompt['candidates'][0]
    assert prompt['candidates'][0]['raw_value'] == proposal.raw_value
    assert prompt['schema']['$defs']['Anchor']['properties']['quote']['type'] == 'null'


def test_incomplete_transcript_does_not_force_an_image_only_anchor_to_be_a_fake_block_id():
    proposal = paper_proposal().model_copy(update={'page': 3})
    spec = {'target': {'main_id': 'SYNTHETIC', 'aliases': []}, 'properties': []}
    prompt = verification_instruction(spec, [proposal], {3: ''}, visible_blocks=[], compact=True)
    assert prompt['schema']['$defs']['Anchor']['properties']['quote'].get('type') != 'null'


def test_native_only_check_requires_every_actual_block_on_each_candidate_page():
    pages = {1: '\n'.join('SYNTHETIC source line ' + str(i) for i in range(50)), 2: ''}
    blocks = page_blocks({1: pages[1]})
    assert complete_native_evidence(pages, blocks, {1})
    assert not complete_native_evidence(pages, blocks[:-1], {1})
    assert not complete_native_evidence(pages, blocks, {1, 2})
    assert not complete_native_evidence(pages, blocks, {3})
