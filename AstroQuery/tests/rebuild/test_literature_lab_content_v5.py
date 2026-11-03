"""Required source boundaries cannot be silently waived by an exact label."""
from copy import deepcopy
import pytest
from astroquery_ai.runtime.errors import DomainError
from tests.rebuild.test_literature_lab_content import context
from tests.support.literature.content_v5 import checked


def response():
    checks={axis:{'required':axis in {'subject','quantity','native_representation'},
        'requested':'synthetic requested condition','source':'synthetic stated condition',
        'match':'same' if axis in {'subject','quantity','native_representation'} else 'not_applicable',
        'evidence':['B1']} for axis in ('subject','quantity','estimator','native_representation',
            'component_or_correction','reference','aperture')}
    return {**context(),'status':'U','match_reason':'Synthetic source explicitly supplies the target result',
        'boundary_checks':checks,'evidence':[{'blocks':['B1'],'role':'reported'}]}


@pytest.mark.parametrize('state',['different','unknown','not_applicable'])
def test_required_mismatch_cannot_be_overridden_by_u_or_exact(state):
    row=response();row['boundary_checks']['component_or_correction'].update(required=True,match=state)
    with pytest.raises(DomainError):checked(row,{1:'SYNTHETIC original'},blocks={'B1':{'page':1,'text':'SYNTHETIC original'}})


def test_optional_comparison_context_does_not_discard_an_identified_main_quantity():
    row=response();row['boundary_checks']['reference'].update(required=False,match='unknown')
    result=checked(row,{1:'SYNTHETIC original'},blocks={'B1':{'page':1,'text':'SYNTHETIC original'}})
    assert result['status']=='U' and result['formal_measurement'] is False
    row['boundary_checks']['reference']['match']='different'
    assert checked(row,{1:'SYNTHETIC original'},blocks={'B1':{'page':1,'text':'SYNTHETIC original'}})['status']=='U'
