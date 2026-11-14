"""A missing formal explanation must never discard original measurement facts."""
from copy import deepcopy

from astroquery_ai.science import author_insights, property_insights
from tests.rebuild.test_author_insight_generation import setup_case


def test_unbound_property_has_explicit_gap_while_native_facts_survive():
    delivery, spec, release = setup_case()
    release['author']['bindings'] = []
    before = deepcopy(delivery)
    materials = author_insights.property_materials(delivery, spec, release)
    assert materials[0]['measurements'] and not materials[0]['claims']
    units = property_insights.property_units(delivery, spec, release)
    report = property_insights.final_report(delivery, spec, {'id': 'SYNTHETIC local knowledge'}, units, {})
    assert report['cards'][0]['knowledge_coverage']['state'] == 'missing'
    assert report['knowledge_coverage']['missing'] == 1
    assert report['cards'][0]['coverage']['all_measurement_ids']
    assert delivery == before
    legacy = author_insights.final_report(delivery, spec, {'id': 'SYNTHETIC local knowledge'}, materials, [], 0)
    assert legacy['property_states'][0]['knowledge_coverage']['state'] == 'missing'
    assert legacy['complete_data_preserved']
