"""Synthetic adversarial cases; real-source acceptance is recorded separately."""
from copy import deepcopy
import pytest

from astroquery_ai.registry.amendments import apply_amendments
from astroquery_ai.runtime.codec import content_hash
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.source_restrictions import checked_source_information
from astroquery_ai.science.insight_validation import validate_units
from astroquery_ai.science.paper_admission import matches_proposal_hash
from astroquery_ai.runtime.codec import digest


def test_resume_reconcile_runs_before_older_finalize(tmp_path):
    from astroquery_ai.runtime.repository import Repository
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('synthetic pending seal')['task_id']
    with repo.transaction() as conn:
        repo.mutate_task(conn, tid, lifecycle='queued')
        finalize = repo.enqueue(conn, tid, 'M13', 'finalize', {})
        reconcile = repo.enqueue(conn, tid, 'M13', 'reconcile', {})
    claimed = repo.claim_job('synthetic-worker')
    assert claimed['job_id'] == reconcile and claimed['job_id'] != finalize
    assert repo.claim_job('synthetic-second-worker') is None


def test_null_scope_schema_migration_cannot_hide_changed_measurements():
    original = {'raw_value': '4.57', 'local_admission': {'context': [{'text': 'synthetic', 'kind': 'method'}]}}
    updated = deepcopy(original)
    updated['local_admission']['context'][0].update(subject_scope=None, property_scope=None)
    assert matches_proposal_hash(updated, digest(original))
    updated['raw_value'] = '4.58'
    assert not matches_proposal_hash(updated, digest(original))


def test_scientific_amendment_is_version_bound_and_preserves_original():
    science = {'records': {'p': {'record_id': 'science-p', 'version': 4,
        'context_contracts': [{'key': 'time', 'meaning': 'timing identity', 'on_missing': 'block'}]}}}
    science['records']['p']['content_sha256'] = content_hash(science['records']['p'])
    original = deepcopy(science)
    amendment = {'schema_version': 'ConsumerScienceAmendment/1', 'amendment_id': 'synthetic',
        'authorized_by': 'user', 'decision_text': 'Synthetic approved unit-only rule',
        'changes': [{'property_id': 'p', 'base_science_sha256': science['records']['p']['content_sha256'],
            'context_updates': {'time': {'on_missing': 'retain_unknown_limits_strict_comparison'}}}]}
    amendment['content_sha256'] = content_hash(amendment)
    derived = apply_amendments(science, amendment)
    assert science == original and derived['records']['p']['version'] == 5
    assert derived['records']['p']['content_sha256'] != science['records']['p']['content_sha256']
    amendment['changes'][0]['base_science_sha256'] = '0' * 64
    amendment['content_sha256'] = content_hash(amendment)
    with pytest.raises(DomainError, match='原条件版本'):
        apply_amendments(science, amendment)


def test_inspected_source_information_cannot_be_replaced_with_checked_flag():
    def check(info):
        return checked_source_information(info, ['Synthetic table: source A; formal errors are underestimated.'],
            measurement_id='A', measurement_version=2, evidence_refs=[], interpretation_ref={})
    assert check({'state': 'checked', 'raw_info': [], 'caution_quotes': [], 'note': 'checked'})['state'] == 'unresolved'
    valid = check({'state': 'checked', 'raw_info': ['Synthetic table: source A'],
        'caution_quotes': ['formal errors are underestimated.'], 'note': 'source A only'})
    assert valid['state'] == 'checked' and valid['cautions'][0]['level'] == 50
    assert check({'state': 'checked', 'raw_info': ['another unseen table'], 'caution_quotes': [], 'note': 'checked'})['state'] == 'unresolved'


def test_catalog_information_ids_bind_real_readme_material_only():
    from astroquery_ai.science.source_restrictions import catalog_source_materials
    source = {'metadata': {'columns': [{'name': 'x', 'description': 'Synthetic mean quantity'}],
        'catalog_document': {'parsed': {'fields': {'x': [{'text': 'Synthetic native x [s]'}]},
            'notes': {'1': [{'text': 'Synthetic formal uncertainty is underestimated'}]}}}}}
    material = catalog_source_materials(source)
    info = {'state': 'checked', 'raw_info': ['column:x', 'readme-fields:x:0'],
        'caution_quotes': ['readme-notes:1:0'], 'note': 'synthetic'}
    checked = checked_source_information(info, material, measurement_id='m', measurement_version=1,
        evidence_refs=[], interpretation_ref={})
    assert checked['state'] == 'checked' and checked['cautions'][0]['message'] == material['readme-notes:1:0']
    info['raw_info'].append('field_descriptions.x.text')
    assert checked_source_information(info, material, measurement_id='m', measurement_version=1,
        evidence_refs=[], interpretation_ref={})['state'] == 'unresolved'


def test_citation_is_not_adoption_without_explicit_checked_result_role():
    from astroquery_ai.science.source_relationships import relationships
    record = {'measurement_id': 'm', 'property_ref': {'id': 'p'}, 'source_ref': {'id': 's'},
        'interpretation_ref': {'id': 'i', 'version': 1}, 'evidence_refs': []}
    interpretation = {'interpretation_id': 'i', 'revision': 1,
        'proposal': {'result_role': 'reported_result'}, 'paper_verification': {'state': 'passed',
            'check': {'result_role': 'reported_result', 'role_evidence': [{'quote': 'Synthetic citation only'}]}}}
    assert relationships([record], [], [], [interpretation]) == []
    interpretation['proposal']['result_role'] = 'adopted_measurement'
    interpretation['paper_verification']['check']['result_role'] = 'adopted_measurement'
    rows = relationships([record], [], [], [interpretation])
    assert rows[0]['kind'] == 'source_declared_adoption'
    assert rows[0]['adopted_result_identity'].startswith('unresolved')


def test_insight_checks_coordinate_values_and_definition_does_not_invent_theory():
    unit = {'unit_id': 'u', 'measurements': [{'measurement_id': 'm',
        'source_value': {'value': {'kind': 'real', 'value': '4.5'}, 'unit': 'ms'},
        'processed_value': {'value_typed': {'kind': 'real', 'value': '0.0045'},
            'coordinate_units': {'source': 'ms', 'target': 's'}}}], 'claims': []}
    response = {'units': [{'unit_id': 'u', 'paragraphs': [{'kind': 'source_fact', 'text': '处理后为0.0045 s。',
        'measurement_ids': ['m'], 'claim_ids': [], 'value_assertions': [{'measurement_id': 'm',
            'coordinate': 'processed', 'value': '0.0045', 'unit': 's'}]}]}]}
    assert validate_units(response, [unit])
    response['units'][0]['paragraphs'][0]['value_assertions'][0]['unit'] = 'ms'
    with pytest.raises(DomainError, match='单位'):
        validate_units(response, [unit])
    response['units'][0]['paragraphs'] = [{'kind': 'property_definition', 'text': '性质定义来自冻结定义。', 'measurement_ids': [], 'claim_ids': []}]
    with pytest.raises(DomainError, match='测量未得到解释'):
        validate_units(response, [unit])
    response['units'][0]['paragraphs'].append({'kind': 'usage_limit', 'text': '保留原文条件未知。', 'measurement_ids': ['m'], 'claim_ids': []})
    assert validate_units(response, [unit])
