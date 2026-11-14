"""Evidence-preserving 3D propagation; numerical output never grants a match."""
from __future__ import annotations

import math
import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, Distance
from astropy.time import Time

from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.errors import DomainError


STATE_ORDER = ('east_mas', 'north_mas', 'parallax_mas', 'pm_ra_cosdec_masyr', 'pm_dec_masyr', 'radial_velocity_kms')
VALUE_FIELDS = ('ra_deg', 'dec_deg', *STATE_ORDER[2:])


def number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise DomainError('ASTROMETRY_INSUFFICIENT_METADATA', '天体测量字段缺失或类型无效')
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise DomainError('ASTROMETRY_INSUFFICIENT_METADATA', '天体测量字段不是有限数值') from exc
    if not math.isfinite(result):
        raise DomainError('ASTROMETRY_INSUFFICIENT_METADATA', '天体测量字段不是有限数值')
    return result


def epoch(value):
    if (not isinstance(value, dict) or value.get('scale') not in {'tai', 'tcb', 'tcg', 'tdb', 'tt', 'utc'}
            or value.get('format') not in {'jd', 'mjd', 'jyear', 'byear'}):
        raise DomainError('ASTROMETRY_TIME_UNRESOLVED', '传播必须有实际历元、格式和时间尺度，不能使用分点代替')
    return Time(number(value.get('value')), format=value['format'], scale=value['scale'])


def coordinate(state, values=None, displacement=None):
    if state.get('frame') != 'icrs':
        raise DomainError('ASTROMETRY_FRAME_UNRESOLVED', '该传播器只接收有据ICRS状态，不暗中解决参考系冲突')
    if state.get('coordinate_role') != 'source_native':
        raise DomainError('ASTROMETRY_REPEATED_PROPAGATION', '服务计算坐标不能再当原生状态传播')
    if state.get('pm_ra_convention') != 'already_multiplied_by_cos_dec':
        raise DomainError('ASTROMETRY_PM_CONVENTION_UNRESOLVED', '必须确认pmRA是否已乘cos(dec)')
    values = values if values is not None else [number(state.get(k)) for k in VALUE_FIELDS]
    ra, dec, parallax, pmra, pmdec, rv = values
    if not -90 <= dec <= 90 or parallax <= 0:
        raise DomainError('ASTROMETRY_OUTSIDE_3D_SCOPE', '三维传播要求有效赤纬及有据正视差')
    anchor = SkyCoord(ra=(ra % 360) * u.deg, dec=dec * u.deg, frame='icrs')
    if displacement is not None:
        position_angle, amount = displacement
        anchor = anchor.directional_offset_by(position_angle * u.deg, amount * u.mas)
    return SkyCoord(ra=anchor.ra, dec=anchor.dec, distance=Distance(parallax=parallax * u.mas),
        pm_ra_cosdec=pmra * u.mas / u.yr, pm_dec=pmdec * u.mas / u.yr,
        radial_velocity=rv * u.km / u.s, obstime=epoch(state.get('reference_epoch')), frame='icrs')


def propagate(state, destination, *, differentiation_steps=None):
    """Uniform space motion. Missing RV is never a measured zero.

    A caller must separately qualify the model's acceleration/perspective domain,
    error conventions, systematics, reference frames and candidate-set completeness.
    """
    from astroquery_ai.runtime.astronomy import configure_offline_tables
    configure_offline_tables()
    initial = coordinate(state)
    when = epoch(destination)
    final = initial.apply_space_motion(new_obstime=when)
    report = {'schema_version': 'AstrometricPropagation/1', 'method': 'astropy_uniform_space_motion_3d',
        'input_state_sha256': digest(state), 'source_evidence_refs': state.get('source_evidence_refs', []),
        'destination_epoch': destination, 'frame': 'icrs', 'ra_deg': format(final.ra.deg, '.17g'),
        'dec_deg': format(final.dec.deg, '.17g'), 'covariance_mas2': None, 'jacobian': None,
        'autonomous_match_accepted': False, 'scientific_model_scope_approval_granted': False}
    if differentiation_steps is None:
        report['uncertainty_state'] = 'not_calculated'
        return report
    if (not isinstance(differentiation_steps, (list, tuple)) or len(differentiation_steps) != 6
            or tuple(state.get('covariance_order', [])) != STATE_ORDER):
        raise DomainError('ASTROMETRY_COVARIANCE_UNRESOLVED', '协方差顺序和显式微分步长必须与六维状态一致')
    try:
        covariance = np.asarray(state.get('covariance'), dtype=float)
    except (TypeError, ValueError) as exc:
        raise DomainError('ASTROMETRY_COVARIANCE_UNRESOLVED', '协方差缺失或无法读取') from exc
    if (covariance.shape != (6, 6) or not np.isfinite(covariance).all()
            or not np.array_equal(covariance, covariance.T) or np.linalg.eigvalsh(covariance).min() < 0):
        raise DomainError('ASTROMETRY_COVARIANCE_UNRESOLVED', '需要完整、对称、半正定的已知协方差，未知交叉项不填零')
    steps = [number(v) for v in differentiation_steps]
    if any(s <= 0 for s in steps):
        raise DomainError('ASTROMETRY_DIFFERENTIATION_SCOPE', '微分步长必须显式给出且大于零')
    values = [number(state.get(k)) for k in VALUE_FIELDS]
    jacobian = np.zeros((2, 6))
    for index, step in enumerate(steps):
        offsets = []
        for sign in (-1, 1):
            moved = values.copy()
            displacement = None
            if index < 2:
                displacement = (90 if index == 0 else 0, sign * step)
            else:
                moved[index] += sign * step
            perturbed = coordinate(state, moved, displacement).apply_space_motion(new_obstime=when)
            east, north = final.spherical_offsets_to(perturbed)
            offsets.append(np.array([east.to_value(u.mas), north.to_value(u.mas)]))
        jacobian[:, index] = (offsets[1] - offsets[0]) / (2 * step)
    projected = jacobian @ covariance @ jacobian.T
    if not np.isfinite(projected).all():
        raise DomainError('ASTROMETRY_NUMERICAL_FAILURE', '传播后的协方差不是有限值')
    report.update(uncertainty_state='propagated_from_supplied_covariance',
        covariance_mas2=projected.tolist(), jacobian=jacobian.tolist(), input_covariance_order=list(STATE_ORDER),
        differentiation_steps=steps, covariance_rule='J C J^T',
        additional_systematics='not_supplied_or_combined', cross_catalog_correlations='not_supplied_or_combined')
    return report
