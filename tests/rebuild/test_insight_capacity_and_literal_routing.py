"""Regressions from the real HD 63433 run; no live provider calls."""
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from astroquery_ai.runtime.calls import ModelProfile, json_input_capacity
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.profiles import ProfileAuthority
from astroquery_ai.science import material_summaries as summaries, property_insights as cards
from astroquery_ai.science.measurements.assembly import EvidenceExtractor


def test_literal_routing_annotation_never_breaks_reextraction_or_grants_admission():
    from tests.rebuild.test_catalog_transcription import proposal
    p = proposal()
    spec = {'properties': [{'property_id': p.property_id, 'definition': {}}],
            'run_policy': {'workflow_contract': 'backend-consolidation/1'}}
    result = EvidenceExtractor(None).assemble(spec=spec,
        source={'source_id': 'synthetic', 'kind': 'catalog', 'table_id': 't'},
        artifact={'artifact_id': 'a', 'sha256': 'sha'}, proposal=p, owner='M03', batch_id='local',
        allowed_pages=[], matched_rows=[0], literal_transcription={'scientific_admission_granted': True})
    assert result['state'] == 'review_candidate' and result['reason'] == 'pending_unified_quality'
    assert result['proposal']['raw_value'] == p.raw_value
    assert 'literal_transcription' not in result['assembly_context']


def test_property_generation_fits_the_existing_validated_execution_contract(monkeypatch):
    # These independent limits mirror the persisted product M11 qualification;
    # the failure was requested output=8192 against validated output=4096.
    execution = {'model': 'qwen3.8-max', 'version': 'research-property-short-2', 'thinking': False,
        'high_resolution_images': False, 'operations': ['insights'], 'source_formats': ['science_snapshot'],
        'maximum_input_tokens': 256000, 'maximum_output_tokens': 4096, 'maximum_images': 0,
        'maximum_wall_seconds': 240, 'maximum_inactivity_seconds': 90}
    report = {'schema_version': 'ScientificProfileQualification/2', 'execution_profiles': [execution]}

    class BoundsPassed(Exception):
        pass

    @contextmanager
    def read():
        yield None

    def task(*args):
        raise BoundsPassed()

    authority = ProfileAuthority(SimpleNamespace(repository=SimpleNamespace(read=read, task=task)))
    monkeypatch.setattr(authority, 'load', lambda *a: (report, {}))
    profile = ModelProfile(model='qwen3.8-max', version=cards.PROTOCOL, thinking=False,
        operation='insights', source_format='science_snapshot', max_images=0,
        max_input_tokens=cards.INPUT_LIMIT, max_output_tokens=cards.OUTPUT_LIMIT,
        wall_seconds=240, inactivity_seconds=90)
    with pytest.raises(BoundsPassed):
        authority.authorize('synthetic', 'M11', profile, 50000)
    with pytest.raises(DomainError) as error:
        authority.authorize('synthetic', 'M11', replace(profile, max_output_tokens=8192), 50000)
    assert error.value.code == 'PROFILE_CAPABILITY_EXCEEDED'


@pytest.mark.parametrize('chars,expected', [(22000, 1), (55000, 2), (100000, 2)])
def test_complete_summary_background_is_planned_without_truncation(chars, expected):
    class Inputs:
        knowledge_context_ref = {'id': 'frozen-context'}

        def pack(self, group, pids):
            return {'properties': [{'label': f'P{i}', 'property_id': pid, 'background': 'x' * chars,
                'conditions': ['ONLY the original applicable regime'], 'authoring_basis': 'author_knowledge'}
                for i, pid in enumerate(pids, 1)]}, {f'P{i}': {'property_id': pid} for i, pid in enumerate(pids, 1)}

    plans = summaries.summary_batches(Inputs(), {}, ['one', 'two'])
    assert len(plans) == expected
    properties = [p for body, _ in plans for p in body['properties']]
    assert [p['property_id'] for p in properties] == ['one', 'two']
    assert all(p['background'] == 'x' * chars and p['conditions'] == ['ONLY the original applicable regime'] for p in properties)
    for body, bindings in plans:
        assert set(bindings) == {p['label'] for p in body['properties']}
        capacity = json_input_capacity([{'role': 'system', 'content': summaries.PROMPT + summaries.BUNDLE_KNOWLEDGE_RULE},
            {'role': 'user', 'content': canonical(body).decode()}], summaries.PROFILE)
        assert capacity['fits'] is (chars < 100000)
