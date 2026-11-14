from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from astroquery_ai.application.material_workbench import MaterialIndex, material_overview
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from tests.rebuild.test_material_analysis_runs import case
from tests.rebuild.test_research_exports import fixture


def test_material_group_cards_count_records_and_figures_once_across_properties():
    body = fixture()
    second = deepcopy(body['definitions'][0])
    second['property_id'] = 'second'
    second['definition']['name_cn'] = '第二性质'
    body['definitions'].append(second)
    body['measurements'][1]['property_ref']['id'] = 'second'
    body['figures'] = [{'figure_id': 'one-image', 'source_id': 's1', 'property_ids': ['p-temperature', 'second']}]
    before = deepcopy(body)
    index = MaterialIndex(body)
    rows = index.grouped_listing()
    assert len(rows) == 1
    assert (rows[0]['record_count'], rows[0]['figure_count']) == (2, 1)
    assert [p['property_id'] for p in rows[0]['available_properties']] == ['p-temperature', 'second']
    assert index.grouped_listing(property_id='second')[0]['record_count'] == 1
    assert body == before


def test_new_header_scope_counts_do_not_reinterpret_legacy_material_associations():
    from astroquery_ai.application.delivery_projections import header_projection
    body = fixture()
    second = deepcopy(body['definitions'][0])
    second['property_id'] = 'second'
    body['definitions'].append(second)
    body['measurements'][1]['property_ref']['id'] = 'second'
    body['revision'], body['status'], body['counts'] = 1, 'completed', {'records': 2}
    index = MaterialIndex(body)
    result = header_projection(body, material_overview(body, index), index=index)
    assert result['display_counts']['materials'] == 2
    assert result['display_counts']['material_groups'] == 1
    assert result['display_counts']['properties'] == 2


def test_grouped_material_http_list_is_opt_in_and_keeps_legacy_contract(tmp_path):
    from tests.rebuild.test_delivery_projection_index import application
    _, _, tid, _, app = application(tmp_path)
    base = f'/api/tasks/{tid}/deliveries/delivery/materials?view=workbench&delivery_revision=1'
    with TestClient(app) as client:
        response = client.get(base + '&group_by=material')
        assert response.status_code == 200
        assert 'available_properties' in response.json()['items'][0]
        assert response.json()['group_by'] == 'material'
        legacy = client.get(base)
        assert legacy.status_code == 200
        assert legacy.json()['items'][0]['property_id'] == 'p-temperature'


def test_property_report_can_be_read_and_submitted_without_a_material_anchor(case):
    import asyncio
    app, tid, body, source, pid, calls = case
    service = app.material_analysis
    request = {'operation_id': 'property-page', 'expected_delivery_revision': body['revision'],
               'property_id': pid, 'scope': 'property_comparison'}
    run = service.submit(tid, body['delivery_id'], request)
    asyncio.run(service.execute(run['run_id']))
    view = service.read(tid, body['delivery_id'], body['revision'], None, pid, 'property_comparison')
    assert view['report']['status'] == 'complete'
    assert view['scope']['material_id'] is None
    same = service.submit(tid, body['delivery_id'], {**request, 'operation_id': 'old-material-anchor', 'material_id': source})
    assert same['run_id'] == run['run_id'] and len(calls) == 1
    with pytest.raises(DomainError):
        service.submit(tid, body['delivery_id'], {**request, 'operation_id': 'missing-own-material', 'scope': 'material'})


def test_reference_detail_keeps_frozen_formula_after_current_library_changes(tmp_path):
    from tests.rebuild.test_task_knowledge_context import case as knowledge_case
    from astroquery_ai.science import task_knowledge
    from astroquery_ai.application.insight_views import knowledge_reference_view
    app, spec, _, _, uid, *_ = knowledge_case(tmp_path)
    item = app.user_knowledge.get_entry(uid)
    app.user_knowledge.update_entry(uid, {'formula': r'F = ma', 'expected_revision': item['revision']})
    context = task_knowledge.capture(app, spec)
    block = next(e for e in context['entries'] if e['entry_id'] == uid)
    item = app.user_knowledge.get_entry(uid)
    app.user_knowledge.update_entry(uid, {'formula': 'CHANGED', 'expected_revision': item['revision']})
    before = canonical(context)
    view = knowledge_reference_view(app, context, uid, block['claim']['claim_id'], block['content_sha256'])
    assert view['entry']['formula'] == r'F = ma'
    assert view['claim']['text'] == 'original private background'
    assert view['read_only'] is True and canonical(context) == before
    with pytest.raises(DomainError):
        knowledge_reference_view(app, context, uid, block['claim']['claim_id'], 'wrong-version')


def test_old_projected_fragment_hash_resolves_and_full_same_release_text_survives(tmp_path):
    from astroquery_ai.science import task_knowledge
    from astroquery_ai.runtime.codec import content_hash
    from astroquery_ai.application.insight_views import knowledge_reference_view
    from tests.rebuild.test_task_knowledge_context import case as knowledge_case
    app, spec, _, release, *_ = knowledge_case(tmp_path)
    context = task_knowledge.capture(app, spec)
    block = deepcopy(context['entries'][0])
    block['origin'] = 'historical_saved_basis'
    block['saved_fragment_sha256'] = block['content_sha256']
    block['content_sha256'] = content_hash(block)
    context['entries'] = [block]
    context['content_sha256'] = content_hash(context)
    legacy_hash = content_hash({k: v for k, v in block.items() if k != 'saved_fragment_sha256'})
    release['author']['entries'][0]['blocks'].append({'text': 'full preserved method', 'role': 'method', 'basis': 'source_checked', 'source_ids': ['s']})
    result = knowledge_reference_view(app, context, block['entry_id'], block['claim']['claim_id'], legacy_hash)
    assert result['expansion'] == 'same_release'
    assert 'full preserved method' in result['entry']['description']


def test_unresolved_citation_groups_have_a_separate_explicit_directory_filter():
    body = fixture()
    body['provenance_bundle']['cited_works'] = [{'cited_work_id': 'cited', 'title': 'Unresolved citation', 'authors': []}]
    index = MaterialIndex(body)
    assert len(index.grouped_listing()) == 1
    assert len(index.grouped_listing(kind='cited')) == 1
    assert index.grouped_listing(kind='cited')[0]['kind'] == 'cited'
