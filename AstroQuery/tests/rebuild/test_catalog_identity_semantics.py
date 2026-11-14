"""Synthetic boundaries for evidence-backed, non-exact identifier consumption."""
from copy import deepcopy
import pytest
from astroquery_ai.science.catalog_identity import (
    identity_prompt, checked_identities, semantic_binding, navigation_patterns,
)


TARGET = {'target_id': 'SYNTHETIC target', 'main_id': 'PSR J1234+5678A', 'aliases': []}
TABLE = {'table_id': 'SYNTHETIC/table', 'description': 'SYNTHETIC source notation', 'columns': [
    {'name': 'Object', 'datatype': 'char', 'ucd': 'meta.id;meta.main', 'description': 'Pulsar name (J2000)'},
    {'name': 'Cross', 'datatype': 'char', 'ucd': 'meta.id.cross', 'description': 'Published same-object identifier'},
    {'name': 'Value', 'datatype': 'double', 'description': 'SYNTHETIC quantity'}],
    'rows': [{'Object': '1234 + 5678 A', 'Cross': None, 'Value': '26.00'}]}


def verdict(**changes):
    item = {'row': 0, 'relation': 'same_entity', 'method': 'source_notation', 'source_column': 'Object',
            'target_alias': None, 'notation_option_id': 'notation-0',
            'evidence_ids': ['column:Object', 'cell:0:Object'], 'reason': 'SYNTHETIC source-declared omitted prefix'}
    return {'rows': [{**item, **changes}]}


def check(response, table=None):
    table = table or deepcopy(TABLE)
    prompt, spans = identity_prompt(TARGET, table, table['rows'], [0], 'Object')
    return checked_identities(response, TARGET, table, table['rows'], [0], 'Object', spans)[0], prompt


def test_source_notation_keeps_original_cells_and_is_never_exact_binding():
    result, prompt = check(verdict())
    assert result['state'] == 'accepted'
    assert 'Value' not in str(prompt['source_evidence'])
    proof = semantic_binding(TARGET, TABLE, TABLE['rows'][0], result,
        {'artifact_id': 'SYNTHETIC artifact', 'sha256': 'SYNTHETIC hash'}, {'attempt_id': 'SYNTHETIC attempt'})
    assert proof['schema_version'] == 'EvidencedIdentifierBinding/1'
    assert proof['actual_returned_keys']['Object'] == '1234 + 5678 A'
    assert proof['exact_identifier_match_claimed'] is False
    assert proof['general_alias_rule_granted'] is False


def test_repeated_identifier_inputs_reuse_decision_with_each_rows_own_evidence():
    from astroquery_ai.science.catalog_identity import identity_equivalence_groups,rebind_identity_check
    table=deepcopy(TABLE)
    table['rows']=[{**table['rows'][0],'Value':str(i)} for i in range(1032)]
    table['rows'].append({**table['rows'][0],'Cross':'PSR J9999+9999'})
    groups,names=identity_equivalence_groups(table,'Object')
    assert groups[0]==list(range(1032)) and groups[1032]==[1032] and 'Value' not in names
    _,spans=identity_prompt(TARGET,table,table['rows'],[0],'Object')
    original=checked_identities(verdict(notation_option_id=None,target_alias_id='A1'),TARGET,table,table['rows'],[0],'Object',spans)[0]
    rebound=rebind_identity_check(original,1031,TARGET,table,'Object',spans)
    assert rebound['state']=='accepted' and rebound['row']==1031
    assert 'cell:1031:Object' in rebound['anchors'] and 'cell:0:Object' not in rebound['anchors']
    assert rebound['reused_from_row']==0
    with pytest.raises(ValueError):rebind_identity_check(original,1032,TARGET,table,'Object',spans)
    table['description']='SYNTHETIC: rows 1-3 have special subject meanings'
    assert len(identity_equivalence_groups(table,'Object')[0])==1033


def test_model_frame_component_exclusions_and_actual_alias_scope_are_preserved():
    # v3 asks the model for source naming meaning, replacing the approved old
    # prefix-only gate. The program preserves exclusions and actual ID scope;
    # it does not claim to solve frame semantics through spelling variants.
    for key in ['1234+5678', 'B1234+5678A', '1234+5678B']:
        table = deepcopy(TABLE)
        table['rows'][0]['Object'] = key
        assert check(verdict(relation='component',notation_option_id=None,target_alias_id='A1'), table)[0]['state'] == 'rejected'
    table = deepcopy(TABLE)
    table['columns'][0]['description'] = 'Pulsar name; coordinate convention unspecified'
    assert check(verdict(relation='unknown',notation_option_id=None,target_alias_id='A1'), table)[0]['state'] == 'unresolved'
    assert check(verdict(target_alias='PSR J1234+5678B'))[0]['state'] != 'accepted'
    assert check(verdict(evidence_ids=['column:Object', 'cell:0:Object', 'invented']))[0]['state'] != 'accepted'


def test_independent_exact_key_conflict_is_not_erased_by_semantics():
    table = deepcopy(TABLE)
    table['columns'][1].update(name='PSRJ', description='Pulsar name')
    table['rows'][0]['PSRJ'] = 'J9999+9999'
    assert check(verdict(), table)[0]['state'] != 'accepted'


def test_published_pair_must_be_same_row_or_one_actual_statement():
    table = deepcopy(TABLE)
    table['rows'][0].update(Object='Local-42', Cross=TARGET['main_id'])
    response = verdict(method='published_cross_id', source_column='Cross', target_alias=TARGET['main_id'], notation_option_id=None,
        evidence_ids=['cell:0:Object', 'cell:0:Cross', 'column:Cross'])
    assert check(response, table)[0]['state'] == 'accepted'
    # Naming the target elsewhere in the catalogue cannot bind Local-42.
    table['rows'][0]['Cross'] = None
    table['description'] += ' includes ' + TARGET['main_id']
    response = verdict(method='published_cross_id', target_alias=TARGET['main_id'], notation_option_id=None,
        evidence_ids=['cell:0:Object', 'column:Object', 'table:description'])
    assert check(response, table)[0]['state'] != 'accepted'


def test_candidate_patterns_are_navigation_and_omissions_remain_unknown():
    patterns = navigation_patterns([TARGET['main_id']])
    assert '*1234*5678*' in patterns
    assert '*PSR*J1234+5678A*' in patterns  # Literal navigation retains the component.
    result, _ = check({'rows': []})
    assert result['state'] == 'unresolved'
    assert result['reason'] == 'row_not_interpreted'


def test_source_scope_limitation_requires_all_identifier_definitions_and_no_conflicting_match():
    from astroquery_ai.science.catalog_identity import checked_table_identity_limitation
    from astroquery_ai.runtime.errors import DomainError
    _,spans=identity_prompt(TARGET,TABLE,TABLE['rows'],[0],'Object')
    response={'rows':[],'table_identity_limitation':{'kind':'source_cross_identification_missing',
        'columns':['Object','Cross'],'evidence_ids':['column:Object','column:Cross'],
        'reason':'SYNTHETIC source mapping unavailable'}}
    assert checked_table_identity_limitation(response,TABLE,'Object',spans)
    for change in ({'columns':['Object']},{'evidence_ids':['cell:0:Object']},
                   {'evidence_ids':['column:Object','invented']}):
        value=deepcopy(response);value['table_identity_limitation'].update(change)
        with pytest.raises(DomainError):checked_table_identity_limitation(value,TABLE,'Object',spans)
    value=deepcopy(response);value['rows']=verdict()['rows']
    with pytest.raises(DomainError):checked_table_identity_limitation(value,TABLE,'Object',spans)


def test_source_wide_missing_crosswalk_does_not_repeat_opaque_row_judgments(tmp_path):
    import asyncio,json
    from types import SimpleNamespace
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.runtime.calls import ModelProfile
    from astroquery_ai.science.catalog.identity import interpret_identity_rows
    async def run():
        repo=Repository(tmp_path/'db');tid=repo.create_task('SYNTHETIC opaque source')['task_id']
        with repo.transaction() as c:
            repo.mutate_task(c,tid,lifecycle='running',science_state='open');repo.enqueue(c,tid,'M03','catalog_extract',{})
        job=repo.claim_job('test',task_id=tid,lease_seconds=600);calls=[]
        class Steps:
            async def model(self,*args,**kwargs):
                body=json.loads(kwargs['messages'][0]['content']);calls.append(body)
                return {'rows':[],'table_identity_limitation':{'kind':'source_cross_identification_missing',
                    'columns':['Internal'],'evidence_ids':['column:Internal'],
                    'reason':'SYNTHETIC author-local IDs, no supplied crosswalk'}},{'attempt_id':'synthetic'}
        service=SimpleNamespace(repo=repo,steps=Steps(),model_profile=lambda *args,**kwargs:ModelProfile('SYNTHETIC'))
        table={'table_id':'SYNTHETIC/table','columns':[{'name':'Internal','datatype':'short',
            'description':'SYNTHETIC internal identifiers in this work'}],
            'rows':[{'Internal':str(i)} for i in range(1000)]}
        checked,attempts=await interpret_identity_rows(service,job,{'target':TARGET},table,'Internal','votable',
            {'sha256':'synthetic','artifact_id':'synthetic'})
        assert len(calls)==1 and len(checked)==1000
        assert all(r['state']=='unresolved' and r['row_examined'] is False for r in checked)
        assert len(attempts)==32  # later rows are not claimed as individual model judgments
        with repo.read() as c:
            limit=repo.objects(c,tid,'catalog_identity_limitation')[0]
            assert len(limit['unexamined_row_indices'])==1000 and limit['target_absence_claimed'] is False
    asyncio.run(run())
