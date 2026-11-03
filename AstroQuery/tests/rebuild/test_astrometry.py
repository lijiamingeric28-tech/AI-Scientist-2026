from copy import deepcopy
import math

import numpy as np
import pytest

from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.astrometry import propagate, STATE_ORDER


def state():
    return {'frame': 'icrs', 'coordinate_role': 'source_native',
        'pm_ra_convention': 'already_multiplied_by_cos_dec',
        'ra_deg': '0', 'dec_deg': '0', 'parallax_mas': '100',
        'pm_ra_cosdec_masyr': '0', 'pm_dec_masyr': '0', 'radial_velocity_kms': '0',
        'reference_epoch': {'value': '2016', 'format': 'jyear', 'scale': 'tcb'},
        'source_evidence_refs': ['SYNTHETIC explicit six-dimensional state']}


WHEN = {'value': '2017', 'format': 'jyear', 'scale': 'tcb'}


def test_position_zero_and_wrap_are_valid_but_no_missing_motion_is_filled():
    source = state()
    result = propagate({**source, 'ra_deg': '360'}, WHEN)
    assert abs(float(result['ra_deg'])) < 1e-10 and abs(float(result['dec_deg'])) < 1e-10
    assert not result['autonomous_match_accepted'] and result['covariance_mas2'] is None
    for key in ['parallax_mas', 'pm_ra_cosdec_masyr', 'pm_dec_masyr', 'radial_velocity_kms']:
        with pytest.raises(DomainError):
            propagate({**source, key: None}, WHEN)


def test_high_proper_motion_uses_cosdec_convention_and_crosses_ra_zero():
    source = {**state(), 'ra_deg': '359.999', 'dec_deg': '60', 'pm_ra_cosdec_masyr': '5000'}
    result = propagate(source, WHEN)
    delta = (float(result['ra_deg']) - 359.999 + 180) % 360 - 180
    assert delta * math.cos(math.radians(60)) * 3600000 == pytest.approx(5000, rel=1e-5)
    assert float(result['ra_deg']) < 1
    # Angular geometry remains finite in the polar region as well.
    result = propagate({**source, 'dec_deg': '89.9999'}, WHEN)
    assert math.isfinite(float(result['ra_deg'])) and math.isfinite(float(result['dec_deg']))


@pytest.mark.parametrize('change', [
    {'reference_epoch': {'equinox': 'J2000'}},
    {'reference_epoch': {'value': '2016', 'format': 'jyear', 'scale': 'UNKNOWN'}},
    {'coordinate_role': 'service_computed'}, {'pm_ra_convention': None}, {'frame': 'FK5'},
])
def test_metadata_ambiguity_is_not_repaired_by_a_library_default(change):
    with pytest.raises(DomainError):
        propagate({**state(), **change}, WHEN)


def test_supplied_cross_covariance_is_propagated_instead_of_discarded():
    source = state()
    cov = np.diag([.25, .25, .01, .04, .04, 1.0])
    cov[0, 3] = cov[3, 0] = .03
    source.update(covariance=cov.tolist(), covariance_order=list(STATE_ORDER))
    untouched = deepcopy(source)
    result = propagate(source, WHEN, differentiation_steps=[.1, .1, .01, .01, .01, .01])
    # C_position + dt^2 C_motion + dt(C_cross + C_cross^T), at dt=1 year.
    assert result['covariance_mas2'][0][0] == pytest.approx(.25 + .04 + 2 * .03, rel=1e-5)
    assert result['covariance_mas2'][1][1] == pytest.approx(.25 + .04, rel=1e-5)
    assert not result['autonomous_match_accepted']
    assert source == untouched


def test_unknown_cross_terms_or_invalid_covariance_cannot_be_filled_with_zero():
    source = state()
    with pytest.raises(DomainError):
        propagate(source, WHEN, differentiation_steps=[.1] * 6)
    source.update(covariance=np.eye(6).tolist(), covariance_order=list(STATE_ORDER))
    source['covariance'][0][1] = None
    with pytest.raises(DomainError):
        propagate(source, WHEN, differentiation_steps=[.1] * 6)
    source['covariance'] = np.eye(6).tolist()
    source['covariance'][0][0] = -1
    with pytest.raises(DomainError):
        propagate(source, WHEN, differentiation_steps=[.1] * 6)
