"""Synthetic locator repair and complete-metadata reuse boundaries."""
from types import SimpleNamespace

from astroquery_ai.runtime.repository import Repository
from astroquery_ai.science.workflow.catalog_service import CatalogService
from astroquery_ai.science.paper_admission import (
    AdmissionCheck, Anchor, admission_protocol_issues, check_local_evidence, page_blocks, protocol_repair_instruction,
)
from tests.rebuild.test_paper_admission import paper_proposal


def test_explicit_original_unit_is_not_replaced_with_a_premature_target_coordinate():
    from astroquery_ai.science.paper_admission import preserve_literal_native_coordinate
    p = paper_proposal()
    p = p.model_copy(update={'page': 3, 'raw_value': '2.345 ms', 'unit': 's',
        'value': p.value.model_copy(update={'value': '0.002345'})})
    restored, proof = preserve_literal_native_coordinate(p, {3: 'SYNTHETIC target spin period 2.345 ms.'})
    assert restored.raw_value == p.raw_value and restored.value.value == '2.345' and restored.unit == 'ms'
    assert proof['target_value_computed'] is False and proof['previous_model_unit'] == 's'
    assert p.value.value == '0.002345' and p.unit == 's'
    # An invented literal or a case-sensitive different physical unit is not a
    # basis for rewriting the source coordinate; quantity admission is separate.
    assert preserve_literal_native_coordinate(p, {3: 'SYNTHETIC target 12.345 ms.'}) == (p, None)
    assert preserve_literal_native_coordinate(p, {3: 'SYNTHETIC target 2.345 mS.'}) == (p, None)
    correct = restored.model_copy(update={'raw_value': '2.345ms'})
    assert preserve_literal_native_coordinate(correct, {3: 'SYNTHETIC 2.345 ms.'}) == (correct, None)


def test_premature_main_conversion_keeps_each_raw_error_for_its_own_source_check():
    from astroquery_ai.science.extraction import ErrorProposal
    from astroquery_ai.science.paper_admission import preserve_literal_native_coordinate
    p = paper_proposal()
    errors = [ErrorProposal(kind='symmetric_delta', values={'delta': v}, raw_text=raw,
        location='SYNTHETIC source error', source_unit='s', interpretation_state='parsed',
        role='unspecified', meaning='reported_error', reason=None)
        for v, raw in [('0.000001', '0.001'), ('0.000002', '0.002')]]
    p = p.model_copy(update={'page': 3, 'raw_value': '2.345 ms', 'unit': 's', 'errors': errors,
        'value': p.value.model_copy(update={'value': '0.002345'})})
    restored, proof = preserve_literal_native_coordinate(p, {3: 'SYNTHETIC 2.345 ms.'})
    assert [e.raw_text for e in restored.errors] == ['0.001', '0.002']
    assert all(e.interpretation_state == 'unresolved' and e.values is None for e in restored.errors)
    assert [e.values for e in p.errors] == [{'delta': '0.000001'}, {'delta': '0.000002'}]
    assert proof['uncertainty_raw_preserved_for_separate_check']


def test_value_subject_and_adoption_role_can_have_different_actual_pages():
    pages = {1: 'SYNTHETIC Table 2 uses the previously measured catalogue values.',
             3: 'Table 2. J1234+5678 DM 26.74870(7).'}
    role = {'page': 1, 'quote': pages[1]}
    local = {'page': 3, 'quote': pages[3]}
    check = AdmissionCheck.model_validate(dict(index=0, subject='target', printed_subject='J1234+5678',
        subject_evidence=[local], role_evidence=[role], result_role='adopted_measurement',
        quantity_match='exact', quantity_evidence=[local], reason='Synthetic adopted table.',
        subject_link={'method': 'evidenced_alias', 'relation': 'target', 'local_evidence': [local],
                      'scope_evidence': [local, role], 'reason': 'Known ID omits PSR display prefix.'}))
    result = check_local_evidence(paper_proposal(), check, {'main_id': 'PSR J1234+5678', 'aliases': []}, pages, {},
                                 require_quantity=True)
    assert result['state'] == 'passed'
    assert result['check']['role_evidence'][0]['page'] == 1
    # The quantity definition may be in a different header block. The actual
    # number remains verifiable in the declared local subject/value anchor.
    pages[1] += ' DM is the catalogue dispersion measure in pc cm^-3.'
    header = {'page': 1, 'quote': pages[1]}
    separate = check.model_copy(update={'quantity_evidence': [Anchor.model_validate(header)]})
    assert check_local_evidence(paper_proposal(), separate,
        {'main_id': 'PSR J1234+5678', 'aliases': []}, pages, {}, image_pages=set(),
        require_quantity=True)['state'] == 'passed'


def test_paper_candidate_is_available_to_source_owner_before_quality_runs(tmp_path):
    from astroquery_ai.science.workflow.context import ScienceContext
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC extraction stage')['task_id']
    context = object.__new__(ScienceContext)
    context.repo = repo
    with repo.transaction() as conn:
        jid = repo.enqueue(conn, tid, 'M06', 'paper_batch', {'work_id': 'synthetic-paper'})
        result = {'state': 'review_candidate', 'reason': 'local_subject_or_result_evidence_unresolved',
            'proposal': {'raw_value': 'synthetic'}, 'assembly_context': {'owner': 'M06', 'batch_id': jid,
                'source': {'source_id': 'synthetic-paper'}}}
        context.commit_candidates(conn, tid, [result], jid)
    with repo.read() as conn:
        pending = repo.objects(conn, tid, 'candidate_pre_review_pending')
        assert len(pending) == 1 and pending[0]['source_id'] == 'synthetic-paper'
        assert not conn.execute('SELECT 1 FROM reviews WHERE task_id=?', (tid,)).fetchone()
        assert not conn.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind='assess_batch' AND status='succeeded'", (tid,)).fetchone()


def test_bad_subject_locator_is_technical_repair_with_literal_navigation():
    pages = {1: 'SYNTHETIC PSR B0329+54. Table 2 describes this observation.',
             3: 'Table 2 continued. Fitted DM 26.74870(7).'}
    blocks = page_blocks(pages)
    local = {'page': 3, 'block_ids': [blocks[1]['block_id']]}
    check = AdmissionCheck.model_validate(dict(index=0, subject='target', printed_subject='PSR B0329+54',
        subject_evidence=[local], role_evidence=[local], result_role='reported_result',
        quantity_match='exact', quantity_evidence=[local], reason='Synthetic fitted result.'))
    p = paper_proposal()
    target = {'main_id': 'PSR B0329+54', 'aliases': []}
    problems = admission_protocol_issues(p, check, target, pages, blocks)
    assert problems == ['subject_locator_does_not_establish_local_to_named_scope_link']
    prompt = protocol_repair_instruction({'target': target, 'properties': []}, [p], [check], [problems], pages, blocks)
    inventory = prompt['literal_name_navigation']
    assert inventory[0]['actual_blocks'] == [{'page': 1, 'block_id': blocks[0]['block_id']}]
    assert 'previous_checks' not in prompt
    assert prompt['saved_pages'] == blocks
    ambiguous = check.model_copy(update={'subject': 'unresolved'})
    assert admission_protocol_issues(p, ambiguous, target, pages, blocks) == []


def test_schema_reuse_requires_saved_complete_metadata_and_owned_concrete_table(tmp_path):
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC metadata reuse')['task_id']
    artifact = {'artifact_id': 'synthetic-metadata'}
    path = tmp_path / 'metadata.xml'
    path.write_text('<VOTABLE><RESOURCE name="SYNTHETIC"><TABLE name="SYNTHETIC/refs">'
        '<FIELD name="Ref" datatype="char"><DESCRIPTION>Reference code</DESCRIPTION></FIELD>'
        '</TABLE></RESOURCE></VOTABLE>')
    owned = []

    def read_owned(task_id, aid):
        owned.append((task_id, aid))
        return artifact, path

    service = object.__new__(CatalogService)
    service.repo = repo
    service.app = SimpleNamespace(artifacts=SimpleNamespace(read_owned=read_owned))
    payload = {'table_id': 'SYNTHETIC/refs', 'discovery_artifact': artifact}
    with repo.transaction() as conn:
        repo.put_object(conn, tid, 'catalog_response', 'search', 1,
            {'artifact': artifact, 'expression': 'keyword-search', 'coverage_state': 'complete_for_expression'})
    assert service.discovered_schema(tid, payload) is None
    assert not owned
    with repo.transaction() as conn:
        repo.put_object(conn, tid, 'catalog_response', 'complete', 1,
            {'artifact': artifact, 'expression': 'catalog-metadata:SYNTHETIC',
             'coverage_state': 'complete_for_expression', 'metadata': {'status': 200}})
    schema, raw, metadata = service.discovered_schema(tid, payload)
    assert raw == path.read_bytes()
    assert schema['resources'][0]['tables'][0]['columns'][0]['name'] == 'Ref'
    assert metadata['schema_reused_from_discovery_artifact'] == artifact['artifact_id']
    assert owned == [(tid, artifact['artifact_id'])]
    assert service.discovered_schema(tid, {**payload, 'table_id': 'SYNTHETIC/absent'}) is None
