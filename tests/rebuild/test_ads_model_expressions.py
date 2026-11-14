"""Synthetic protocol/permission boundaries; no scientific retrieval claims."""
from copy import deepcopy
import pytest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.ads_queries import checked_expression
from astroquery_ai.science.literature_selection import checked_query,query_outcome
from astroquery_ai.science.workflow.literature_service import LiteratureService
from astroquery_ai.science.literature import ranked_queues,parse_record,deduplicate


def spec():
    return {'target':{'main_id':'synthetic star','aliases':['catalog 1']},'properties':[{'property_id':'p','definition':{'family_id':'f'}}]}


def row(channel='metadata'):
    target='abs:("synthetic star" OR "catalog 1")'
    quantity=('body' if channel=='body' else 'abs')+':(temperature OR Teff)'
    return {'family':'F1','properties':['P1'],'channel':channel,'names':['N1','N2'],
            'target_query':target,'quantity_query':quantity,'query':f'({target}) AND ({quantity})','intent':'SYNTHETIC target temperature'}


def families():return [{'family_id':'f','selected_property_ids':['p']}]


def test_actual_expressions_preserve_model_wording_and_two_channels():
    plans=checked_query({'queries':[row(),row('body')]},spec(),families())
    assert {p['layer'] for p in plans}=={'metadata','body'}
    assert all('doctype:(article OR eprint)' in p['query'] for p in plans)
    assert all('catalog 1' in p['query'] and 'Teff' in p['query'] for p in plans)
    assert 'abs:temperature' in plans[0]['query']  # no forced long phrase


@pytest.mark.parametrize('change',[
    {'query':'abs:"synthetic star" OR abs:temperature OR abs:"catalog 1" OR abs:Teff'},
    {'target_query':'object:("synthetic star" OR "catalog 1")'},
    {'target_query':'abs:("invented star" OR "catalog 1")'},
    {'channel':'identifier'},
    {'query':'abs:"synthetic star" AND (abs:temperature OR abs:Teff)'},
    {'quantity_query':'abs:temperature NOT abs:planet'},
])
def test_invalid_or_escaping_query_never_becomes_pure_name_search(change):
    r=row();r.update(change)
    with pytest.raises(DomainError):checked_expression(r,['synthetic star','catalog 1'])


def test_bad_sibling_reports_gap_but_preserves_valid_query():
    bad=row('body');bad['names']=['N999']
    out=query_outcome({'queries':[row(),bad]},spec(),families())
    assert len(out['plans'])==1 and out['missing_scopes']==[('f','body')]
    assert out['errors'] and out['plans'][0]['layer']=='metadata'


def test_scientific_bracket_notation_is_literal_not_an_ads_range():
    r=row();r['quantity_query']='abs:("[Fe/H]" OR metallicity)'
    r['query']=r['target_query']+' AND '+r['quantity_query']
    assert '[Fe/H]' in checked_expression(r,['synthetic star','catalog 1'])


def test_one_query_keeps_all_family_memberships_and_ranking():
    s=spec();s['properties'].append({'property_id':'p2','definition':{'family_id':'f2'}})
    fs=families()+[{'family_id':'f2','selected_property_ids':['p2']}]
    second=row();second.update(family='F2',properties=['P2'])
    out=query_outcome({'queries':[row(),second]},s,fs)
    assert len(out['plans'])==1 and len(out['plans'][0]['family_links'])==2
    works,mapping=deduplicate([parse_record({'bibcode':'SYNTHETIC-a','doctype':'article'})])
    queues=ranked_queues(works,mapping,[{**out['plans'][0],'bibcodes':['SYNTHETIC-a']}],['f','f2'])
    assert queues['f']==queues['f2'] and len(queues['f'])==1


def test_final_allocation_keeps_only_the_selected_property(tmp_path):
    # The old all-confirmed-properties expansion was explicitly retired.
    # Check its replacement at the actual material publication boundary.
    import asyncio
    from astroquery_ai.science.literature_preparation import prepare, schedule
    from tests.rebuild.test_two_tier_materials import carrier, settle_synthetic_downloads

    async def run():
        repo, tid, service = carrier(tmp_path, properties=('p', 'q'), count=1)
        with repo.transaction() as conn:
            state = repo.objects(conn, tid, 'material_preparation')[0]
            state['revision'] = 2
            state['pools']['q']['eligible'] = []
            for pool in state['pools'].values():
                pool['full_used'] = True
            repo.put_object(conn, tid, 'material_preparation', tid, 2, state)
        await prepare(service, repo.claim_job('worker', task_id=tid))
        settle_synthetic_downloads(repo, tid)
        with repo.transaction() as conn:
            schedule(repo, conn, tid)
        await prepare(service, repo.claim_job('worker', task_id=tid))
        with repo.read() as conn:
            source = repo.objects(conn, tid, 'source')[0]
            assert source['work']['allowed_property_ids'] == ['p']
            allocation = repo.objects(conn, tid, 'reading_allocation')[0]
            assert allocation['property_ids'] == ['p']
    asyncio.run(run())
