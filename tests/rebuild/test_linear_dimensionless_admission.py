"""Independent original-evidence gates for linear dimensionless coordinates."""
import pytest

from astroquery_ai.science.paper_admission import AdmissionCheck, check_local_evidence
from astroquery_ai.science.unit_declarations import dimensionless_coordinate_declaration
from tests.rebuild.test_paper_admission import paper_proposal


def evidence_case():
    text = 'SYNTHETIC cluster has source-adopted redshift z = 0.023 in the source.'
    data = paper_proposal().model_dump(mode='json')
    data.update({
        'raw_value': '0.023', 'value': {'kind': 'real', 'value': '0.023'},
        'unit': None, 'errors': [], 'representation': 'linear', 'location_kind': 'body'})
    p = type(paper_proposal()).model_validate(data)
    anchor = {'page': 3, 'quote': text}
    check = dict(index=0, subject='target', printed_subject='SYNTHETIC cluster',
        subject_evidence=[anchor], result_role='adopted_measurement', role_evidence=[anchor],
        quantity_match='exact', quantity_evidence=[anchor], native_unit=None,
        unit_match='not_applicable', unit_evidence=[], reason='Synthetic independent source check')
    binding = {'output_profile': {'unit': {'kind': 'dimensionless', 'semantic_kind': 'redshift'},
        'representation': {'kind': 'linear'}}}
    return p, check, binding, {3: text}


def verify(p, check, binding, pages):
    return check_local_evidence(p, AdmissionCheck.model_validate(check),
        {'main_id': 'SYNTHETIC cluster', 'aliases': []}, pages, {},
        require_quantity=True, require_units=True, property_binding=binding)


def test_evidenced_cluster_redshift_preserves_absent_printed_unit():
    p, check, binding, pages = evidence_case()
    v = verify(p, check, binding, pages)
    assert v['state'] == 'passed', v
    d = dimensionless_coordinate_declaration(p.model_dump(mode='json'), binding, v, {'id': 'original'})
    assert d['canonical_symbol'] == '1'
    assert d['raw_unit_text'] is None and d['source_literal'] is None
    assert 'redshift z = 0.023' in d['raw_quote']


@pytest.mark.parametrize('change', ['member', 'velocity', 'missing_evidence', 'missing_physical_unit', 'unresolved'])
def test_missing_unit_is_never_a_general_dimensionless_fallback(change):
    p, check, binding, pages = evidence_case()
    if change == 'member':
        check.update(subject='other', printed_subject='SYNTHETIC member')
    elif change == 'velocity':
        check.update(quantity_match='different', native_unit='km/s', unit_match='different')
    elif change == 'missing_evidence':
        check['quantity_evidence'] = []
    elif change == 'missing_physical_unit':
        binding['output_profile']['unit'] = {'kind': 'physical', 'canonical_symbol': 'keV'}
    else:
        check['quantity_match'] = 'unresolved'
    v = verify(p, check, binding, pages)
    assert dimensionless_coordinate_declaration(p.model_dump(mode='json'), binding, v, {}) is None


def test_forged_pass_without_coordinate_verification_does_not_supply_unit():
    p, check, binding, pages = evidence_case()
    v = verify(p, check, binding, pages)
    v.pop('dimensionless_native_coordinate')
    assert dimensionless_coordinate_declaration(p.model_dump(mode='json'), binding, v, {}) is None
