"""Counterexamples observed in the first real run, and explicit synthetic controls."""
from astroquery_ai.runtime.codec import digest
from astroquery_ai.science.extraction import MeasurementProposal
from astroquery_ai.science.paper_admission import (
    AdmissionCheck, check_local_evidence, preserve_parenthetical_errors,
)
from tests.rebuild.test_catalog_transcription import proposal


def paper_proposal(raw="26.74870(7)", delta="0.0007"):
    base = proposal().model_dump(mode="json")
    base.update(page=3, row=None, column=None, location_kind="caption", raw_value=raw,
                value={"kind": "real", "value": "26.74870"},
                errors=[dict(location="brackets", raw_text=raw, kind="symmetric_delta",
                             values={"delta": delta}, role="unspecified", meaning="unspecified",
                             interpretation_state="parsed", reason=None)])
    return MeasurementProposal.model_validate(base)


def test_intrinsic_count_needs_quantity_evidence_and_never_fills_an_unknown_physical_unit():
    target={'main_id':'SYNTHETIC group','aliases':[]}
    text='SYNTHETIC group: reported number of selected members = 37 members.'
    data=paper_proposal().model_dump(mode='json')
    data.update(raw_value='37',value={'kind':'integer','value':'37'},errors=[],unit=None,location_kind='body')
    p=MeasurementProposal.model_validate(data)
    anchor={'page':3,'quote':text}
    c=AdmissionCheck.model_validate({'index':0,'subject':'target','printed_subject':target['main_id'],
        'subject_evidence':[anchor],'result_role':'reported_result','role_evidence':[anchor],
        'quantity_match':'exact','quantity_evidence':[anchor],'reason':'SYNTHETIC grounded count',
        'unit_match':'not_applicable','native_unit':None,'unit_evidence':[]})
    count={'output_profile':{'unit':{'kind':'dimensionless','semantic_kind':'count'}}}
    result=check_local_evidence(p,c,target,{3:text},{},require_quantity=True,require_units=True,property_binding=count)
    assert result['state']=='passed' and result['intrinsic_count_coordinate']['native_unit_literal'] is None,result
    ratio={'output_profile':{'unit':{'kind':'dimensionless','semantic_kind':'ratio'}}}
    assert check_local_evidence(p,c,target,{3:text},{},require_quantity=True,require_units=True,property_binding=ratio)['state']=='unresolved'


def test_integer_to_real_server_decoding_keeps_exact_original_admission_binding(tmp_path):
    from tests.rebuild.registry_fixture import make_release
    from tests.rebuild.factories import ref
    from astroquery_ai.science.extraction import EvidenceExtractor
    definition=make_release(tmp_path/'synthetic-registry')['definitions'][0]
    data=paper_proposal().model_dump(mode='json')
    data.update(property_id=definition['property_id'],raw_value='37',value={'kind':'integer','value':'37'},
                unit='m',errors=[],conditions=[],location_kind='body')
    p=MeasurementProposal.model_validate(data)
    spec={'task_id':'SYNTHETIC task','spec_id':'SYNTHETIC spec','target':{'target_id':'SYNTHETIC target'},
        'properties':[{'property_id':definition['property_id'],'definition':definition}]}
    source={'source_id':'SYNTHETIC paper','kind':'paper','qualification_ref':ref()}
    artifact={'artifact_id':'SYNTHETIC artifact','sha256':ref()['content_sha256']}
    verified={'state':'passed','reason':'SYNTHETIC exact source check','proposal_hash':digest(p.model_dump(mode='json')),
              'context':[],'check':None}
    result=EvidenceExtractor(None).assemble(spec=spec,source=source,artifact=artifact,proposal=p,owner='M06',
        batch_id='SYNTHETIC batch',allowed_pages=[3],paper_verification=verified)
    assert result['state']=='admitted',result.get('reason')
    assert result['measurement']['value']=={'kind':'real','value':'37'}
    assert result['measurement']['raw_value']=='37'
    data['value']['value']='38';changed=MeasurementProposal.model_validate(data)
    rejected=EvidenceExtractor(None).assemble(spec=spec,source=source,artifact=artifact,proposal=changed,owner='M06',
        batch_id='SYNTHETIC batch',allowed_pages=[3],paper_verification=verified)
    assert rejected['state']!='admitted'


def test_native_numeric_conflict_detects_premature_units_and_reciprocal_without_computing():
    from astroquery_ai.science.paper_admission import native_numeric_conflict
    data = paper_proposal('16.05').model_dump(mode='json')
    data['value'] = {'kind': 'real', 'value': '0.01605'}
    p = MeasurementProposal.model_validate(data)
    assert native_numeric_conflict(p)['source_numeric_literal'] == '16.05'
    f = p.model_copy(update={'raw_value': '62.29588783082522(9)'})
    assert native_numeric_conflict(f)['reason'] == 'native_numeric_coordinate_changed'
    for raw in ('0.016050', '0.01605(2)', '0.01605 s', '0.01605 ± 0.00002'):
        assert native_numeric_conflict(p.model_copy(update={'raw_value': raw})) is None
    # Nonlinear and nontrivial textual encodings need their own interpretation.
    assert native_numeric_conflict(p.model_copy(update={'representation': 'log10'})) is not None
    assert native_numeric_conflict(p.model_copy(update={'raw_value': '1.605 × 10^-2'})) is None


def test_figure_boundary_uses_visual_admission_despite_complete_native_text():
    from astroquery_ai.science.paper_admission import requires_visual_admission
    p = paper_proposal()
    assert requires_visual_admission(p)
    assert requires_visual_admission(p.model_copy(update={'location_kind': 'body', 'column': 'Figure 2 Header'}))
    assert not requires_visual_admission(p.model_copy(update={'location_kind': 'body', 'column': None}))


def test_independent_plot_location_rejects_even_a_genuine_reported_target_measurement():
    p = paper_proposal()
    target = {'main_id': 'PSR J2145-0750', 'aliases': []}
    anchor = {'page': 3, 'quote': 'SYNTHETIC figure title: PSR J2145-0750 DM 26.74870(7)'}
    raw = {'index': 0, 'subject': 'target', 'printed_subject': target['main_id'],
           'subject_evidence': [anchor], 'result_role': 'reported_result', 'role_evidence': [anchor],
           'quantity_match': 'exact', 'quantity_evidence': [anchor], 'value_location_kind': 'plot',
           'reason': 'SYNTHETIC independent layout judgment'}
    checked = check_local_evidence(p, AdmissionCheck.model_validate(raw), target, {3: anchor['quote']}, {}, require_quantity=True)
    assert checked['state'] == 'rejected' and checked['reason'] == 'value_only_reported_inside_figure'
    raw.pop('value_location_kind')
    assert 'value_location_kind' not in AdmissionCheck.model_validate(raw).model_dump(mode='json')


def test_coordinate_name_minus_typography_is_not_a_cross_id_or_component_match():
    from astroquery_ai.science.catalogs import exact_identifier, identifier_typography
    target = {'main_id': 'PSR J1234-5678', 'aliases': []}
    text = 'SYNTHETIC Table: pulsar J1234−5678 DM 26.74870(7).'
    anchor = {'page': 3, 'quote': text}
    data = dict(index=0, subject='target', printed_subject='J1234−5678',
        subject_evidence=[anchor], role_evidence=[anchor], result_role='reported_result',
        quantity_match='exact', quantity_evidence=[anchor], reason='Synthetic native table.')
    p = paper_proposal()
    result = check_local_evidence(p, AdmissionCheck.model_validate(data), target, {3: text}, {}, require_quantity=True)
    assert result['state'] == 'passed'
    assert result['check']['printed_subject'] == 'J1234−5678'
    assert exact_identifier('PSR J1234−5678') == exact_identifier('PSR J1234-5678')
    assert exact_identifier('PSR J1234−5678A') != exact_identifier('PSR J1234-5678')
    assert exact_identifier('PSR B1234−5678') != exact_identifier('PSR J1234-5678')
    assert identifier_typography('flux −0.2 or object NGC−1234') == 'flux −0.2 or object NGC−1234'
    data['printed_subject'] = 'J1234−5678A'
    assert check_local_evidence(p, AdmissionCheck.model_validate(data), target, {3: text}, {}, require_quantity=True)['state'] != 'passed'


def test_only_an_explicit_source_footnote_can_annotate_an_exact_verified_table_identifier():
    from astroquery_ai.science.paper_admission import page_blocks
    target = {'main_id': 'PSR B0329+54', 'aliases': []}
    p = paper_proposal().model_copy(update={'page': 4, 'location_kind': 'table'})
    for printed, declaration, expected in [
        ('B0329+54*', 'Pulsars labeled with * were detected.', 'passed'),
        ('B0329+54*', 'No annotation declaration here.', 'unresolved'),
        ('B0329+54A*', 'Pulsars labeled with * were detected.', 'unresolved'),
        ('B0823+26*', 'Pulsars labeled with * were detected.', 'unresolved'),
    ]:
        text = f'SYNTHETIC table. {declaration}\nName DM\n{printed} 26.74870(7)'
        block = page_blocks({4: text})[0]['block_id']
        anchor = {'page': 4, 'block_ids': [block]}
        check = AdmissionCheck.model_validate({'index': 0, 'subject': 'target', 'printed_subject': printed,
            'subject_evidence': [anchor], 'result_role': 'reported_result', 'role_evidence': [anchor],
            'quantity_match': 'exact', 'quantity_evidence': [anchor], 'reason': 'SYNTHETIC literal table.'})
        result = check_local_evidence(p, check, target, {4: text}, {}, require_quantity=True)
        assert result['state'] == expected
        assert check.printed_subject == printed
        if expected == 'passed':
            assert result['subject_annotation']['marker'] == '*'
            assert any('labeled with *' in item['text'] for item in result['context'])


def test_actual_tenfold_parentheses_failure_keeps_main_and_raw_unresolved():
    original = paper_proposal()
    checked = preserve_parenthetical_errors(original)
    assert checked.value == original.value and checked.raw_value == original.raw_value
    assert checked.errors[0].raw_text == original.errors[0].raw_text
    assert checked.errors[0].values is None and checked.errors[0].interpretation_state == "unresolved"
    assert original.errors[0].values == {"delta": "0.0007"}
    valid = preserve_parenthetical_errors(paper_proposal(delta="0.00007"))
    assert valid.errors[0].values == {"delta": "0.00007"}
    assert valid.errors[0].role == "unspecified" and valid.errors[0].level_kind is None


def test_other_local_object_not_authorized_by_paper_mention_of_target():
    p = paper_proposal()
    page = "SYNTHETIC control: PSR B0329+54 and FRB 20180916B. Initial trial DM for FRB 20180916B is 348.82."
    check = AdmissionCheck.model_validate(dict(index=0, subject="other", printed_subject="FRB 20180916B",
        subject_evidence=[dict(page=3, quote="Initial trial DM for FRB 20180916B is 348.82.")],
        result_role="assumption", role_evidence=[dict(page=3, quote="Initial trial DM")], context=[], reason="Different local object."))
    result = check_local_evidence(p, check, {"main_id": "PSR B0329+54", "aliases": []}, {3: page}, {"attempt_id": "synthetic"})
    assert result["state"] == "rejected"
    assert result["proposal_hash"] == digest(p.model_dump(mode="json"))
    # A confident target enum with fabricated subject evidence still cannot pass.
    check = AdmissionCheck.model_validate({**check.model_dump(), "subject": "target", "printed_subject": "PSR B0329+54",
                                    "subject_evidence": [dict(page=3, quote="made up text")]})
    # Fabricated identity cannot authorize entry; the real source still
    # positively identifies this number as a trial input, so no human is needed.
    assert check_local_evidence(p, check, {"main_id": "PSR B0329+54", "aliases": []}, {3: page}, {})["state"] == "rejected"


def test_source_target_result_context_survives_and_foreign_page_is_not_authorized():
    page = "SYNTHETIC PSR B0329+54. Table 2 best-fit DM: 26.74870(7). Method: midpoint."
    raw = dict(index=0, subject="target", printed_subject="PSR B0329+54",
               subject_evidence=[dict(page=4, quote="PSR B0329+54")], result_role="reported_result",
               role_evidence=[dict(page=4, quote="Table 2 best-fit DM: 26.74870(7).")],
               context=[dict(kind="fiducial", text="midpoint", anchor=dict(page=4, quote="Method: midpoint."))], reason="Local table result.")
    target = {"main_id": "PSR B0329+54", "aliases": []}
    result = check_local_evidence(paper_proposal().model_copy(update={'page': 4}), AdmissionCheck.model_validate(raw), target, {4: page}, {})
    assert result["state"] == "passed" and result["context"][0]["text"] == "midpoint"
    assert check_local_evidence(paper_proposal(), AdmissionCheck.model_validate(raw), target, {3: page}, {})["state"] == "unresolved"


def test_indexed_evidence_is_copied_by_server_and_invented_ids_fail():
    from astroquery_ai.science.paper_admission import page_blocks
    page = "SYNTHETIC PSR B0329+54 best-fit DM 26.74870(7), midpoint method."
    block = page_blocks({4: page})[0]["block_id"]
    raw = dict(index=0, subject="target", printed_subject="PSR B0329+54",
               subject_evidence=[dict(page=4, block_ids=[block])], result_role="reported_result",
               role_evidence=[dict(page=4, block_ids=[block])], context=[], reason="Source block.")
    target = {"main_id": "PSR B0329+54", "aliases": []}
    result = check_local_evidence(paper_proposal().model_copy(update={'page': 4}), AdmissionCheck.model_validate(raw), target, {4: page}, {})
    assert result["state"] == "passed" and result["check"]["role_evidence"][0]["quote"] == page
    raw["role_evidence"][0]["block_ids"] = ["invented"]
    assert check_local_evidence(paper_proposal(), AdmissionCheck.model_validate(raw), target, {4: page}, {})["state"] == "unresolved"


def test_remote_target_mention_is_not_a_local_subject_link():
    pages = {1: 'SYNTHETIC study of OTHER OBJECT.',
             6: 'For this object the fitted DM is 26.74870(7).',
             10: 'Comparison: PSR B0329+54 has a published mass.'}
    p = paper_proposal().model_copy(update={'page': 6})
    check = AdmissionCheck.model_validate(dict(index=0, subject='target', printed_subject='PSR B0329+54',
        subject_evidence=[{'page': 6, 'quote': pages[6]}, {'page': 10, 'quote': pages[10]}],
        result_role='reported_result', role_evidence=[{'page': 6, 'quote': pages[6]}], reason='SYNTHETIC old false binding.'))
    result = check_local_evidence(p, check, {'main_id': 'PSR B0329+54', 'aliases': []}, pages,
                                  {'operation': 'paper_admission'})
    assert result['state'] == 'unresolved'
    assert 'identity_context' not in result
    foreign = check.model_copy(update={'subject': 'other', 'printed_subject': None,
        'subject_link': __import__('astroquery_ai.science.paper_admission', fromlist=['SubjectLink']).SubjectLink.model_validate({
            'method': 'section_scope', 'relation': 'other', 'local_evidence': [{'page': 6, 'quote': pages[6]}],
            'scope_evidence': [{'page': 1, 'quote': pages[1]}], 'reason': 'SYNTHETIC foreign section.'})})
    assert check_local_evidence(p, foreign, {'main_id': 'PSR B0329+54', 'aliases': []}, pages, {})['state'] == 'rejected'


def test_cross_page_scope_has_real_local_and_governing_evidence():
    pages = {1: 'SYNTHETIC PSR B0329+54 timing study; Table 2 reports its fits.',
             6: 'Table 2 continued. Fitted DM is 26.74870(7).'}
    p = paper_proposal().model_copy(update={'page': 6})
    local, scope = {'page': 6, 'quote': pages[6]}, {'page': 1, 'quote': pages[1]}
    check = AdmissionCheck.model_validate(dict(index=0, subject='target', printed_subject='PSR B0329+54',
        subject_evidence=[scope], result_role='reported_result', role_evidence=[local], reason='SYNTHETIC scoped table.',
        subject_link={'method': 'cross_page_scope', 'relation': 'target',
                      'local_evidence': [local], 'scope_evidence': [scope],
                      'reason': 'Continued table and explicitly stated table subject.'}))
    result = check_local_evidence(p, check, {'main_id': 'PSR B0329+54', 'aliases': []}, pages, {})
    assert result['state'] == 'passed' and result['subject_binding'] == 'evidenced_semantic_scope'
    bad = check.model_copy(update={'subject_link': check.subject_link.model_copy(update={'local_evidence': [check.subject_evidence[0]]})})
    assert check_local_evidence(p, bad, {'main_id': 'PSR B0329+54', 'aliases': []}, pages, {})['state'] == 'unresolved'


def test_literal_pulsar_header_can_supply_namespace_but_not_wrong_row():
    page = 'SYNTHETIC Table 1. PSR J  PSR B  DM\n0332+5434 0329+54 26.74870(7)\n0826+2637 0823+26 19.45'
    raw = dict(index=0, subject='target', printed_subject='0329+54',
               subject_evidence=[dict(page=3, quote=page)], result_role='adopted_measurement',
               role_evidence=[dict(page=3, quote=page)], reason='Header namespace.',
               quantity_match='exact', quantity_evidence=[dict(page=3, quote=page)])
    target = {'main_id': 'PSR B0329+54', 'aliases': []}
    checked = check_local_evidence(paper_proposal(), AdmissionCheck.model_validate(raw), target, {3: page}, {}, require_quantity=True)
    assert checked['state'] == 'passed' and checked['subject_namespace']['prefix'] == 'B'
    raw.update(subject='other', printed_subject='0823+26')
    assert check_local_evidence(paper_proposal(), AdmissionCheck.model_validate(raw), target, {3: page}, {}, require_quantity=True)['state'] == 'rejected'
    raw.update(subject='target', printed_subject='0329+54')
    raw['subject_evidence'] = [dict(page=3, quote='0332+5434 0329+54 26.74870(7)')]
    assert check_local_evidence(paper_proposal(), AdmissionCheck.model_validate(raw), target, {3: page}, {}, require_quantity=True)['state'] == 'unresolved'


def test_quantity_difference_and_unreported_number_do_not_become_measurements():
    page = 'SYNTHETIC PSR B0329+54: DM difference 0.002. No total DM is reported here.'
    raw = dict(index=0, subject='target', printed_subject='PSR B0329+54',
               subject_evidence=[dict(page=3, quote=page)], result_role='reported_result',
               role_evidence=[dict(page=3, quote=page)], reason='Different quantity.',
               quantity_match='different', quantity_evidence=[dict(page=3, quote=page)])
    target = {'main_id': 'PSR B0329+54', 'aliases': []}
    assert check_local_evidence(paper_proposal(), AdmissionCheck.model_validate(raw), target, {3: page}, {}, require_quantity=True)['reason'] == 'different_reported_measurand'
    raw.update(result_role='not_reported', quantity_match='unresolved')
    assert check_local_evidence(paper_proposal(), AdmissionCheck.model_validate(raw), target, {3: page}, {}, require_quantity=True)['reason'] == 'value_not_reported_in_source_scope'


def test_actual_pulsar_designation_can_omit_literal_psr_display_prefix():
    page = 'SYNTHETIC source: pulsar B0329+54 has fitted DM 26.74870(7).'
    raw = dict(index=0, subject='target', printed_subject='PSR B0329+54',
               subject_evidence=[dict(page=3, quote=page)], result_role='reported_result',
               role_evidence=[dict(page=3, quote=page)], reason='Same verified designation.',
               quantity_match='exact', quantity_evidence=[dict(page=3, quote=page)])
    target = {'main_id': 'PSR B0329+54', 'aliases': []}
    result = check_local_evidence(paper_proposal(), AdmissionCheck.model_validate(raw), target, {3: page}, {}, require_quantity=True)
    assert result['state'] == 'passed' and result['subject_display_prefix']['source_omits_display_prefix']
    raw['printed_subject'] = 'SYNTHETIC arbitrary B0329+54'
    assert check_local_evidence(paper_proposal(), AdmissionCheck.model_validate(raw), target, {3: page}, {}, require_quantity=True)['state'] == 'unresolved'


def test_auxiliary_context_preserved_without_expanding_comparison_keys(tmp_path):
    from tests.rebuild.registry_fixture import make_release
    from tests.rebuild.factories import ref
    from astroquery_ai.science.extraction import EvidenceExtractor, ConditionProposal
    from astroquery_ai.runtime.codec import content_hash
    data = make_release(tmp_path / 'synthetic-registry')
    definition = data['definitions'][0]
    spec = {'task_id': 'SYNTHETIC task', 'spec_id': 'SYNTHETIC spec',
            'target': {'target_id': 'SYNTHETIC target'},
            'properties': [{'property_id': definition['property_id'], 'definition': definition}]}
    source = {'source_id': 'SYNTHETIC source', 'kind': 'catalog', 'table_id': 'SYNTHETIC/T', 'qualification_ref': ref()}
    source['content_sha256'] = content_hash(source)
    artifact = {'artifact_id': 'SYNTHETIC artifact', 'sha256': ref()['content_sha256']}
    p = proposal().model_copy(update={'property_id': definition['property_id'],
        'conditions': [ConditionProposal(key='method', state='known', value='SYNTHETIC midpoint', raw_text='SYNTHETIC midpoint')]})
    result = EvidenceExtractor(None).assemble(spec=spec, source=source, artifact=artifact, proposal=p,
            owner='M03', batch_id='SYNTHETIC batch', allowed_pages=[], matched_rows=[0])
    assert result['state'] == 'admitted' and result['context']['conditions'] == []
    extra = result['source_statements'][0]
    assert extra['eligible_for_comparison'] is False
    assert extra['raw_quote'] == 'SYNTHETIC midpoint'
    assert result['interpretation']['proposal']['conditions'][0]['key'] == 'method'


def test_unproved_error_labels_do_not_change_numeric_components():
    from astroquery_ai.science.paper_admission import preserve_uncertainty_semantics, page_blocks
    p = paper_proposal(delta='0.00007')
    p.errors[0].role = 'stat'
    p.errors[0].meaning = 'standard_uncertainty'
    pages = {3: 'SYNTHETIC fitted DM 26.74870(7).'}
    safe = preserve_uncertainty_semantics(p, pages, page_blocks(pages))
    assert safe.errors[0].role == safe.errors[0].meaning == 'unspecified'
    assert safe.errors[0].values == {'delta': '0.00007'} and safe.raw_value == p.raw_value
    assert p.errors[0].role == 'stat'  # Original model response is not overwritten.


def test_producer_honors_scoped_model_semantics_without_fixed_language_spelling():
    from astroquery_ai.science.paper_admission import preserve_uncertainty_semantics, page_blocks, Anchor
    p=paper_proposal(delta='0.00007')
    note='SYNTHETIC: variations aléatoires; écart-type de la mesure.'
    p.errors[0]=p.errors[0].model_copy(update={'role':'stat','meaning':'standard_uncertainty',
        'semantics_evidence':[Anchor(page=3,quote=note)],'semantic_support_fields':['role','meaning']})
    pages={3:'SYNTHETIC fitted DM 26.74870(7). '+note}
    safe=preserve_uncertainty_semantics(p,pages,page_blocks(pages))
    assert safe.errors[0].role=='stat' and safe.errors[0].meaning=='standard_uncertainty'
    assert safe.errors[0].values==p.errors[0].values and safe.raw_value==p.raw_value
    p.errors[0]=p.errors[0].model_copy(update={'semantics_evidence':[Anchor(page=3,quote='not in source')]})
    assert preserve_uncertainty_semantics(p,pages,page_blocks(pages)).errors[0].role=='unspecified'


def test_optional_error_semantics_preserves_legacy_proposal_hash_but_binds_new_assertion():
    from astroquery_ai.runtime.codec import digest
    from astroquery_ai.science.paper_admission import matches_proposal_hash
    from astroquery_ai.science.extraction import MeasurementProposal
    legacy = paper_proposal(delta='0.00007').model_dump(mode='json')
    assert 'semantic_support_fields' not in legacy['errors'][0]
    roundtrip = MeasurementProposal.model_validate(legacy).model_dump(mode='json')
    assert roundtrip == legacy and matches_proposal_hash(roundtrip, digest(legacy))
    changed = MeasurementProposal.model_validate(legacy)
    changed.errors[0].semantic_support_fields = ['meaning']
    current = changed.model_dump(mode='json')
    assert current['errors'][0]['semantic_support_fields'] == ['meaning']
    assert not matches_proposal_hash(current, digest(legacy))


def test_independent_view_is_not_changed_by_the_readers_interpretation_labels():
    from astroquery_ai.science.paper_admission import independent_proposal_view
    from astroquery_ai.science.extraction import ConditionProposal
    original = paper_proposal()
    interpreted = original.model_copy(update={'column':'SYNTHETIC inferred column',
        'source_quote':'SYNTHETIC unverified reader paraphrase', 'subject_role':'other',
        'result_role':'assumption', 'conditions':[ConditionProposal(key='synthetic',state='known',
            value='reader interpretation',raw_text=None)]})
    assert independent_proposal_view(original) == independent_proposal_view(interpreted)
    changed_literal = original.model_copy(update={'raw_value':'SYNTHETIC other literal'})
    assert independent_proposal_view(changed_literal) != independent_proposal_view(original)


def test_model_evidenced_alias_is_generic_and_needs_both_names_in_source_scope():
    p = paper_proposal().model_copy(update={'location_kind': 'body'})
    target = {'main_id': 'SYNTHETIC HD123', 'aliases': []}
    value = {'page': 3, 'quote': 'SYNTHETIC DisplayAlpha† has DM 26.74870(7).'}
    scope = {'page': 3, 'quote': 'SYNTHETIC DisplayAlpha† denotes SYNTHETIC HD123 in this table.'}
    raw = {'index': 0, 'subject': 'target', 'printed_subject': 'SYNTHETIC DisplayAlpha†',
        'subject_evidence': [value], 'result_role': 'reported_result', 'role_evidence': [value],
        'quantity_match': 'exact', 'quantity_evidence': [value], 'reason': 'SYNTHETIC model source-bound alias',
        'subject_link': {'method': 'evidenced_alias', 'relation': 'target', 'local_evidence': [value],
            'scope_evidence': [scope], 'counter_evidence': [], 'reason': 'Both identifiers declared by the source'}}
    pages = {3: value['quote'] + '\n' + scope['quote']}
    assert check_local_evidence(p, AdmissionCheck.model_validate(raw), target, pages, {}, require_quantity=True)['state'] == 'passed'
    # An anchored different object does not inherit the neighboring alias link.
    other = 'SYNTHETIC DisplayBeta has DM 26.74870(7).'
    raw['printed_subject'] = 'SYNTHETIC DisplayBeta'
    for key in ('subject_evidence', 'role_evidence', 'quantity_evidence'):
        raw[key] = [{'page': 3, 'quote': other}]
    raw['subject_link']['local_evidence'] = [{'page': 3, 'quote': other}]
    assert check_local_evidence(p, AdmissionCheck.model_validate(raw), target, {3: other + '\n' + scope['quote']}, {}, require_quantity=True)['state'] != 'passed'


def test_native_input_bound_keeps_complete_blocks_on_each_page():
    from astroquery_ai.science.paper_admission import fit_native_blocks
    from astroquery_ai.runtime.calls import input_upper_bound
    blocks = [{'page': page, 'block_id': f'p{page}:b{i}', 'text': 'SYNTHETIC ' * 35}
              for page in [1, 2, 3, 4] for i in range(5)]
    prompt, content, selected = fit_native_blocks({'instruction': 'SYNTHETIC JSON', 'page_evidence': blocks},
                                                  'page_evidence', [], blocks, maximum=4000)
    assert len(selected) < len(blocks) and {b['page'] for b in selected} == {1, 2, 3, 4}
    assert all(block in blocks for block in selected)
    assert input_upper_bound([{'role': 'user', 'content': content}]) <= 4000
    assert prompt['native_core_transcript_state'] == 'partial_blocks_full_images_retained'


def test_unit_typography_is_not_a_change_of_physical_unit():
    from astroquery_ai.science.units import parse_unit
    assert parse_unit('pc cm−3') == parse_unit('pc.cm-3') == parse_unit('pc cm⁻³')
    assert parse_unit('pc cm^{-3}') == parse_unit('pc cm**-3')
    assert parse_unit('m^{2}') == parse_unit('m2')
    import pytest
    with pytest.raises(ValueError):
        parse_unit('cm^{unknown}')


def test_empty_read_retry_cue_uses_target_and_selected_quantity_not_gold_numbers():
    from astroquery_ai.science.paper_admission import target_quantity_pages
    spec = {'target': {'main_id': 'PSR B0329+54', 'aliases': []}, 'properties': [{'definition': {
        'name_en': 'Dispersion measure', 'name_cn': '色散量', 'aliases': ['DM']}}]}
    index = {'pages': [{'page': 1, 'text': 'SYNTHETIC PSR B\nDM\n0329+54 26.84'},
                       {'page': 2, 'text': 'SYNTHETIC PSR B0329+54 without selected property.'},
                       {'page': 3, 'text': 'SYNTHETIC DM for PSR B0823+26.'}]}
    assert target_quantity_pages(spec, index, [1, 2, 3]) == [1]
