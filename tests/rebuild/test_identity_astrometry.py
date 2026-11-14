import asyncio
import httpx
import pytest

from astroquery_ai.runtime.codec import canonical, content_hash
from astroquery_ai.science.identity import SimbadIdentity
from tests.rebuild.scenario import application, confirmed_case


@pytest.mark.parametrize('coordinate', [0, 'NaN', 400])
def test_identity_retains_source_motion_errors_without_inventing_an_epoch(tmp_path, coordinate):
    app = application(tmp_path)
    fields = ['oid', 'main_id', 'otype', 'ra', 'dec', 'ids', 'pmra', 'pmdec', 'pm_err_maj',
        'pm_err_min', 'pm_err_angle', 'pm_bibcode', 'plx_value', 'plx_err', 'rvz_radvel', 'rvz_err']
    values = [7, 'SYNTHETIC_AQ', 'SYN', coordinate, 0, 'SYNTHETIC_AQ|SYNTHETIC alias',
        0, None, .15, .10, 40, 'SYNTHETIC reference', 20, .5, None, None]
    raw = canonical({'metadata': [{'name': name, 'unit': 'SYNTHETIC unit'} for name in fields], 'data': [values]})
    queries = []

    class HTTP:
        async def request(self, *args, **kwargs):
            queries.append(kwargs['data']['query'])
            return raw, {'retrieved_at': 'SYNTHETIC timestamp'}
    result = asyncio.run(SimbadIdentity(HTTP(), app.artifacts).resolve('SYNTHETIC task', 'SYNTHETIC_AQ'))
    assert len(queries) == 1 and 'b.pm_err_maj' in queries[0] and 'b.rvz_err' in queries[0]
    target = result['targets'][0]
    evidence = result['astrometric_evidence'][0]
    assert target['astrometry_evidence_ref']['content_sha256'] == content_hash(evidence)
    assert evidence['raw_values']['pmra'] == 0 and evidence['raw_values']['pmdec'] is None
    assert evidence['raw_values']['pm_err_maj'] == .15 and evidence['raw_values']['pm_err_min'] == .10
    assert evidence['raw_values']['rvz_radvel'] is None and evidence['reference_epoch'] is None
    assert evidence['pm_ra_convention'] == 'not_established_by_this_response'
    assert not evidence['autonomous_match_granted']
    assert (target['coordinates'] is not None) == (coordinate == 0)


def test_real_identity_adapter_evidence_reaches_the_frozen_snapshot_in_synthetic_flow(tmp_path):
    async def run():
        app = application(tmp_path)
        ordinary_transport = app.http.transport

        async def http(request):
            if request.url.host in {'simbad.cds.unistra.fr', 'simbad.cfa.harvard.edu'}:
                return httpx.Response(200, json={'metadata': [{'name': n} for n in
                    ['oid', 'main_id', 'otype', 'ra', 'dec', 'ids', 'pmra', 'pmdec', 'pm_err_maj']],
                    'data': [[7, 'SYNTHETIC_AQ', 'pA*', 0, 0, 'SYNTHETIC_AQ', 1.0, -2.0, .1]]})
            return await ordinary_transport.handle_async_request(request)
        app.http.transport = httpx.MockTransport(http)
        app.identity = SimbadIdentity(app.http, app.artifacts)
        state, _ = await confirmed_case(app)
        with app.repository.read() as conn:
            delivery = app.delivery.get(conn, state['task_id'])
            query = app.repository.object(conn, state['task_id'], 'confirmed_query', delivery['query_ref']['id'])
            ref = query['target']['astrometry_evidence_ref']
            evidence = app.repository.object(conn, state['task_id'], 'target_astrometry', ref['id'], ref['version'])
        assert evidence in delivery['provenance_bundle']['target_astrometries']
        assert evidence['raw_values']['pm_err_maj'] == .1
        assert evidence['reference_epoch'] is None
        assert query['target']['coordinates']['ra_deg'] == 0
    asyncio.run(run())
