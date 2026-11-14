from copy import deepcopy
import pytest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.source_restrictions import (
    catalog_information_prompt, decode_catalog_information, checked_source_information)


def test_short_actual_material_ids_are_exactly_decoded_not_model_generated_paths():
    texts = {'column:Error': 'SYNTHETIC mean error; no confidence level stated',
             'readme-note:2:0': 'SYNTHETIC contaminated measurements must be used cautiously'}
    payload = catalog_information_prompt({}, texts, [])
    response = {'items':[{'item_id':'SYNTHETIC row','state':'checked','checked_ids':['s1','s2'],
                         'caution_ids':['s2'],'note':'SYNTHETIC explicit caution applies'}]}
    result = decode_catalog_information(response, payload).items[0]
    assert result.checked_ids == list(texts)
    assert result.caution_ids == ['readme-note:2:0']
    broken = deepcopy(response); broken['items'][0]['checked_ids'] = [':']
    with pytest.raises(DomainError): decode_catalog_information(broken,payload)
    unchecked = checked_source_information({'state':'checked','raw_info':[':'],'caution_quotes':[], 'note':'invalid punctuation'},
        texts, measurement_id='SYNTHETIC row',measurement_version=1,evidence_refs=[],interpretation_ref=None)
    assert unchecked['state']=='unresolved'
    valid = checked_source_information({'state':'checked','raw_info':result.checked_ids,
        'caution_quotes':result.caution_ids,'note':result.note}, texts,
        measurement_id='SYNTHETIC row',measurement_version=1,evidence_refs=[],interpretation_ref=None)
    assert valid['state']=='checked' and len(valid['cautions'])==1
