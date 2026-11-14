"""Packing must preserve science exactly, including near-identical distinctions and scopes."""
from copy import deepcopy

from astroquery_ai.runtime.calls import input_upper_bound
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.prompt_compaction import compact_repeated_text


def unpack(packed):
    table=packed.get('shared_texts',{})
    def walk(value):
        if isinstance(value,dict) and set(value)=={'shared_text_ref'}:
            return table[value['shared_text_ref']]
        if isinstance(value,dict):return {key:walk(item) for key,item in value.items()}
        if isinstance(value,list):return [walk(item) for item in value]
        return value
    return walk({key:item for key,item in packed.items() if key not in {'shared_texts','shared_text_rule'}})


def test_shared_input_roundtrips_without_changing_ids_numbers_or_scientific_distinctions():
    repeated='Same physical definition, complete subject and units, conditions and exclusions. '*30
    prompt={'input_text':'SYNTHETIC query','allowed_candidate_ids':['P1','P2','P3'],
        'applicable_registry':[{'property_id':pid,'definition':repeated,
            'distinction':qualifier,'value':v,'threshold':0} for pid,qualifier,v in [
                ('P1','cluster aggregate; never member values',1),
                ('P2','member value; never cluster aggregate',-1),
                ('P3','an upper limit, not an estimate',None)]],
        'previous_semantic_batches':[{'text':repeated,'candidate_ids':['P1']}]}
    original=deepcopy(prompt);packed=compact_repeated_text(prompt)
    assert unpack(packed)==original and prompt==original
    assert packed['allowed_candidate_ids']==original['allowed_candidate_ids']
    assert len(canonical(packed))<len(canonical(original))


def test_wide_merge_fits_by_sharing_without_dropping_any_candidate():
    physical='完整的物理定义、对象范围、单位、误差约定和排除边界。'*12
    prompt={'applicable_registry':[{'property_id':f'P{i}','definition':physical,
        'distinction':f'Exact independent estimator {i}; no substitute estimators.'} for i in range(70)],
        'previous_semantic_batches':[{'explanation':physical,'candidate_property_ids':['P0','P69']}]}
    before=input_upper_bound([{'role':'user','content':canonical(prompt).decode()}])
    packed=compact_repeated_text(prompt)
    after=input_upper_bound([{'role':'user','content':canonical(packed).decode()}])
    assert before>48000 and after<48000
    assert len(packed['applicable_registry'])==70 and unpack(packed)==prompt


def test_no_repeated_prose_keeps_the_same_prompt():
    prompt={'allowed_candidate_ids':['P1'],'description':'one unique exact scientific statement'}
    assert compact_repeated_text(prompt) is prompt
