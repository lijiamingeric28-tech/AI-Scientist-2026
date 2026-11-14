from copy import deepcopy

from fastapi.testclient import TestClient

from tests.rebuild.test_material_workbench import fixture
from tests.rebuild.test_delivery_projection_index import application


def test_reading_profile_uses_exact_material_property_and_keeps_source_unchanged():
    from astroquery_ai.application.material_reading import reading_profiles
    body = fixture()
    body['sources'].append({'source_id': 'other', 'title': 'Other source'})
    body['measurements'][1]['source_ref']['id'] = 'other'
    body['measurements'][0]['representation'] = 'linear'
    before = deepcopy(body)
    profiles = reading_profiles(body)
    profile = profiles['s1:p-temperature']
    assert profile['record_count'] == 1
    assert profile['units'] == ['K']
    assert profile['measurement_ids'] == ['m1']
    assert profile['condition_state'] == 'not_recorded'
    assert body == before


def test_material_http_detail_exposes_scope_profile_and_switchable_properties(tmp_path, monkeypatch):
    repo, service, tid, body, app = application(tmp_path)
    url = f'/api/tasks/{tid}/deliveries/delivery/materials?view=workbench&material_id=s1&property_id=p-temperature&delivery_revision=1'
    with TestClient(app) as client:
        first = client.get(url)
        assert first.status_code == 200
        row = first.json()['items'][0]
        assert row['available_properties'][0]['property_id'] == 'p-temperature'
        assert row['profile']['record_count'] == row['record_count'] == 2
        assert len(body['measurements']) == 4
        assert row['profile']['scope'] == 'material_property'
        original = repo.object
        def no_delivery(conn, task, kind, *args, **kwargs):
            assert kind != 'delivery', 'warm detail must use exact disposable projection'
            return original(conn, task, kind, *args, **kwargs)
        monkeypatch.setattr(repo, 'object', no_delivery)
        assert client.get(url).json() == first.json()
        assert client.get(url + '&at_seq=999999').status_code == 409
